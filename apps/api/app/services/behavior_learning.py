"""Stage-17 transaction service: validate, persist and apply bounded evidence."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import (
    AttributeEvidence,
    BehaviorSignal,
    FeedbackReason,
    ProfileAdjustment,
    ProfileInference,
)
from app.models.matching import InteractionEvent
from app.models.policy import MatchPolicyVersion
from app.models.profile import (
    InferredPreference,
    ProfileAttribute,
    ProfileVersion,
    UserProfile,
)
from app.services.learning_policy import (
    LEARNING_POLICY_VERSION,
    AttributeTarget,
    BehaviorDecision,
    BehaviorEventFacts,
    evaluate_behavior,
)
from app.services.matching.types import SubjectContext


@dataclass(frozen=True)
class ProcessBehaviorCommand:
    event_date: date
    interaction_event_id: uuid.UUID
    learning_consent: bool
    cause_code: str | None = None
    attribute_targets: tuple[AttributeTarget, ...] = ()
    actual_impression: bool = True
    is_bot: bool = False
    is_employee: bool = False
    is_test: bool = False
    is_advertising: bool = False
    duplicate: bool = False
    independent_evidence_count: int = 1
    position_propensity: float | None = None


@dataclass(frozen=True)
class ProcessBehaviorResult:
    processing_id: uuid.UUID
    decision: BehaviorDecision
    profile_version: int
    affected_attributes: tuple[dict[str, Any], ...]
    idempotent_replay: bool = False


def _snapshot_hash(snapshot: dict[str, Any]) -> bytes:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).digest()


async def _ontology_key(db: AsyncSession, code: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = (
        await db.execute(
            text(
                "SELECT tv.taxonomy_version_id, c.concept_id "
                "FROM ontology.concept c "
                "JOIN ontology.concept_revision cr ON cr.concept_id = c.concept_id "
                "JOIN ontology.taxonomy_version tv ON tv.taxonomy_version_id = cr.taxonomy_version_id "
                "WHERE c.concept_code = :code AND cr.status = 'ACTIVE' "
                "AND tv.status = 'PUBLISHED' ORDER BY tv.published_at DESC LIMIT 1"
            ),
            {"code": code},
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


async def process_behavior_event(
    db: AsyncSession,
    *,
    subject: SubjectContext,
    command: ProcessBehaviorCommand,
) -> ProcessBehaviorResult:
    existing = (
        await db.execute(
            select(BehaviorSignal).where(
                BehaviorSignal.event_date == command.event_date,
                BehaviorSignal.event_log_id == command.interaction_event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        decision = BehaviorDecision(
            validation_status=existing.validation_status,
            signal_type=existing.signal_type,
            signal_strength=float(existing.signal_strength),
            decayed_signal=float(existing.decayed_signal),
            cause_code=existing.cause_code,
            cause_scope=existing.cause_scope,
            profile_update_required=False,
            recommendation_refresh_required=False,
            processing_mode="IDEMPOTENT_REPLAY",
            adjustments=(),
            invalid_reason_codes=tuple(existing.invalid_reason_codes or []),
            policy_version=LEARNING_POLICY_VERSION,
            input_fingerprint=existing.input_fingerprint,
        )
        profile = await db.get(UserProfile, subject.profile_id)
        return ProcessBehaviorResult(
            existing.behavior_signal_id,
            decision,
            profile.current_version if profile is not None else 0,
            (),
            True,
        )

    event = (
        await db.execute(
            select(InteractionEvent).where(
                InteractionEvent.event_date == command.event_date,
                InteractionEvent.interaction_event_id == command.interaction_event_id,
                InteractionEvent.tenant_id == subject.tenant_id,
                InteractionEvent.event_id == subject.event_id,
            )
        )
    ).scalar_one_or_none()
    if event is None:
        raise ValueError("interaction event not found in the signed tenant/event scope")

    profile = (
        await db.execute(
            select(UserProfile)
            .where(UserProfile.profile_id == subject.profile_id, UserProfile.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is None:
        raise ValueError("profile not found")

    policy = (
        await db.execute(
            select(MatchPolicyVersion).where(
                MatchPolicyVersion.version == LEARNING_POLICY_VERSION,
                MatchPolicyVersion.status == "PUBLISHED",
            )
        )
    ).scalar_one_or_none()
    if policy is None:
        raise RuntimeError(f"published learning policy missing: {LEARNING_POLICY_VERSION}")

    explicit_rows = await db.execute(
        select(ProfileAttribute.attribute_code).where(
            ProfileAttribute.profile_id == profile.profile_id,
            ProfileAttribute.active.is_(True),
            ProfileAttribute.source_type.in_(("USER_SELECTED", "USER_TYPED", "USER_EDITED", "REGISTRATION")),
        )
    )
    explicit_codes = frozenset(row[0] for row in explicit_rows)
    facts = BehaviorEventFacts(
        event_id=str(event.interaction_event_id),
        event_type=event.event_type,
        user_type=profile.user_type,
        occurred_at=event.occurred_at,
        received_at=event.received_at or datetime.now(UTC),
        cause_code=command.cause_code,
        attribute_targets=command.attribute_targets,
        learning_consent=command.learning_consent and event.consent_snapshot_id is not None,
        actual_impression=command.actual_impression,
        duplicate=command.duplicate,
        is_bot=command.is_bot,
        is_employee=command.is_employee,
        is_test=command.is_test,
        is_advertising=command.is_advertising,
        independent_evidence_count=command.independent_evidence_count,
        position_propensity=command.position_propensity,
        explicit_attribute_codes=explicit_codes,
        context=event.context_json or {},
    )
    decision = evaluate_behavior(facts, now=datetime.now(UTC))
    confidence = max(
        (item.confidence for item in decision.adjustments),
        default=0.0 if decision.signal_type == "NEUTRAL" else 0.25,
    )
    signal = BehaviorSignal(
        event_date=event.event_date,
        event_log_id=event.interaction_event_id,
        profile_id=profile.profile_id,
        match_policy_version_id=policy.match_policy_version_id,
        signal_type=decision.signal_type,
        signal_strength=decision.signal_strength,
        decayed_signal=decision.decayed_signal,
        cause_code=decision.cause_code,
        cause_scope=decision.cause_scope,
        confidence=confidence,
        validation_status=decision.validation_status,
        invalid_reason_codes=list(decision.invalid_reason_codes),
        input_fingerprint=decision.input_fingerprint,
        valid=decision.validation_status == "VALID",
        processed_at=datetime.now(UTC),
    )
    db.add(signal)
    await db.flush()

    affected: list[dict[str, Any]] = []
    applied_any = False
    for adjustment in decision.adjustments:
        db.add(
            AttributeEvidence(
                behavior_signal_id=signal.behavior_signal_id,
                attribute_code=adjustment.attribute_code,
                target_level=adjustment.target_level,
                propagation_weight=(abs(adjustment.adjustment) / max(abs(decision.decayed_signal), 1e-9)),
                decayed_value=decision.decayed_signal,
                positive=adjustment.adjustment >= 0,
            )
        )
        previous = (
            await db.execute(
                select(InferredPreference).where(
                    InferredPreference.profile_id == profile.profile_id,
                    InferredPreference.attribute_code == adjustment.attribute_code,
                )
            )
        ).scalar_one_or_none()
        previous_value = float(previous.inferred_score) if previous is not None else 0.0
        new_value = min(max(previous_value + adjustment.adjustment, -1.0), 1.0)
        status = adjustment.application_status
        applied = False
        if status == "APPLY_CANDIDATE":
            ontology_key = await _ontology_key(db, adjustment.attribute_code)
            if ontology_key is None:
                status = "SKIPPED"
            else:
                taxonomy_version_id, concept_id = ontology_key
                if previous is None:
                    previous = InferredPreference(
                        profile_id=profile.profile_id,
                        taxonomy_version_id=taxonomy_version_id,
                        concept_id=concept_id,
                        attribute_code=adjustment.attribute_code,
                        inferred_score=new_value,
                        positive_evidence_count=1 if adjustment.adjustment >= 0 else 0,
                        negative_evidence_count=1 if adjustment.adjustment < 0 else 0,
                        confidence=adjustment.confidence,
                        first_observed_at=event.occurred_at,
                        last_observed_at=event.occurred_at,
                    )
                    db.add(previous)
                else:
                    previous.inferred_score = new_value
                    previous.positive_evidence_count += int(adjustment.adjustment >= 0)
                    previous.negative_evidence_count += int(adjustment.adjustment < 0)
                    previous.confidence = max(float(previous.confidence), adjustment.confidence)
                    previous.last_observed_at = max(previous.last_observed_at or event.occurred_at, event.occurred_at)
                applied = True
                applied_any = True

        inference_status = "APPLIED" if applied else "CANDIDATE"
        db.add(
            ProfileInference(
                profile_id=profile.profile_id,
                attribute_code=adjustment.attribute_code,
                inferred_value={"score": new_value, "adjustment": adjustment.adjustment},
                condition_json=None,
                confidence=adjustment.confidence,
                evidence_count=command.independent_evidence_count,
                first_observed_at=event.occurred_at,
                last_observed_at=event.occurred_at,
                status=inference_status,
                user_confirmed=False,
                source_policy_version=LEARNING_POLICY_VERSION,
            )
        )
        db.add(
            ProfileAdjustment(
                profile_id=profile.profile_id,
                attribute_code=adjustment.attribute_code,
                previous_value={"score": previous_value},
                adjustment_value=adjustment.adjustment,
                new_value={"score": new_value},
                source_type="FEEDBACK" if event.event_type.startswith("FEEDBACK") else "BEHAVIOR",
                source_reference_id=signal.behavior_signal_id,
                confidence=adjustment.confidence,
                application_status="APPLIED" if applied else status,
                applied=applied,
                applied_at=datetime.now(UTC) if applied else None,
            )
        )
        affected.append({
            "code": adjustment.attribute_code,
            "adjustment": adjustment.adjustment,
            "status": "APPLIED" if applied else status,
        })

    if decision.cause_code and event.event_type.startswith("FEEDBACK"):
        db.add(
            FeedbackReason(
                behavior_signal_id=signal.behavior_signal_id,
                reason_code=decision.cause_code,
                sentiment=decision.signal_type,
                intensity=abs(decision.signal_strength),
                source="USER",
                confidence=1.0,
            )
        )

    if applied_any:
        profile.current_version += 1
        profile.row_version += 1
        snapshot = {
            "profile_id": str(profile.profile_id),
            "version": profile.current_version,
            "source_event_id": str(event.interaction_event_id),
            "policy_version": LEARNING_POLICY_VERSION,
            "behavior_adjustments": affected,
        }
        db.add(
            ProfileVersion(
                profile_id=profile.profile_id,
                version_number=profile.current_version,
                snapshot_json=snapshot,
                snapshot_hash=_snapshot_hash(snapshot),
                change_reason="BEHAVIOR_LEARNING",
                source_event_id=event.interaction_event_id,
            )
        )

    await db.flush()
    return ProcessBehaviorResult(
        processing_id=signal.behavior_signal_id,
        decision=decision,
        profile_version=profile.current_version,
        affected_attributes=tuple(affected),
    )

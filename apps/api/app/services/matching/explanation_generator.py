"""⑪ Explanation Generator - docs/05-ai-matching-engine-architecture.md 5.11절.

최종 추천 결과에 대해 사용자가 이해할 수 있는 추천 이유를 생성한다. 05번 문서 10.1절
"AI 설명 생성 실패" 절은 "미리 정의된 추천 이유 템플릿 사용"을 정상적인 대체 경로로 이미
전제하므로, 이번 MVP는 처음부터 템플릿 방식만 구현한다. LLM은 사실·근거 코드를 만들 수
없으며, 향후 문장 표현에 사용하더라도 공통 facade가 확정한 claim만 바꿔 써야 한다.

생성 방식(5.11절 그대로):
    1. 공통 facade가 실제 점수 기여도·양면 상태와 어댑터의 evidence_ref를 교차 검증한다.
    2. facade가 허용 코드, 근거 참조, 원천 component, claim 지문을 확정한다.
    3. 이 모듈은 확정 claim을 템플릿 문장으로 투영할 뿐 사실을 추가하지 않는다.
    4. 정책 버전·claim 지문을 포함한 입력 지문을 생성해 저장 계약에서 검증한다.
    5. 사용자 화면에 최대 2~3개 표시.

금지 근거(5.11절): 성별·연령 기반 추정, 사용자가 입력하지 않은 소비성향, 업체 미제공
품질·효능 주장, 내부 점수·가중치, 다른 사용자의 개인 데이터, 광고비·스폰서 여부. 이 템플릿
집합과 facade allowlist는 위 항목을 애초에 다루지 않는다. 점수 provenance가 없는 격리된
레거시 호출에는 기존 feature 템플릿을 호환 경로로 유지하지만 실제 추천 파이프라인은 facade
claim 경로만 사용한다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from meet_ai.engine import (
    MatchingMode,
    ReasonClaim,
    derive_directional_reason_claims,
    derive_reciprocal_reason_claims,
)

from app.services.matching.types import (
    MatchCandidate,
    MatchReasonDraft,
    ResolvedProfile,
)

EXPLANATION_POLICY_VERSION = "explain-template-v1.2-engine-claims"

#: feature 키 -> (reason_code, 문장 템플릿). 값이 0.5 이상일 때만 근거로 채택한다.
_GENERAL_TEMPLATES: dict[str, tuple[str, str]] = {
    "taste_match": ("TASTE_MATCH", "선호하신 맛 특성과 잘 맞습니다."),
    "aroma_match": ("AROMA_MATCH", "선호하신 향과 잘 맞습니다."),
    "category_match": ("CATEGORY_MATCH", "관심 있으신 주종과 일치합니다."),
    "alcohol_match": ("ALCOHOL_MATCH", "선호하신 도수대와 맞습니다."),
    "price_match": ("PRICE_MATCH", "희망 가격대에서 만나볼 수 있습니다."),
    "availability_score": ("AVAILABILITY", "지금 시음하거나 구매할 수 있습니다."),
    "usage_match": ("GOAL_MATCH", "찾고 계신 목적과 잘 맞는 제품입니다."),
}

_BUYER_TEMPLATES: dict[str, tuple[str, str]] = {
    "category_match": ("CATEGORY_MATCH", "찾고 계신 제품군과 일치합니다."),
    "channel_match": ("CHANNEL_MATCH", "희망하신 유통채널과 일치합니다."),
    "region_match": ("REGION_MATCH", "희망하신 공급지역과 일치합니다."),
    "moq_match": ("MOQ_MATCH", "희망하신 주문 조건에 맞는 최소주문수량입니다."),
    "capacity_match": ("CAPACITY_MATCH", "필요하신 물량을 공급할 수 있는 역량입니다."),
    "oem_availability": ("OEM_AVAILABLE", "OEM 거래가 가능합니다."),
    "private_label_availability": (
        "PRIVATE_LABEL_AVAILABLE",
        "PB·자체브랜드 거래가 가능합니다.",
    ),
    "export_availability": ("EXPORT_AVAILABLE", "수출 거래가 가능합니다."),
    "preferred_buyer_match": (
        "PREFERRED_BUYER_MATCH",
        "업체가 희망하는 바이어 유형과 일치합니다.",
    ),
}

_MAX_REASONS = 3
_FEATURE_MIN_THRESHOLD = 0.5

_GENERAL_COMPONENT_FIELDS = {
    "goal": ("GOAL_MATCH", "goal_match"),
    "category": ("CATEGORY_MATCH", "category_match"),
    "sensory": ("TASTE_MATCH", "sensory_match"),
    "price": ("PRICE_MATCH", "price_match"),
    "alcohol": ("ALCOHOL_MATCH", "alcohol_match"),
    "service": ("SERVICE_MATCH", "service_match"),
    "usage": ("USAGE_MATCH", "usage_feature_match"),
    "trust": ("DATA_TRUST", "data_trust"),
}
_BUYER_COMPONENT_FIELDS = {
    "business_goal": ("BUSINESS_GOAL_MATCH", "business_goal_match"),
    "product": ("PRODUCT_MATCH", "product_match"),
    "channel": ("CHANNEL_MATCH", "channel_match"),
    "price": ("PRICE_MATCH", "price_match"),
    "moq": ("MOQ_MATCH", "moq_match"),
    "capacity": ("CAPACITY_MATCH", "capacity_match"),
    "region": ("REGION_MATCH", "region_match"),
    "cooperation": ("COOPERATION_MATCH", "cooperation_match"),
    "meeting": ("MEETING_AVAILABLE", "meeting_match"),
    "trust": ("DATA_TRUST", "trade_trust"),
}

_CLAIM_TEMPLATES: dict[str, str] = {
    code: text for code, text in (*_GENERAL_TEMPLATES.values(), *_BUYER_TEMPLATES.values())
}
_CLAIM_TEMPLATES.update(
    {
        "BUSINESS_GOAL_MATCH": "찾고 계신 사업 목적과 잘 맞는 업체입니다.",
        "PRODUCT_MATCH": "찾고 계신 제품군과 일치합니다.",
        "SENSORY_MATCH": "선호하신 맛과 향 특성과 잘 맞습니다.",
        "SERVICE_MATCH": "원하시는 서비스 조건과 잘 맞습니다.",
        "USAGE_MATCH": "원하시는 이용 목적과 잘 맞습니다.",
        "BEHAVIOR_MATCH": "동의하신 관심 이력과 관련성이 높습니다.",
        "DATA_TRUST": "승인된 정보의 완성도와 신뢰도가 높습니다.",
        "COOPERATION_MATCH": "희망하신 협업 방식과 잘 맞습니다.",
        "MUTUAL_CHANNEL_MATCH": "바이어와 업체가 희망하는 유통 채널이 서로 맞습니다.",
        "MUTUAL_PRODUCT_MATCH": "바이어의 제품 수요와 업체의 공급 포트폴리오가 서로 맞습니다.",
        "DIRECTION_IMBALANCE": "양측 적합도 차이가 있어 추가 확인이 필요합니다.",
        "SEMANTIC_MATCH": "입력하신 내용과 승인된 소개 정보의 의미가 관련됩니다.",
        "KEYWORD_MATCH": "검색어가 승인된 업체·제품 정보와 일치합니다.",
    }
)


def _reason(
    code: str,
    text: str,
    evidence_refs: list[str],
    *,
    contribution: float | None,
    source_fingerprint: str | None = None,
) -> MatchReasonDraft:
    lineage = {
        "policy_version": EXPLANATION_POLICY_VERSION,
        "code": code,
        "text": text,
        "evidence_refs": evidence_refs,
        "contribution": contribution,
        "generated_by": "TEMPLATE",
        "source_fingerprint": source_fingerprint,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            lineage,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return MatchReasonDraft(
        code=code,
        text=text,
        evidence_refs=evidence_refs,
        contribution_score=contribution,
        generated_by="TEMPLATE",
        explanation_policy_version=EXPLANATION_POLICY_VERSION,
        input_fingerprint=fingerprint,
    )


def _context_reasons(candidate: MatchCandidate) -> list[MatchReasonDraft]:
    reasons: list[MatchReasonDraft] = []
    if candidate.availability.get("meeting"):
        availability_owner = (
            candidate.participation_id
            or candidate.exhibitor_id
            or candidate.object_id
        )
        reasons.append(
            _reason(
                "MEETING_AVAILABLE",
                "현재 상담 가능한 시간이 있습니다.",
                [f"availability_slot:owner:{availability_owner}"],
                contribution=candidate.score_components.get("context_score"),
            )
        )
    if (
        candidate.estimated_walk_minutes is not None
        and candidate.estimated_walk_minutes <= 10
    ):
        booth_id = candidate.payload.get("booth_id") or candidate.object_id
        reasons.append(
            _reason(
                "NEARBY",
                f"현재 위치에서 도보 {candidate.estimated_walk_minutes}분 거리입니다.",
                [f"booth:{booth_id}:location"],
                contribution=candidate.score_components.get("context_score"),
            )
        )
    return reasons


def _reason_evidence(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    contributions: Mapping[str, float],
    fields: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    profile_ref = f"profile:{profile.profile_id}:v{profile.profile_version}"
    target = candidate.object_type.lower()
    evidence: dict[str, tuple[str, str]] = {}
    for component in contributions:
        definition = fields.get(component)
        if definition is None:
            continue
        code, feature_name = definition
        if candidate.features.get(feature_name) is None:
            continue
        evidence[code] = (
            profile_ref,
            f"{target}:{candidate.object_id}:{feature_name}",
        )
    return evidence


def _facade_claims(
    candidate: MatchCandidate, profile: ResolvedProfile
) -> tuple[ReasonClaim, ...]:
    channels = tuple(candidate.source_channels)
    if candidate.reciprocal_policy_version is not None:
        evidence: dict[str, tuple[str, ...]] = {}
        profile_ref = f"profile:{profile.profile_id}:v{profile.profile_version}"
        target_ref = f"{candidate.object_type.lower()}:{candidate.object_id}"
        if (
            "channel" in candidate.directional_contributions
            and "channel" in candidate.exhibitor_directional_contributions
        ):
            evidence["MUTUAL_CHANNEL_MATCH"] = (
                f"{profile_ref}:channel",
                f"{target_ref}:preferred_channel_match",
            )
        if (
            "product" in candidate.directional_contributions
            and "portfolio" in candidate.exhibitor_directional_contributions
        ):
            evidence["MUTUAL_PRODUCT_MATCH"] = (
                f"{profile_ref}:product",
                f"{target_ref}:portfolio_match",
            )
        if (
            "meeting" in candidate.directional_contributions
            and "meeting_readiness" in candidate.exhibitor_directional_contributions
            and candidate.availability.get("meeting")
        ):
            owner_id = candidate.participation_id or candidate.exhibitor_id
            if owner_id is not None:
                evidence["MEETING_AVAILABLE"] = (
                    f"availability_slot:owner:{owner_id}",
                )
        if (
            candidate.imbalance_value is not None
            and candidate.directional_score_fingerprint
            and candidate.exhibitor_directional_score_fingerprint
        ):
            evidence["DIRECTION_IMBALANCE"] = (
                f"score:{candidate.directional_score_fingerprint}",
                f"score:{candidate.exhibitor_directional_score_fingerprint}",
            )
        return derive_reciprocal_reason_claims(
            candidate.directional_contributions,
            candidate.exhibitor_directional_contributions,
            imbalance_value=candidate.imbalance_value or 0,
            recall_channels=channels,
            reason_evidence=evidence,
        )

    if candidate.directional_policy_version is None:
        return ()
    buyer = profile.user_type == "BUYER"
    fields = _BUYER_COMPONENT_FIELDS if buyer else _GENERAL_COMPONENT_FIELDS
    evidence = _reason_evidence(
        candidate,
        profile,
        candidate.directional_contributions,
        fields,
    )
    if "VECTOR" in candidate.source_channels:
        evidence["SEMANTIC_MATCH"] = (
            f"{candidate.object_type.lower()}:{candidate.object_id}:approved_summary",
        )
    return derive_directional_reason_claims(
        MatchingMode.BUYER_TO_EXHIBITOR if buyer else MatchingMode.GENERAL_VISITOR,
        candidate.directional_contributions,
        recall_channels=channels,
        reason_evidence=evidence,
    )


def _legacy_feature_reasons(
    candidate: MatchCandidate, profile: ResolvedProfile
) -> list[MatchReasonDraft]:
    """Compatibility path for isolated, pre-engine callers; runtime uses facade claims."""

    templates = _BUYER_TEMPLATES if profile.user_type == "BUYER" else _GENERAL_TEMPLATES
    profile_ref = f"profile:{profile.profile_id}:v{profile.profile_version}"
    ranked = sorted(
        (
            (key, value)
            for key, value in candidate.features.items()
            if key in templates
            and value is not None
            and value >= _FEATURE_MIN_THRESHOLD
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        _reason(
            templates[key][0],
            templates[key][1],
            [
                profile_ref,
                f"{candidate.object_type.lower()}:{candidate.object_id}:{key}",
            ],
            contribution=value,
        )
        for key, value in ranked
    ]


def generate_explanations(
    candidates: list[MatchCandidate], *, profile: ResolvedProfile
) -> None:
    for candidate in candidates:
        reasons = _context_reasons(candidate)
        claims = _facade_claims(candidate, profile)
        for claim in claims:
            text = _CLAIM_TEMPLATES.get(claim.code)
            if text is None:
                continue
            reasons.append(
                _reason(
                    claim.code,
                    text,
                    list(claim.evidence_refs),
                    contribution=(
                        None
                        if claim.contribution_score is None
                        else float(claim.contribution_score)
                    ),
                    source_fingerprint=claim.claim_fingerprint,
                )
            )
        if not claims and candidate.directional_policy_version is None:
            reasons.extend(_legacy_feature_reasons(candidate, profile))

        if not reasons:
            reasons.append(
                _reason(
                    "EXPLORATION_CANDIDATE",
                    "직접 일치하는 정보가 부족해 탐색 후보로 제안합니다.",
                    [f"{candidate.object_type.lower()}:{candidate.object_id}"],
                    contribution=None,
                )
            )

        reasons = sorted(
            reasons,
            key=lambda reason: (
                -(reason.contribution_score or 0.0),
                reason.code,
            ),
        )[:_MAX_REASONS]
        for index, reason in enumerate(reasons):
            reason.display_order = index
        candidate.reasons = reasons

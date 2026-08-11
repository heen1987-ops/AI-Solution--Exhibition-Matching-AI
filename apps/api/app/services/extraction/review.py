"""전시업체 확인/수정/거절, 검수제출, 운영자 승인/반려/보완요청 - 상태전이 비즈니스 로직.

라우터(``app/api/v1/routers/extraction.py``)는 인증/404/403만 다루고, 실제 전이 규칙은
전부 여기 있다 - HTTP 계층 없이 단위 테스트 가능하게 하기 위함
(``app/services/buyer_profile``와 같은 분리 원칙).

절대 하지 않는 일: 이 모듈의 어떤 함수도 ``app.models.exhibitor``의 어떤 테이블에도
쓰지 않는다(import조차 하지 않는다) - 이 트랙의 하드 경계
(``tests/test_extraction_api.py::test_no_router_path_ever_touches_business_tables``가 강제).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import (
    APPROVABLE_REVIEW_STATUSES,
    ContentReviewAction,
    ContentReviewRequest,
    ExtractedAttribute,
    PublishedContentVersion,
    SourceEvidence,
)
from app.services.extraction.attribute_schema import is_critical_trade_condition
from app.services.extraction.errors import (
    ExtractionNotFoundError,
    InvalidTransitionError,
    ReviewRequestNotFoundError,
    SubmitReviewValidationError,
)
from app.services.indexing.service import regenerate_exhibitor_documents

_NON_TERMINAL_FOR_SUBMIT = ("REJECTED_BY_EXHIBITOR", "SUPERSEDED")
_EVIDENCE_EXEMPT_FACT_TYPES = ("SELF_DECLARED", "UNKNOWN")


async def _get_extraction_or_raise(db: AsyncSession, extraction_id: uuid.UUID) -> ExtractedAttribute:
    row = await db.get(ExtractedAttribute, extraction_id)
    if row is None:
        raise ExtractionNotFoundError(extraction_id)
    return row


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Exhibitor-facing: patch / confirm
# ---------------------------------------------------------------------------


async def patch_extraction(
    db: AsyncSession,
    extraction_id: uuid.UUID,
    *,
    fields: dict,
    actor_user_id: uuid.UUID,
) -> ExtractedAttribute:
    """WAVE2D-CONTRACTS §9 PATCH - review_status는 절대 건드리지 않는다. ``fields``는
    라우터가 ``ExtractionPatchRequest.model_dump(exclude_unset=True)``로 넘긴, 실제로
    요청 본문에 있던 필드만 담은 dict다(부분 PATCH의미)."""

    row = await _get_extraction_or_raise(db, extraction_id)

    previous = {"normalized_value": row.normalized_value, "visibility": row.visibility}
    changed = False
    if "normalized_value" in fields:
        row.normalized_value = fields["normalized_value"]
        changed = True
    if "visibility" in fields and fields["visibility"] is not None:
        row.visibility = fields["visibility"]
        changed = True

    if changed:
        row.edited_by_exhibitor = True
        db.add(
            ContentReviewAction(
                extraction_id=row.extraction_id,
                actor_user_id=actor_user_id,
                actor_role="EXHIBITOR",
                action_type="MODIFY",
                previous_value=previous,
                new_value={"normalized_value": row.normalized_value, "visibility": row.visibility},
                reason=fields.get("reason"),
            )
        )
    return row


async def confirm_extraction(
    db: AsyncSession,
    extraction_id: uuid.UUID,
    *,
    decision: str,
    reason: str | None,
    actor_user_id: uuid.UUID,
) -> ExtractedAttribute:
    """WAVE2D-CONTRACTS §9 confirm - §3 전이표: PROPOSED -> CONFIRMED_BY_EXHIBITOR |
    MODIFIED_BY_EXHIBITOR | REJECTED_BY_EXHIBITOR. ``edited_by_exhibitor``가 True면(즉 앞서
    PATCH로 값을 고쳤으면) confirm은 MODIFIED_BY_EXHIBITOR로, 아니면 CONFIRMED_BY_EXHIBITOR로
    간다 - PATCH 단독으로는 절대 이 상태들로 넘어가지 않는다는 계약을 이 함수가 지킨다."""

    row = await _get_extraction_or_raise(db, extraction_id)
    if row.review_status != "PROPOSED":
        raise InvalidTransitionError(current_status=row.review_status, attempted=f"confirm:{decision}")

    now = _now()
    if decision == "reject":
        row.review_status = "REJECTED_BY_EXHIBITOR"
        row.rejection_reason = reason
        action_type = "REJECT"
    else:
        row.review_status = "MODIFIED_BY_EXHIBITOR" if row.edited_by_exhibitor else "CONFIRMED_BY_EXHIBITOR"
        # UNKNOWN 행을 확인하는 것은 "값을 확정"이 아니라 "빈 값을 봤고 인지했다"는 뜻이라
        # 감사로그에서 구분해 둔다(제출 검증의 "critical trade-condition UNKNOWN 인지" 규칙이
        # 바로 이 review_status 전이를 근거로 삼는다 - submit_for_review 참고).
        action_type = "ACKNOWLEDGE_UNKNOWN" if row.fact_type == "UNKNOWN" else "CONFIRM"

    row.reviewed_by_exhibitor_user_id = actor_user_id
    row.reviewed_by_exhibitor_at = now
    db.add(
        ContentReviewAction(
            extraction_id=row.extraction_id,
            actor_user_id=actor_user_id,
            actor_role="EXHIBITOR",
            action_type=action_type,
            new_value={"review_status": row.review_status},
            reason=reason,
        )
    )
    return row


# ---------------------------------------------------------------------------
# Exhibitor-facing: submit-review
# ---------------------------------------------------------------------------


async def _pending_checks(db: AsyncSession, document_id: uuid.UUID) -> list[dict]:
    stmt = select(ExtractedAttribute).where(ExtractedAttribute.document_id == document_id)
    rows = list((await db.execute(stmt)).scalars().all())

    checks: list[dict] = []
    for row in rows:
        if row.review_status == "PROPOSED":
            if row.fact_type == "UNKNOWN" and is_critical_trade_condition(row.attribute_code):
                checks.append(
                    {
                        "code": "TRADE_CONDITION_UNKNOWN_UNACKNOWLEDGED",
                        "message": (
                            f"필수 거래조건 항목 '{row.attribute_code}'을(를) 확인할 수 없었습니다. "
                            "확인 후 제출해야 합니다."
                        ),
                        "extraction_id": row.extraction_id,
                        "attribute_code": row.attribute_code,
                    }
                )
            else:
                checks.append(
                    {
                        "code": "EXTRACTIONS_PENDING_REVIEW",
                        "message": f"'{row.attribute_code}' 항목이 아직 확인/거절되지 않았습니다.",
                        "extraction_id": row.extraction_id,
                        "attribute_code": row.attribute_code,
                    }
                )
            continue

        if row.review_status == "CONFLICTED":
            checks.append(
                {
                    "code": "CONFLICTS_UNRESOLVED",
                    "message": f"'{row.attribute_code}' 항목에 해소되지 않은 충돌이 있습니다.",
                    "extraction_id": row.extraction_id,
                    "attribute_code": row.attribute_code,
                }
            )
            continue

        if row.review_status in _NON_TERMINAL_FOR_SUBMIT:
            continue

        if row.fact_type not in _EVIDENCE_EXEMPT_FACT_TYPES:
            evidence_count_stmt = select(func.count(SourceEvidence.evidence_id)).where(
                SourceEvidence.extraction_id == row.extraction_id
            )
            evidence_count = (await db.execute(evidence_count_stmt)).scalar_one()
            if evidence_count == 0:
                checks.append(
                    {
                        "code": "EVIDENCE_MISSING",
                        "message": f"'{row.attribute_code}' 항목에 근거 문서 인용이 없습니다.",
                        "extraction_id": row.extraction_id,
                        "attribute_code": row.attribute_code,
                    }
                )

        if row.visibility is None:
            checks.append(
                {
                    "code": "VISIBILITY_NOT_SET",
                    "message": f"'{row.attribute_code}' 항목에 공개범위가 설정되지 않았습니다.",
                    "extraction_id": row.extraction_id,
                    "attribute_code": row.attribute_code,
                }
            )

    return checks


async def submit_for_review(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> ContentReviewRequest:
    checks = await _pending_checks(db, document_id)
    if checks:
        raise SubmitReviewValidationError(checks)

    stmt = (
        select(ContentReviewRequest)
        .where(ContentReviewRequest.document_id == document_id)
        .order_by(ContentReviewRequest.submitted_at.desc())
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    now = _now()
    if existing is not None and existing.status == "CHANGES_REQUESTED":
        existing.status = "SUBMITTED"
        existing.submitted_by_user_id = actor_user_id
        existing.submitted_at = now
        review_request = existing
    elif existing is not None and existing.status in ("SUBMITTED", "IN_OPERATOR_REVIEW"):
        review_request = existing
    else:
        review_request = ContentReviewRequest(
            tenant_id=tenant_id,
            exhibitor_id=exhibitor_id,
            document_id=document_id,
            status="SUBMITTED",
            submitted_by_user_id=actor_user_id,
        )
        db.add(review_request)
        await db.flush()

    db.add(
        ContentReviewAction(
            review_request_id=review_request.review_request_id,
            actor_user_id=actor_user_id,
            actor_role="EXHIBITOR",
            action_type="SUBMIT_FOR_REVIEW",
            new_value={"status": review_request.status},
        )
    )
    return review_request


# ---------------------------------------------------------------------------
# Operator-facing
# ---------------------------------------------------------------------------


async def claim_review_requests(
    db: AsyncSession, *, review_request_ids: list[uuid.UUID], actor_user_id: uuid.UUID
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    claimed: list[uuid.UUID] = []
    already_claimed: list[uuid.UUID] = []
    for review_request_id in review_request_ids:
        row = await db.get(ContentReviewRequest, review_request_id)
        if row is None:
            raise ReviewRequestNotFoundError(review_request_id)
        if row.status != "SUBMITTED":
            already_claimed.append(review_request_id)
            continue
        row.status = "IN_OPERATOR_REVIEW"
        row.claimed_by_user_id = actor_user_id
        db.add(
            ContentReviewAction(
                review_request_id=row.review_request_id,
                actor_user_id=actor_user_id,
                actor_role="OPERATOR",
                action_type="CLAIM",
            )
        )
        claimed.append(review_request_id)
    return claimed, already_claimed


async def approve_extraction(
    db: AsyncSession,
    extraction_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    reason: str | None,
    event_id: uuid.UUID | None = None,
) -> tuple[ExtractedAttribute, PublishedContentVersion | None]:
    """§3: CONFIRMED_BY_EXHIBITOR | MODIFIED_BY_EXHIBITOR | CONFLICTED -> APPROVED_BY_OPERATOR.

    §4 binding rule: AI_INFERRED는 확인+승인 경로를 건너뛸 수 없다 - 이 함수가 유일한 승인
    경로이고 ``APPROVABLE_REVIEW_STATUSES`` 밖에서 호출하면 무조건 막히므로, PROPOSED에서
    곧바로 승인하는 지름길은 애초에 존재하지 않는다(모든 fact_type에 동일하게 적용).

    MERGE STEP 26: 발행본(``PublishedContentVersion``)이 실제로 만들어졌고 호출자가
    ``event_id``를 넘겼을 때만 ``regenerate_exhibitor_documents(trigger='APPROVE')``를
    호출해 검색/추천 색인을 갱신한다. ``event_id``는 이 함수가 스스로 구하지 않는다 -
    모듈 docstring의 하드 경계("``app.models.exhibitor``를 import조차 하지 않는다")
    때문에 호출자(``app/api/v1/routers/extraction.py``)가
    ``app/core/router_auth.py::get_exhibitor_current_event_id``로 미리 구해 값으로
    넘긴다. ``regenerate_exhibitor_documents``는 스스로 커밋하지 않으므로(그 모듈
    docstring 참고) 이 호출은 라우터의 기존 트랜잭션 안에 그대로 합쳐진다.
    """

    row = await _get_extraction_or_raise(db, extraction_id)
    if row.review_status not in APPROVABLE_REVIEW_STATUSES:
        raise InvalidTransitionError(current_status=row.review_status, attempted="approve")

    row.review_status = "APPROVED_BY_OPERATOR"
    row.reviewed_by_operator_user_id = actor_user_id
    row.reviewed_by_operator_at = _now()

    published_version: PublishedContentVersion | None = None
    if row.normalized_value is not None and row.visibility is not None:
        max_version_stmt = select(func.max(PublishedContentVersion.version_no)).where(
            PublishedContentVersion.extraction_id == row.extraction_id
        )
        current_max = (await db.execute(max_version_stmt)).scalar()
        next_version_no = (current_max or 0) + 1

        if current_max:
            supersede_stmt = select(PublishedContentVersion).where(
                PublishedContentVersion.extraction_id == row.extraction_id,
                PublishedContentVersion.superseded_at.is_(None),
            )
            for prior in (await db.execute(supersede_stmt)).scalars().all():
                prior.superseded_at = _now()

        published_version = PublishedContentVersion(
            extraction_id=row.extraction_id,
            tenant_id=row.tenant_id,
            exhibitor_id=row.exhibitor_id,
            entity_type=row.entity_type,
            entity_reference=row.entity_reference,
            attribute_code=row.attribute_code,
            value=row.normalized_value,
            concept_codes=row.concept_codes,
            visibility=row.visibility,
            version_no=next_version_no,
            published_by_user_id=actor_user_id,
        )
        db.add(published_version)
        # version_id는 flush 시점에 채워지는 python-side default라, 라우터가 응답에 담기
        # 전에 반드시 flush해야 한다 (안 하면 published_version_id가 null로 나간다).
        await db.flush()

        if event_id is not None:
            await regenerate_exhibitor_documents(
                db,
                tenant_id=row.tenant_id,
                event_id=event_id,
                exhibitor_id=row.exhibitor_id,
                trigger="APPROVE",
                requested_by_user_id=actor_user_id,
            )

    db.add(
        ContentReviewAction(
            extraction_id=row.extraction_id,
            actor_user_id=actor_user_id,
            actor_role="OPERATOR",
            action_type="APPROVE",
            reason=reason,
        )
    )
    return row, published_version


async def reject_extraction(
    db: AsyncSession, extraction_id: uuid.UUID, *, actor_user_id: uuid.UUID, reason: str | None
) -> ExtractedAttribute:
    row = await _get_extraction_or_raise(db, extraction_id)
    if row.review_status not in APPROVABLE_REVIEW_STATUSES:
        raise InvalidTransitionError(current_status=row.review_status, attempted="reject")

    row.review_status = "REJECTED_BY_OPERATOR"
    row.reviewed_by_operator_user_id = actor_user_id
    row.reviewed_by_operator_at = _now()
    row.rejection_reason = reason
    db.add(
        ContentReviewAction(
            extraction_id=row.extraction_id,
            actor_user_id=actor_user_id,
            actor_role="OPERATOR",
            action_type="REJECT_REVIEW",
            reason=reason,
        )
    )
    return row


async def request_changes(
    db: AsyncSession, review_request_id: uuid.UUID, *, actor_user_id: uuid.UUID, comment: str
) -> ContentReviewRequest:
    """§1: OPERATOR_REVIEW -> EXHIBITOR_REVIEW 보완요청. 문서 단위이므로 개별 extraction의
    review_status는 건드리지 않는다 - 전시업체가 다시 손봐야 할 항목은 여전히 각자의
    review_status(대부분 CONFIRMED_BY_EXHIBITOR/MODIFIED_BY_EXHIBITOR)를 유지한다."""

    row = await db.get(ContentReviewRequest, review_request_id)
    if row is None:
        raise ReviewRequestNotFoundError(review_request_id)
    if row.status not in ("SUBMITTED", "IN_OPERATOR_REVIEW"):
        raise InvalidTransitionError(current_status=row.status, attempted="request-changes")

    row.status = "CHANGES_REQUESTED"
    row.operator_comment = comment
    row.decided_by_user_id = actor_user_id
    row.decided_at = _now()
    db.add(
        ContentReviewAction(
            review_request_id=row.review_request_id,
            actor_user_id=actor_user_id,
            actor_role="OPERATOR",
            action_type="REQUEST_CHANGES",
            reason=comment,
        )
    )
    return row


async def list_admin_review_queue(
    db: AsyncSession,
    *,
    exhibitor_id: uuid.UUID | None = None,
    fact_type: str | None = None,
) -> list[dict]:
    """``GET /admin/ai-review`` - WAVE2D-CONTRACTS §4 "AI_INFERRED가 먼저 보이도록 정렬/
    필터 가능해야 한다"를 만족한다.

    ``document_type`` 필터는 의도적으로 지원하지 않는다: 이 함수는 ``document.source_document``
    (BACKEND-DOCUMENT 트랙 소유, 아직 마이그레이션 없음)를 조인하지 않는다 - 소프트참조 원칙
    (``app/models/extraction.py`` 모듈 docstring)을 쿼리 레이어까지 일관되게 지키기 위해서다.
    통합 단계에서 그 테이블의 마이그레이션이 들어오면 조인을 추가해 확장할 수 있다(TODO,
    이 함수의 반환 dict에 이미 ``document_id``가 있으므로 호출자가 필요하면 별도 조회로
    보완할 수 있다).
    """

    request_stmt = select(ContentReviewRequest).where(
        ContentReviewRequest.status.in_(("SUBMITTED", "IN_OPERATOR_REVIEW"))
    )
    if exhibitor_id is not None:
        request_stmt = request_stmt.where(ContentReviewRequest.exhibitor_id == exhibitor_id)
    request_stmt = request_stmt.order_by(ContentReviewRequest.submitted_at.asc())
    requests = list((await db.execute(request_stmt)).scalars().all())

    items: list[dict] = []
    for review_request in requests:
        if review_request.document_id is None:
            pending_rows: list[ExtractedAttribute] = []
        else:
            attr_stmt = select(ExtractedAttribute).where(
                ExtractedAttribute.document_id == review_request.document_id,
                ExtractedAttribute.review_status.in_(APPROVABLE_REVIEW_STATUSES),
            )
            pending_rows = list((await db.execute(attr_stmt)).scalars().all())

        if fact_type is not None and not any(r.fact_type == fact_type for r in pending_rows):
            continue

        items.append(
            {
                "review_request_id": review_request.review_request_id,
                "document_id": review_request.document_id,
                "exhibitor_id": review_request.exhibitor_id,
                "status": review_request.status,
                "submitted_at": review_request.submitted_at,
                "claimed_by_user_id": review_request.claimed_by_user_id,
                "pending_extraction_count": len(pending_rows),
                "ai_inferred_count": sum(1 for r in pending_rows if r.fact_type == "AI_INFERRED"),
                "has_unresolved_conflict": any(r.review_status == "CONFLICTED" for r in pending_rows),
            }
        )

    # AI_INFERRED가 있는 요청을 먼저 보여준다 (§4 binding rule의 "우선 노출" 요건).
    items.sort(key=lambda item: (item["ai_inferred_count"] == 0, item["submitted_at"]))
    return items

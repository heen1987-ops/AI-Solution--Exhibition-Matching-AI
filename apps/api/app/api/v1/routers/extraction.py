"""AI 추출결과 검수 워크플로 API 라우터. 트랙: BACKEND-EXTRACTION (WAVE 2D).

이 파일은 ``app/api/v1/routers/partner.py``나 ``app/api/v1/api.py``를 직접 수정하지 않고
``build_extraction_router()``만 노출한다 - ``exhibitor_preference.py``/``document.py``와
같은 패턴이다. integrator가 ``app/api/v1/api.py``에서 이 router를 include해야 아래 경로들이
실제로 마운트된다(이 router 자체는 prefix가 없다).

노출 경로 (WAVE2D-CONTRACTS §9, 상대 경로 - 최종 prefix는 integrator 결정):
    GET   /partner/documents/{document_id}/extractions
    PATCH /partner/extractions/{extraction_id}
    POST  /partner/extractions/{extraction_id}/confirm
    POST  /partner/extractions/submit-review
    GET   /admin/ai-review
    POST  /admin/ai-review
    POST  /admin/ai-review/{extraction_id}/approve
    POST  /admin/ai-review/{extraction_id}/reject
    POST  /admin/ai-review/{review_request_id}/request-changes

``{id}`` discriminator에 대한 메모 (WAVE2D-CONTRACTS §9가 열어 둔 두 가지 읽기 중 선택)
------------------------------------------------------------------------------------------
approve/reject는 ``extraction_id``를 쓴다(속성 단위 세분화 승인) - §4의 "AI_INFERRED는 어떤
일괄승인 지름길도 건너뛸 수 없다" 불변식을 문서 단위 승인이 조용히 어길 위험을 원천적으로
없애기 위한 의도적 선택이다. request-changes는 ``review_request_id``를 쓴다(§1의 문서 단위
OPERATOR_REVIEW -> EXHIBITOR_REVIEW 되돌리기이므로 문서/검수요청 단위가 자연스럽다).

인증/인가 (통합 STEP 20)
------------------------
원본에 있던 클라이언트 제어 행위자 헤더 스텁과 사설 ``_require_exhibitor_access`` /
``_require_operator_access`` 복사본은 삭제했다. 행위자는 검증된 principal에서만 파생하고
(``app/core/router_auth.py``), 인가 규칙도 그 공용 어댑터를 쓴다.

``/admin/ai-review*`` 다섯 경로는 여기에 더해
``Depends(require_roles("EVENT_ADMIN", "DATA_REVIEWER"))``를 라우트 dependency로 갖는다.
legacy ``identity.user_role`` 경로에는 MFA 개념이 아예 없으므로, 운영자 승인/반려처럼
게시 여부를 결정하는 행위는 ``app/core/auth.py``의 AAL2 강제를 반드시 함께 통과해야 한다
(PRIVILEGED_ADMIN_ROLES에 두 역할 모두 들어 있어 AAL2가 아니면 403 MFA_REQUIRED).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_roles
from app.core.router_auth import (
    get_actor_user_id,
    get_exhibitor_current_event_id,
    require_exhibitor_access,
    require_operator_access,
)
from app.db.session import get_db
from app.models.document import SourceDocument
from app.models.extraction import (
    ExtractedAttribute,
    SourceEvidence,
)
from app.schemas.extraction import (
    AdminDecisionRequest,
    AdminDecisionResponse,
    AdminRequestChangesRequest,
    AdminRequestChangesResponse,
    AdminReviewClaimRequest,
    AdminReviewClaimResponse,
    AdminReviewQueueItem,
    AdminReviewQueueResponse,
    EvidenceRead,
    ExtractedAttributeRead,
    ExtractionConfirmRequest,
    ExtractionListResponse,
    ExtractionPatchRequest,
    SubmitReviewRejected,
    SubmitReviewRequest,
    SubmitReviewResponse,
)
from app.services.extraction import review as review_service
from app.services.extraction.errors import (
    DocumentNotFoundError,
    ExtractionNotFoundError,
    ExtractionServiceError,
    InvalidTransitionError,
    ReviewRequestNotFoundError,
    SubmitReviewValidationError,
    UnknownOntologyCodeError,
)

router_module_name = __name__

#: ``/admin/ai-review*`` 전용 라우트 의존성 - 모듈 docstring "인증/인가" 참고.
require_ai_review_admin = require_roles("EVENT_ADMIN", "DATA_REVIEWER")


async def _get_document_or_404(db: AsyncSession, document_id: UUID) -> SourceDocument:
    document = await db.get(SourceDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND"})
    return document


def _map_service_error(exc: ExtractionServiceError) -> HTTPException:
    if isinstance(exc, (ExtractionNotFoundError, DocumentNotFoundError, ReviewRequestNotFoundError)):
        return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, InvalidTransitionError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, UnknownOntologyCodeError):
        return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, SubmitReviewValidationError):
        return HTTPException(
            status_code=422,
            detail=SubmitReviewRejected(checks=exc.checks).model_dump(mode="json"),
        )
    return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


async def _to_read_model(db: AsyncSession, row: ExtractedAttribute) -> ExtractedAttributeRead:
    evidence_stmt = select(SourceEvidence).where(SourceEvidence.extraction_id == row.extraction_id)
    evidence_rows = list((await db.execute(evidence_stmt)).scalars().all())
    return ExtractedAttributeRead(
        extraction_id=row.extraction_id,
        document_id=row.document_id,
        ai_run_id=row.ai_run_id,
        entity_type=row.entity_type,  # type: ignore[arg-type]
        entity_reference=row.entity_reference,
        temporary_entity_ref=row.temporary_entity_ref,
        attribute_code=row.attribute_code,
        proposed_value=row.proposed_value,
        normalized_value=row.normalized_value,
        concept_codes=row.concept_codes,
        fact_type=row.fact_type,  # type: ignore[arg-type]
        temporal_validity=row.temporal_validity,  # type: ignore[arg-type]
        confidence=float(row.confidence) if row.confidence is not None else None,
        review_status=row.review_status,  # type: ignore[arg-type]
        visibility=row.visibility,  # type: ignore[arg-type]
        edited_by_exhibitor=row.edited_by_exhibitor,
        evidence=[
            EvidenceRead(
                evidence_id=e.evidence_id,
                document_id=e.document_id,
                segment_ref=e.segment_ref,
                page_number=e.page_number,
                section_title=e.section_title,
                text_start=e.text_start,
                text_end=e.text_end,
                evidence_text=e.evidence_text,
                evidence_hash=e.evidence_hash,
            )
            for e in evidence_rows
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
        reviewed_by_exhibitor_user_id=row.reviewed_by_exhibitor_user_id,
        reviewed_by_exhibitor_at=row.reviewed_by_exhibitor_at,
        reviewed_by_operator_user_id=row.reviewed_by_operator_user_id,
        reviewed_by_operator_at=row.reviewed_by_operator_at,
        rejection_reason=row.rejection_reason,
        superseded_by_extraction_id=row.superseded_by_extraction_id,
    )


def build_extraction_router() -> APIRouter:
    """이 트랙의 엔드포인트를 담은 독립 라우터를 만든다. 마운트는 integrator 책임."""

    router = APIRouter()

    # -----------------------------------------------------------------
    # Exhibitor-facing
    # -----------------------------------------------------------------

    @router.get(
        "/partner/documents/{document_id}/extractions",
        response_model=ExtractionListResponse,
    )
    async def list_extractions(
        document_id: UUID,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> ExtractionListResponse:
        document = await _get_document_or_404(db, document_id)
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=document.exhibitor_id
        )
        stmt = select(ExtractedAttribute).where(ExtractedAttribute.document_id == document_id)
        rows = list((await db.execute(stmt)).scalars().all())
        items = [await _to_read_model(db, row) for row in rows]
        return ExtractionListResponse(document_id=document_id, items=items)

    @router.patch(
        "/partner/extractions/{extraction_id}", response_model=ExtractedAttributeRead
    )
    async def patch_extraction(
        extraction_id: UUID,
        body: ExtractionPatchRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> ExtractedAttributeRead:
        row = await db.get(ExtractedAttribute, extraction_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "EXTRACTION_NOT_FOUND"})
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=row.exhibitor_id
        )
        try:
            updated = await review_service.patch_extraction(
                db,
                extraction_id,
                fields=body.model_dump(exclude_unset=True),
                actor_user_id=actor_user_id,
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return await _to_read_model(db, updated)

    @router.post(
        "/partner/extractions/{extraction_id}/confirm", response_model=ExtractedAttributeRead
    )
    async def confirm_extraction(
        extraction_id: UUID,
        body: ExtractionConfirmRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> ExtractedAttributeRead:
        row = await db.get(ExtractedAttribute, extraction_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "EXTRACTION_NOT_FOUND"})
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=row.exhibitor_id
        )
        try:
            updated = await review_service.confirm_extraction(
                db,
                extraction_id,
                decision=body.decision,
                reason=body.reason,
                actor_user_id=actor_user_id,
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return await _to_read_model(db, updated)

    @router.post(
        "/partner/extractions/submit-review",
        response_model=SubmitReviewResponse,
        responses={422: {"model": SubmitReviewRejected}},
    )
    async def submit_review(
        body: SubmitReviewRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> SubmitReviewResponse:
        document = await _get_document_or_404(db, body.document_id)
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=document.exhibitor_id
        )
        try:
            review_request = await review_service.submit_for_review(
                db,
                document_id=body.document_id,
                tenant_id=document.tenant_id,
                exhibitor_id=document.exhibitor_id,
                actor_user_id=actor_user_id,
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return SubmitReviewResponse(
            review_request_id=review_request.review_request_id,
            document_id=body.document_id,
            status=review_request.status,
            submitted_at=review_request.submitted_at,
        )

    # -----------------------------------------------------------------
    # Operator-facing
    #
    # 다섯 경로 모두 require_ai_review_admin(AAL2/MFA 강제)을 라우트 dependency로
    # 갖고, 그 위에 legacy OPERATOR/ADMIN 역할 확인(require_operator_access)을 그대로
    # 유지한다 - 모듈 docstring "인증/인가" 참고.
    # -----------------------------------------------------------------

    @router.get(
        "/admin/ai-review",
        response_model=AdminReviewQueueResponse,
        dependencies=[Depends(require_ai_review_admin)],
    )
    async def list_admin_review_queue(
        fact_type: str | None = None,
        exhibitor_id: UUID | None = None,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> AdminReviewQueueResponse:
        await require_operator_access(db, actor_user_id=actor_user_id)
        items = await review_service.list_admin_review_queue(
            db, exhibitor_id=exhibitor_id, fact_type=fact_type
        )
        return AdminReviewQueueResponse(items=[AdminReviewQueueItem(**item) for item in items])

    @router.post(
        "/admin/ai-review",
        response_model=AdminReviewClaimResponse,
        dependencies=[Depends(require_ai_review_admin)],
    )
    async def claim_admin_review_queue(
        body: AdminReviewClaimRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> AdminReviewClaimResponse:
        await require_operator_access(db, actor_user_id=actor_user_id)
        try:
            claimed, already_claimed = await review_service.claim_review_requests(
                db, review_request_ids=body.review_request_ids, actor_user_id=actor_user_id
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return AdminReviewClaimResponse(claimed=claimed, already_claimed=already_claimed)

    @router.post(
        "/admin/ai-review/{extraction_id}/approve",
        response_model=AdminDecisionResponse,
        dependencies=[Depends(require_ai_review_admin)],
    )
    async def approve_extraction(
        extraction_id: UUID,
        body: AdminDecisionRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> AdminDecisionResponse:
        await require_operator_access(db, actor_user_id=actor_user_id)
        # MERGE STEP 26: review.py 자신은 app.models.exhibitor를 절대 import하지 않으므로
        # (모듈 docstring의 하드 경계), 승인이 트리거하는 색인 갱신에 필요한 event_id는
        # 그 경계 밖인 여기서 미리 구해 값으로 넘긴다. 대상 행이 없으면 event_id=None을
        # 넘기고, 서비스가 그대로 ExtractionNotFoundError로 처리한다.
        extraction_row = await db.get(ExtractedAttribute, extraction_id)
        event_id = (
            await get_exhibitor_current_event_id(
                db,
                tenant_id=extraction_row.tenant_id,
                exhibitor_id=extraction_row.exhibitor_id,
            )
            if extraction_row is not None
            else None
        )
        try:
            row, published = await review_service.approve_extraction(
                db,
                extraction_id,
                actor_user_id=actor_user_id,
                reason=body.reason,
                event_id=event_id,
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return AdminDecisionResponse(
            extraction_id=row.extraction_id,
            review_status=row.review_status,  # type: ignore[arg-type]
            published_version_id=published.version_id if published else None,
        )

    @router.post(
        "/admin/ai-review/{extraction_id}/reject",
        response_model=AdminDecisionResponse,
        dependencies=[Depends(require_ai_review_admin)],
    )
    async def reject_extraction(
        extraction_id: UUID,
        body: AdminDecisionRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> AdminDecisionResponse:
        await require_operator_access(db, actor_user_id=actor_user_id)
        try:
            row = await review_service.reject_extraction(
                db, extraction_id, actor_user_id=actor_user_id, reason=body.reason
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return AdminDecisionResponse(
            extraction_id=row.extraction_id,
            review_status=row.review_status,  # type: ignore[arg-type]
            published_version_id=None,
        )

    @router.post(
        "/admin/ai-review/{review_request_id}/request-changes",
        response_model=AdminRequestChangesResponse,
        dependencies=[Depends(require_ai_review_admin)],
    )
    async def request_changes(
        review_request_id: UUID,
        body: AdminRequestChangesRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> AdminRequestChangesResponse:
        await require_operator_access(db, actor_user_id=actor_user_id)
        try:
            row = await review_service.request_changes(
                db, review_request_id, actor_user_id=actor_user_id, comment=body.comment
            )
        except ExtractionServiceError as exc:
            raise _map_service_error(exc) from exc
        return AdminRequestChangesResponse(
            review_request_id=row.review_request_id,
            status=row.status,
            operator_comment=row.operator_comment or "",
        )

    return router

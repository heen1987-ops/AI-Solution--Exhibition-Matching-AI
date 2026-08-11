"""업체 공개 거래조건/희망 바이어 요약 API 라우터.

WAVE2C BACKEND-EXHIBITOR-PREFERENCE에서 넘어온 라우터를 통합 저장소 규약에 맞춰
재배선한 것이다. ``app/api/v1/routers/partner.py``가 이미 ``/partner/*`` 프리픽스를
소유하고 있어 이 파일은 그 라우터를 직접 수정하지 않고 독립된
``build_exhibitor_preference_router()``만 노출한다 - 마운트는 integrator 책임이다
(이 파일 자체는 prefix가 없다, partner.py와 동일한 관례).

노출 경로 (integrator가 최종 프리픽스를 결정한다. 아래는 상대 경로):
    GET /exhibitor-preference/{exhibitor_id}                      - 합성 조회 (공개)
    PUT /exhibitor-preference/{exhibitor_id}/availability          - 신규거래/상담가능 선언
    PUT /exhibitor-preference/{exhibitor_id}/cooperation-types     - 협력유형 선호 전체교체

인증/인가 (통합 STEP 20)
------------------------
원본에 있던 클라이언트 제어 행위자 헤더 스텁(``get_actor_user_id``)과 사설
``_require_exhibitor_access`` 복사본은 삭제했다. 두 쓰기 엔드포인트는 공용 어댑터
``app/core/router_auth.py``의 검증된 principal 파생 행위자와 인가 규칙만 쓴다.

GET은 의도적으로 행위자를 요구하지 않는 공개 경로다 - 통합 STEP 16(c)에서
``services/exhibitor_preference/service.py``가 ``Exhibitor.master_approval_status ==
'APPROVED'``와 선언 자체의 ``approval_status``를 모두 검사하도록 바뀌었기 때문에,
미승인 업체의 선언은 이 경로로 절대 새어 나가지 않는다.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router_auth import get_actor_user_id, require_exhibitor_access
from app.db.session import get_db
from app.models.exhibitor import Exhibitor
from app.schemas.exhibitor_preference import (
    ExhibitorCooperationTypeListResponse,
    ExhibitorCooperationTypeRead,
    ExhibitorCooperationTypeReplaceRequest,
    ExhibitorPreferenceRead,
    ExhibitorTradeAvailabilityRead,
    ExhibitorTradeAvailabilityUpdate,
    TaxonomyRef,
)
from app.services.exhibitor_preference import (
    get_exhibitor_preference_view,
    replace_cooperation_types,
    upsert_trade_availability,
)


async def _get_exhibitor_or_404(db: AsyncSession, exhibitor_id: UUID) -> Exhibitor:
    exhibitor = await db.get(Exhibitor, exhibitor_id)
    if exhibitor is None or exhibitor.deleted_at is not None:
        raise HTTPException(status_code=404, detail="EXHIBITOR_NOT_FOUND")
    return exhibitor


def build_exhibitor_preference_router() -> APIRouter:
    """이 트랙의 엔드포인트를 담은 독립 라우터를 만든다. 마운트는 integrator 책임."""

    router = APIRouter()

    @router.get(
        "/exhibitor-preference/{exhibitor_id}", response_model=ExhibitorPreferenceRead
    )
    async def read_exhibitor_preference(
        exhibitor_id: UUID, db: AsyncSession = Depends(get_db)
    ) -> ExhibitorPreferenceRead:
        await _get_exhibitor_or_404(db, exhibitor_id)
        return await get_exhibitor_preference_view(db, exhibitor_id)

    @router.put(
        "/exhibitor-preference/{exhibitor_id}/availability",
        response_model=ExhibitorTradeAvailabilityRead,
    )
    async def update_trade_availability(
        exhibitor_id: UUID,
        body: ExhibitorTradeAvailabilityUpdate,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> ExhibitorTradeAvailabilityRead:
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id
        )
        await _get_exhibitor_or_404(db, exhibitor_id)
        row = await upsert_trade_availability(
            db,
            exhibitor_id,
            new_trade_available=body.new_trade_available,
            meeting_available=body.meeting_available,
        )
        return ExhibitorTradeAvailabilityRead(
            exhibitor_id=row.exhibitor_id,
            new_trade_available=row.new_trade_available,  # type: ignore[arg-type]
            meeting_available=row.meeting_available,  # type: ignore[arg-type]
            approval_status=row.approval_status,  # type: ignore[arg-type]
        )

    @router.put(
        "/exhibitor-preference/{exhibitor_id}/cooperation-types",
        response_model=ExhibitorCooperationTypeListResponse,
    )
    async def update_cooperation_types(
        exhibitor_id: UUID,
        body: ExhibitorCooperationTypeReplaceRequest,
        actor_user_id: UUID = Depends(get_actor_user_id),
        db: AsyncSession = Depends(get_db),
    ) -> ExhibitorCooperationTypeListResponse:
        await require_exhibitor_access(
            db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id
        )
        await _get_exhibitor_or_404(db, exhibitor_id)
        try:
            rows = await replace_cooperation_types(
                db, exhibitor_id, body.cooperation_types
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"INVALID_COOPERATION_TYPE:{exc}"
            ) from exc
        return ExhibitorCooperationTypeListResponse(
            exhibitor_id=exhibitor_id,
            items=[
                ExhibitorCooperationTypeRead(
                    exhibitor_cooperation_type_id=row.exhibitor_cooperation_type_id,
                    cooperation_type=TaxonomyRef(
                        taxonomy_version_id=row.taxonomy_version_id,
                        concept_id=row.concept_id,
                    ),
                    active=row.active,
                )
                for row in rows
            ],
        )

    return router

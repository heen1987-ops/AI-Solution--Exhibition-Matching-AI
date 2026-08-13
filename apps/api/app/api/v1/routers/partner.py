"""참가업체 파트너 포털 API 라우터.

경로 근거
---------
docs/08-exhibitor-product-profile-model.md 28절이 이 파일의 1차 근거다. 그 문서 27절 끝의
안내("인터페이스 명세의 라우트 규칙과 경로 표기가 다를 수 있음 - 구현 시 인터페이스 명세를
우선한다")에 따라, docs/frontend-backend-ai-interface-spec.md와 경로가 충돌하면 인터페이스
명세를 우선해야 하지만, 인터페이스 명세 15절은 이 작업이 다루는 프로파일/제품/거래조건/희망
바이어 엔드포인트를 별도로 정의하지 않는다(그 절은 대시보드·상담·부스상태만 다룬다). 따라서
아래 다섯 경로는 08 문서 28.1~28.6절 표기를 그대로 따른다:

    GET   /exhibitors/{exhibitor_id}/profile
    PATCH /partner/exhibitors/{exhibitor_id}/profile
    POST  /partner/products
    PUT   /partner/products/{product_id}/trade-conditions
    PUT   /partner/exhibitors/{exhibitor_id}/buyer-preferences
    POST  /partner/exhibitors/{exhibitor_id}/submit

이 router는 자체 prefix가 없다 - app/api/v1/api.py(공용 aggregator, 이 작업 범위 밖)가 추가
prefix 없이 include해야 위 경로가 최종적으로 `<API_V1_PREFIX>/...`가 된다. 28.7절(운영자 승인,
POST /api/v1/admin/exhibitors/{exhibitor_id}/approve)은 이번 작업 지시가 명시한 범위
("업체 프로파일 조회/수정, 제품 등록, 거래조건 등록, 희망 바이어 등록, 검수 제출")에 들어있지
않아 이 파일에 포함하지 않는다 - 운영자(admin) 라우터 담당 에이전트의 몫이다.

인증 경계
---------
보호 경로는 검증된 서버 세션 또는 서비스 JWT에서 파생된 principal만 사용한다. 호출자가
보내는 사용자 식별 헤더는 권한 판단에 사용하지 않으며, 업체 범위는 principal의 tenant/event와
DB 소속 관계를 함께 확인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router_auth import get_actor_user_id, require_exhibitor_access
from app.db.session import get_db
from app.models.exhibitor import (
    EventProduct,
    Exhibitor,
    ExhibitorBusinessType,
    ExhibitorBuyerPreference,
    ExhibitorParticipation,
    ExhibitorProfile,
    ExhibitorStaff,
    Product,
    ProductProfile,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.ontology_refs import concept as ontology_concept
from app.schemas.partner import (
    BuyerPreferenceItem,
    BuyerPreferenceListResponse,
    BuyerPreferenceRead,
    BuyerPreferenceReplaceRequest,
    ExhibitorProfileRead,
    ExhibitorProfileUpdate,
    ExhibitorSupplyProfileRead,
    ProductCreateRequest,
    ProductRead,
    ProductSupplyProfileRead,
    SubmitResponse,
    TaxonomyRef,
    TradeConditionRead,
    TradeConditionUpsert,
)

router = APIRouter()


# 행위자 식별/인가는 공용 어댑터(app/core/router_auth.py)가 정본이다. 아래 두 이름은
# 기존 참조(및 테스트의 dependency_overrides)를 깨지 않기 위한 동일 객체 별칭이다.
_require_exhibitor_access = require_exhibitor_access


async def _get_exhibitor_or_404(db: AsyncSession, exhibitor_id: UUID) -> Exhibitor:
    exhibitor = await db.get(Exhibitor, exhibitor_id)
    if exhibitor is None or exhibitor.deleted_at is not None:
        raise HTTPException(status_code=404, detail="EXHIBITOR_NOT_FOUND")
    return exhibitor


def _business_types_to_refs(rows: list[ExhibitorBusinessType]) -> list[TaxonomyRef]:
    return [
        TaxonomyRef(taxonomy_version_id=r.taxonomy_version_id, concept_id=r.concept_id)
        for r in rows
    ]


async def _resolve_concept_code(db: AsyncSession, concept_id: UUID) -> str | None:
    """ontology.concept.concept_code를 조회한다 (db-erd 11절 정본 코드값).

    exhibition.product_profile.category_code는 "표시용 코드 캐시"(exhibitor.py 모듈
    docstring)이므로 concept_id의 UUID 자체가 아니라 실제 사람이 읽는 코드
    (예: "ALCOHOL.DISTILLED")를 담아야 한다.
    """

    stmt = select(ontology_concept.c.concept_code).where(
        ontology_concept.c.concept_id == concept_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 28.1 - 업체 프로파일 조회 (공개, 08 2.3절 PUBLIC 등급만 반환)
# ---------------------------------------------------------------------------


@router.get("/exhibitors/{exhibitor_id}/profile", response_model=ExhibitorProfileRead)
async def get_exhibitor_profile(
    exhibitor_id: UUID, db: AsyncSession = Depends(get_db)
) -> ExhibitorProfileRead:
    exhibitor = await _get_exhibitor_or_404(db, exhibitor_id)

    business_types_stmt = select(ExhibitorBusinessType).where(
        ExhibitorBusinessType.exhibitor_id == exhibitor_id
    )
    business_types = list((await db.execute(business_types_stmt)).scalars().all())

    profile_stmt = select(ExhibitorProfile).where(
        ExhibitorProfile.exhibitor_id == exhibitor_id
    )
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()

    region = None
    if exhibitor.region_concept_id is not None:
        region = TaxonomyRef(
            taxonomy_version_id=exhibitor.region_taxonomy_version_id,
            concept_id=exhibitor.region_concept_id,
        )

    return ExhibitorProfileRead(
        exhibitor_id=exhibitor.exhibitor_id,
        company_name=exhibitor.company_name,
        company_summary=exhibitor.company_summary,
        website_url=exhibitor.website_url,
        region=region,
        business_types=_business_types_to_refs(business_types),
        master_approval_status=exhibitor.master_approval_status,
        data_completeness_percent=float(exhibitor.data_completeness_percent),
        current_profile_version=exhibitor.current_profile_version,
        supply_profile=(
            ExhibitorSupplyProfileRead.model_validate(profile) if profile else None
        ),
    )


# ---------------------------------------------------------------------------
# 28.2 - 업체 프로파일 수정
# ---------------------------------------------------------------------------


@router.patch("/partner/exhibitors/{exhibitor_id}/profile", response_model=ExhibitorProfileRead)
async def update_exhibitor_profile(
    exhibitor_id: UUID,
    body: ExhibitorProfileUpdate,
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> ExhibitorProfileRead:
    await _require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    exhibitor = await _get_exhibitor_or_404(db, exhibitor_id)

    if body.company_summary is not None:
        exhibitor.company_summary = body.company_summary
    if body.website_url is not None:
        exhibitor.website_url = body.website_url
    if body.region is not None:
        exhibitor.region_taxonomy_version_id = body.region.taxonomy_version_id
        exhibitor.region_concept_id = body.region.concept_id

    if body.business_types is not None:
        await db.execute(
            delete(ExhibitorBusinessType).where(
                ExhibitorBusinessType.exhibitor_id == exhibitor_id
            )
        )
        for ref in body.business_types:
            db.add(
                ExhibitorBusinessType(
                    exhibitor_id=exhibitor_id,
                    taxonomy_version_id=ref.taxonomy_version_id,
                    concept_id=ref.concept_id,
                )
            )

    profile_stmt = select(ExhibitorProfile).where(
        ExhibitorProfile.exhibitor_id == exhibitor_id
    )
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()
    if profile is None:
        profile = ExhibitorProfile(exhibitor_id=exhibitor_id)
        db.add(profile)

    if body.capability_json is not None:
        profile.capability_json = body.capability_json
    if body.business_types is not None:
        profile.business_type = [str(ref.concept_id) for ref in body.business_types]
    # 08 31.1절 "업체·운영자 충돌" 원칙: 업체가 승인된 프로파일을 고치면 재검수가 필요하므로
    # 승인상태를 되돌린다. REJECTED에서 고친 경우도 다시 DRAFT로 돌려 재작성 흐름을 보장한다.
    if profile.approval_status in ("SUBMITTED", "APPROVED", "REJECTED"):
        profile.approval_status = "DRAFT"

    exhibitor.current_profile_version += 1
    profile.current_version = exhibitor.current_profile_version

    await db.commit()
    return await get_exhibitor_profile(exhibitor_id, db)


# ---------------------------------------------------------------------------
# 28.3 - 제품 등록
# ---------------------------------------------------------------------------


@router.post("/partner/products", response_model=ProductRead, status_code=201)
async def create_product(
    body: ProductCreateRequest,
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> ProductRead:
    await _require_exhibitor_access(
        db, actor_user_id=actor_user_id, exhibitor_id=body.exhibitor_id
    )
    exhibitor = await _get_exhibitor_or_404(db, body.exhibitor_id)

    product = Product(
        exhibitor_id=body.exhibitor_id,
        product_name=body.product_name,
        product_summary=body.product_summary,
        alcohol_percentage=body.alcohol_percentage,
        production_method=body.production_method,
        main_ingredients_json={"items": body.main_ingredients} if body.main_ingredients else None,
    )
    if body.category is not None:
        product.category_taxonomy_version_id = body.category.taxonomy_version_id
        product.category_concept_id = body.category.concept_id
    db.add(product)
    await db.flush()

    category_code = (
        await _resolve_concept_code(db, body.category.concept_id) if body.category else None
    )
    profile = ProductProfile(
        product_id=product.product_id,
        category_code=category_code,
        taste_json=body.taste or None,
        aroma_json=body.aroma or None,
        usage_json=body.usage or None,
        feature_json=body.features or None,
    )
    db.add(profile)

    if body.event_id is not None:
        participation_stmt = select(ExhibitorParticipation).where(
            ExhibitorParticipation.tenant_id == exhibitor.tenant_id,
            ExhibitorParticipation.event_id == body.event_id,
            ExhibitorParticipation.exhibitor_id == body.exhibitor_id,
        )
        participation = (await db.execute(participation_stmt)).scalar_one_or_none()
        if participation is None:
            raise HTTPException(status_code=422, detail="NO_PARTICIPATION_FOR_EVENT")
        db.add(
            EventProduct(
                tenant_id=participation.tenant_id,
                event_id=body.event_id,
                participation_id=participation.participation_id,
                product_id=product.product_id,
            )
        )

    await db.commit()

    return ProductRead(
        product_id=product.product_id,
        exhibitor_id=product.exhibitor_id,
        product_name=product.product_name,
        product_summary=product.product_summary,
        category=body.category,
        alcohol_percentage=(
            float(product.alcohol_percentage) if product.alcohol_percentage is not None else None
        ),
        master_approval_status=product.master_approval_status,
        supply_profile=ProductSupplyProfileRead.model_validate(profile),
    )


# ---------------------------------------------------------------------------
# 28.4 - 거래조건 등록
# ---------------------------------------------------------------------------


@router.put(
    "/partner/products/{product_id}/trade-conditions", response_model=TradeConditionRead
)
async def upsert_trade_conditions(
    product_id: UUID,
    body: TradeConditionUpsert,
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> TradeConditionRead:
    product = await db.get(Product, product_id)
    if product is None or product.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    await _require_exhibitor_access(
        db, actor_user_id=actor_user_id, exhibitor_id=product.exhibitor_id
    )
    exhibitor = await _get_exhibitor_or_404(db, product.exhibitor_id)

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.tenant_id == exhibitor.tenant_id,
        ExhibitorParticipation.event_id == body.event_id,
        ExhibitorParticipation.exhibitor_id == product.exhibitor_id,
    )
    participation = (await db.execute(participation_stmt)).scalar_one_or_none()
    if participation is None:
        raise HTTPException(status_code=422, detail="NO_PARTICIPATION_FOR_EVENT")

    event_product_stmt = select(EventProduct).where(
        EventProduct.event_id == body.event_id, EventProduct.product_id == product_id
    )
    event_product = (await db.execute(event_product_stmt)).scalar_one_or_none()
    if event_product is None:
        event_product = EventProduct(
            tenant_id=participation.tenant_id,
            event_id=body.event_id,
            participation_id=participation.participation_id,
            product_id=product_id,
        )
        db.add(event_product)
        await db.flush()

    trade_condition_stmt = select(TradeCondition).where(
        TradeCondition.event_product_id == event_product.event_product_id
    )
    trade_condition = (await db.execute(trade_condition_stmt)).scalar_one_or_none()
    if trade_condition is None:
        trade_condition = TradeCondition(
            participation_id=participation.participation_id,
            event_product_id=event_product.event_product_id,
        )
        db.add(trade_condition)

    trade_condition.min_order_quantity = body.min_order_quantity
    trade_condition.max_order_quantity = body.max_order_quantity
    trade_condition.monthly_capacity = body.monthly_capacity
    trade_condition.wholesale_price_min_amount = body.wholesale_price_min_amount
    trade_condition.wholesale_price_max_amount = body.wholesale_price_max_amount
    trade_condition.currency = body.currency
    trade_condition.oem_status = body.oem_status
    trade_condition.private_label_status = body.private_label_status
    trade_condition.export_status = body.export_status
    trade_condition.exclusive_distribution_considered = body.exclusive_distribution_considered
    trade_condition.lead_time_days = body.lead_time_days
    trade_condition.valid_from = body.valid_from
    trade_condition.valid_until = body.valid_until
    # 08 31.1절 원칙과 동일하게, 조건을 고치면 재검수가 필요하므로 승인상태를 되돌린다.
    if trade_condition.approval_status in ("APPROVED", "REJECTED"):
        trade_condition.approval_status = "DRAFT"

    await db.flush()

    await db.execute(
        delete(TradeConditionTerm).where(
            TradeConditionTerm.trade_condition_id == trade_condition.trade_condition_id
        )
    )
    term_groups = (
        ("REGION", body.supply_regions),
        ("CHANNEL", body.channels),
        ("COUNTRY", body.countries),
    )
    for term_type, refs in term_groups:
        for ref in refs:
            db.add(
                TradeConditionTerm(
                    trade_condition_id=trade_condition.trade_condition_id,
                    term_type=term_type,
                    taxonomy_version_id=ref.taxonomy_version_id,
                    concept_id=ref.concept_id,
                )
            )

    await db.commit()

    return TradeConditionRead(
        trade_condition_id=trade_condition.trade_condition_id,
        product_id=product_id,
        event_id=body.event_id,
        min_order_quantity=trade_condition.min_order_quantity,
        max_order_quantity=trade_condition.max_order_quantity,
        monthly_capacity=trade_condition.monthly_capacity,
        wholesale_price_min_amount=trade_condition.wholesale_price_min_amount,
        wholesale_price_max_amount=trade_condition.wholesale_price_max_amount,
        currency=trade_condition.currency,
        oem_status=trade_condition.oem_status,  # type: ignore[arg-type]
        private_label_status=trade_condition.private_label_status,  # type: ignore[arg-type]
        export_status=trade_condition.export_status,  # type: ignore[arg-type]
        exclusive_distribution_considered=trade_condition.exclusive_distribution_considered,
        lead_time_days=trade_condition.lead_time_days,
        valid_from=trade_condition.valid_from,
        valid_until=trade_condition.valid_until,
        supply_regions=body.supply_regions,
        channels=body.channels,
        countries=body.countries,
        approval_status=trade_condition.approval_status,
    )


# ---------------------------------------------------------------------------
# 28.5 - 희망 바이어 등록
# ---------------------------------------------------------------------------


def _pick_taxonomy_version(item: BuyerPreferenceItem) -> UUID:
    versions = {
        ref.taxonomy_version_id
        for ref in (item.buyer_type, item.channel, item.region)
        if ref is not None
    }
    if len(versions) != 1:
        raise HTTPException(
            status_code=400,
            detail="BUYER_PREFERENCE_TAXONOMY_VERSION_MISMATCH",
        )
    return versions.pop()


@router.put(
    "/partner/exhibitors/{exhibitor_id}/buyer-preferences",
    response_model=BuyerPreferenceListResponse,
)
async def replace_buyer_preferences(
    exhibitor_id: UUID,
    body: BuyerPreferenceReplaceRequest,
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> BuyerPreferenceListResponse:
    await _require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    await _get_exhibitor_or_404(db, exhibitor_id)

    await db.execute(
        delete(ExhibitorBuyerPreference).where(
            ExhibitorBuyerPreference.exhibitor_id == exhibitor_id
        )
    )

    created: list[ExhibitorBuyerPreference] = []
    for item in body.preferences:
        if item.buyer_type is None and item.channel is None and item.region is None:
            raise HTTPException(status_code=400, detail="BUYER_PREFERENCE_EMPTY_DIMENSION")
        taxonomy_version_id = _pick_taxonomy_version(item)
        row = ExhibitorBuyerPreference(
            exhibitor_id=exhibitor_id,
            taxonomy_version_id=taxonomy_version_id,
            buyer_type_concept_id=item.buyer_type.concept_id if item.buyer_type else None,
            channel_concept_id=item.channel.concept_id if item.channel else None,
            region_concept_id=item.region.concept_id if item.region else None,
            volume_min=item.volume_min,
            volume_max=item.volume_max,
            preference_level=item.preference_level,
        )
        db.add(row)
        created.append(row)

    await db.commit()

    return BuyerPreferenceListResponse(
        exhibitor_id=exhibitor_id,
        items=[
            BuyerPreferenceRead(
                exhibitor_buyer_preference_id=row.exhibitor_buyer_preference_id,
                buyer_type=(
                    TaxonomyRef(
                        taxonomy_version_id=row.taxonomy_version_id,
                        concept_id=row.buyer_type_concept_id,
                    )
                    if row.buyer_type_concept_id
                    else None
                ),
                channel=(
                    TaxonomyRef(
                        taxonomy_version_id=row.taxonomy_version_id,
                        concept_id=row.channel_concept_id,
                    )
                    if row.channel_concept_id
                    else None
                ),
                region=(
                    TaxonomyRef(
                        taxonomy_version_id=row.taxonomy_version_id,
                        concept_id=row.region_concept_id,
                    )
                    if row.region_concept_id
                    else None
                ),
                volume_min=row.volume_min,
                volume_max=row.volume_max,
                preference_level=row.preference_level,  # type: ignore[arg-type]
                active=row.active,
            )
            for row in created
        ],
    )


# ---------------------------------------------------------------------------
# 28.6 - 검수 제출
# ---------------------------------------------------------------------------


async def _compute_completeness(db: AsyncSession, exhibitor: Exhibitor) -> tuple[float, float, int]:
    """08 17.1절 가중치의 근사 구현.

    TODO(6단계 온톨로지·상세 가중치 확정 후 재검토): 08 17.1/17.2절은 "기본정보 15%,
    제품정보 20%, 거래조건 25%, 공급역량 15%, 희망 바이어 10%, 상담정보 10%, 검증정보 5%"를
    업체 완성도로 제시하지만, 각 항목을 "충족/미충족"으로 판정하는 세부 기준(예: 제품정보
    몇 건부터 만점인지)은 문서에 없다. 여기서는 합리적인 근사만 두고, 실제 서비스 투입 전
    운영·매칭 담당 에이전트가 재조정해야 한다. consumer/buyer 분리는 27.1절 컬럼 두 개
    (consumer_completeness/buyer_completeness)가 요구하는 최소한의 구분만 반영한다.
    """

    product_count = (
        await db.execute(
            select(func.count(Product.product_id)).where(
                Product.exhibitor_id == exhibitor.exhibitor_id, Product.deleted_at.is_(None)
            )
        )
    ).scalar_one()

    trade_condition_count = (
        await db.execute(
            select(func.count(TradeCondition.trade_condition_id))
            .join(
                ExhibitorParticipation,
                ExhibitorParticipation.participation_id == TradeCondition.participation_id,
            )
            .where(ExhibitorParticipation.exhibitor_id == exhibitor.exhibitor_id)
        )
    ).scalar_one()

    buyer_preference_count = (
        await db.execute(
            select(func.count(ExhibitorBuyerPreference.exhibitor_buyer_preference_id)).where(
                ExhibitorBuyerPreference.exhibitor_id == exhibitor.exhibitor_id,
                ExhibitorBuyerPreference.active.is_(True),
            )
        )
    ).scalar_one()

    staff_count = (
        await db.execute(
            select(func.count(ExhibitorStaff.staff_id))
            .join(
                ExhibitorParticipation,
                ExhibitorParticipation.participation_id == ExhibitorStaff.participation_id,
            )
            .where(ExhibitorParticipation.exhibitor_id == exhibitor.exhibitor_id)
        )
    ).scalar_one()

    profile_stmt = select(ExhibitorProfile).where(
        ExhibitorProfile.exhibitor_id == exhibitor.exhibitor_id
    )
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()

    basic_info_score = 1.0 if (exhibitor.company_summary and exhibitor.website_url) else (
        0.5 if (exhibitor.company_summary or exhibitor.website_url) else 0.0
    )
    product_score = min(product_count, 3) / 3
    capability_score = 1.0 if (profile and profile.capability_json) else 0.0
    trade_condition_score = 1.0 if trade_condition_count > 0 else 0.0
    buyer_pref_score = 1.0 if buyer_preference_count > 0 else 0.0
    consultation_score = 1.0 if staff_count > 0 else 0.0

    consumer_completeness = round(
        (basic_info_score * 0.4 + product_score * 0.4 + capability_score * 0.2) * 100, 2
    )
    buyer_completeness = round(
        (trade_condition_score * 0.4 + buyer_pref_score * 0.3 + consultation_score * 0.3) * 100,
        2,
    )

    return consumer_completeness, buyer_completeness, product_count


@router.post("/partner/exhibitors/{exhibitor_id}/submit", response_model=SubmitResponse)
async def submit_exhibitor_profile(
    exhibitor_id: UUID,
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> SubmitResponse:
    await _require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    exhibitor = await _get_exhibitor_or_404(db, exhibitor_id)

    consumer_completeness, buyer_completeness, product_count = await _compute_completeness(
        db, exhibitor
    )

    blocking_issues: list[str] = []
    if product_count == 0:
        blocking_issues.append("NO_PRODUCT_REGISTERED")

    if blocking_issues:
        raise HTTPException(
            status_code=422,
            detail={"code": "PROFILE_INCOMPLETE", "blocking_issues": blocking_issues},
        )

    profile_stmt = select(ExhibitorProfile).where(
        ExhibitorProfile.exhibitor_id == exhibitor_id
    )
    profile = (await db.execute(profile_stmt)).scalar_one_or_none()
    if profile is None:
        profile = ExhibitorProfile(exhibitor_id=exhibitor_id)
        db.add(profile)

    profile.consumer_completeness = consumer_completeness
    profile.buyer_completeness = buyer_completeness
    profile.approval_status = "SUBMITTED"

    await db.commit()

    return SubmitResponse(
        exhibitor_id=exhibitor_id,
        approval_status=profile.approval_status,
        consumer_completeness=consumer_completeness,
        buyer_completeness=buyer_completeness,
        submitted_at=datetime.now(UTC),
        blocking_issues=blocking_issues,
    )

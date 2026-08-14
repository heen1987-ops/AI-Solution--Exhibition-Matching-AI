"""④ Candidate Generator - docs/05-ai-matching-engine-architecture.md 5.4절.

추천 가능한 전체 참가업체·제품·부스·프로그램 중 상위 후보군을 빠르게 검색한다. 05번 문서
5.4절이 나열한 6개 채널 중 이번 구현에서 실동작으로 채우는 것:

    1. 구조화 속성 검색   - SQL로 승인·활성 상태 후보를 넓게 가져온 뒤, 프로파일의 taxonomy
                            코드(categories/channels/regions/taste/aroma)와
                            ``Catalog.match_strength``로 관련도를 매겨 상위 N개를 뽑는다.
    2. 벡터 의미 검색     - 식별정보·자유문을 제외한 프로파일 온톨로지 신호로 배포된 SUMMARY
                            임베딩을 조회한다. 공급자/pgvector 장애 시 구조화 검색만 유지한다.
    3. 인기·품질 기반 후보 - exhibitor_profile.trade_readiness_score, product_profile의
                            consumer_score/buyer_score로 정렬한 상위 N개.
    4. 운영자 지정 후보   - 지정 후보를 담을 테이블이 db-erd/07/08 어디에도 아직 없어
                            no-op으로 둔다. TODO(운영자 큐레이션 테이블 설계 후 구현).
    5. 관심목록 연관 후보  - interaction.interaction_event의 FAVORITE_ADD류 이벤트로 사용자가
                            저장한 대상과 같은 업체/카테고리의 다른 후보를 채널로 추가한다.
    6. 탐색·신규성 후보   - 최근 승인된 참가업체·제품을 최신순으로 추가한다.

이 단계는 최종순위를 결정하지 않는다(문서 5.4절 "충분한 재현율을 확보하는 것이 목적이다").
승인·운영종료 등 자격 판단은 5 Hard Filter Engine이 한다 - 그래서 여기서는 굳이
``master_approval_status == 'APPROVED'``로 좁히지 않고, 표시용 pool 전체를 가져와 다음
단계가 사유와 함께 배제할 수 있게 한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    ExhibitorProfile,
    Product,
    ProductProfile,
    Program,
    SupplyCapability,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.matching import InteractionEvent, Recommendable
from app.services.matching.ontology_support import (
    get_catalog,
    max_match_strength,
    resolve_concept_codes,
)
from app.services.matching.profile_semantic_recall import (
    ProfileSemanticRecall,
    recall_profile_participations,
)
from app.services.matching.semantic_search import NullSemanticScorer, SemanticScorer
from app.services.matching.types import (
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    ValidatedRequest,
)

# 05번 문서 5.4절 "후보군 병합 예시"의 채널별 상한을 그대로 기본값으로 쓴다.
# TODO(운영 데이터/부하 테스트 확정 후 교체): 정확한 값은 11/12단계 정책에서 확정한다.
STRUCTURED_LIMIT = 100
VECTOR_LIMIT = 80
POPULARITY_LIMIT = 20
EXPLORATION_LIMIT = 10
INTEREST_LIMIT = 20
TOTAL_POOL_CAP = 150
RAW_FETCH_CAP = 400  # 구조화 관련도 정렬 전에 SQL에서 가져오는 원시 행 상한.
VECTOR_OBJECTS_PER_PARTICIPATION = 3

_INTEREST_EVENT_TYPES = ("RECOMMENDATION_SAVED", "FAVORITE_ADD")


def _target_object_types(recommendation_type: str) -> tuple[str, ...]:
    if recommendation_type == "MIXED":
        return ("BOOTH", "PRODUCT", "EXHIBITOR", "PROGRAM")
    return (recommendation_type,)


async def _load_supply_profiles(
    db: AsyncSession, exhibitor_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """08번 문서 29절 "매칭엔진 입력용 공급 프로파일" 형태로 업체별 매칭 입력을 조립한다.

    Feature Builder/Hard Filter가 재조회 없이 쓸 수 있도록 candidate.payload["supply_profile"]에
    그대로 캐시한다.
    """

    ids = list({eid for eid in exhibitor_ids if eid is not None})
    if not ids:
        return {}

    profiles: dict[uuid.UUID, dict[str, Any]] = {}
    profile_rows = (
        await db.execute(
            select(ExhibitorProfile).where(ExhibitorProfile.exhibitor_id.in_(ids))
        )
    ).scalars()
    for row in profile_rows:
        completeness_values = [
            v
            for v in (row.consumer_completeness, row.buyer_completeness)
            if v is not None
        ]
        profiles[row.exhibitor_id] = {
            "profile_version": row.current_version,
            "approval_status": row.approval_status,
            "business_types": list(row.business_type or []),
            "trade_profile": {
                "channels": [],
                "regions": [],
                "min_order_quantity": None,
                "monthly_available_capacity": None,
                "oem_status": "UNKNOWN",
                "private_label_status": "UNKNOWN",
                "export_status": "UNKNOWN",
            },
            "preferred_buyers": list(row.preferred_buyer_json or []),
            "trade_readiness_score": float(row.trade_readiness_score)
            if row.trade_readiness_score is not None
            else None,
            "consumer_completeness": float(row.consumer_completeness),
            "buyer_completeness": float(row.buyer_completeness),
            "data_trust_score": (
                sum(float(v) for v in completeness_values)
                / len(completeness_values)
                / 100.0
                if completeness_values
                else 0.5
            ),
        }

    # 참가(participation) 단위 거래조건 -> 채널/지역 코드, MOQ, OEM/PB/수출 상태.
    participation_rows = (
        await db.execute(
            select(
                ExhibitorParticipation.participation_id,
                ExhibitorParticipation.exhibitor_id,
            ).where(ExhibitorParticipation.exhibitor_id.in_(ids))
        )
    ).all()
    participation_to_exhibitor = {
        row.participation_id: row.exhibitor_id for row in participation_rows
    }
    participation_ids = list(participation_to_exhibitor)

    if participation_ids:
        trade_rows = (
            (
                await db.execute(
                    select(TradeCondition).where(
                        TradeCondition.participation_id.in_(participation_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        trade_condition_ids = [tc.trade_condition_id for tc in trade_rows]
        term_rows = (
            (
                await db.execute(
                    select(TradeConditionTerm).where(
                        TradeConditionTerm.trade_condition_id.in_(trade_condition_ids)
                    )
                )
            )
            .scalars()
            .all()
            if trade_condition_ids
            else []
        )
        concept_codes = await resolve_concept_codes(
            db, [t.concept_id for t in term_rows]
        )
        terms_by_condition: dict[uuid.UUID, list[TradeConditionTerm]] = {}
        for term in term_rows:
            terms_by_condition.setdefault(term.trade_condition_id, []).append(term)

        for tc in trade_rows:
            exhibitor_id = participation_to_exhibitor.get(tc.participation_id)
            profile = profiles.get(exhibitor_id)
            if profile is None:
                continue
            trade_profile = profile["trade_profile"]
            for term in terms_by_condition.get(tc.trade_condition_id, []):
                code = concept_codes.get(term.concept_id)
                if not code:
                    continue
                if (
                    term.term_type == "CHANNEL"
                    and code not in trade_profile["channels"]
                ):
                    trade_profile["channels"].append(code)
                elif (
                    term.term_type == "REGION" and code not in trade_profile["regions"]
                ):
                    trade_profile["regions"].append(code)
            if tc.min_order_quantity is not None:
                current = trade_profile["min_order_quantity"]
                trade_profile["min_order_quantity"] = (
                    tc.min_order_quantity
                    if current is None
                    else min(current, tc.min_order_quantity)
                )
            # 업체 공통조건(event_product_id IS NULL)을 대표값으로 우선 채택한다.
            if tc.event_product_id is None or trade_profile["oem_status"] == "UNKNOWN":
                trade_profile["oem_status"] = tc.oem_status
                trade_profile["private_label_status"] = tc.private_label_status
                trade_profile["export_status"] = tc.export_status

    # 공급역량 -> 신규공급 가능량, 지역 코드 보강.
    capability_rows = (
        (
            await db.execute(
                select(SupplyCapability).where(SupplyCapability.exhibitor_id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    for cap in capability_rows:
        profile = profiles.get(cap.exhibitor_id)
        if profile is None:
            continue
        trade_profile = profile["trade_profile"]
        if cap.available_capacity is not None:
            current = trade_profile["monthly_available_capacity"]
            trade_profile["monthly_available_capacity"] = (
                cap.available_capacity
                if current is None
                else max(current, cap.available_capacity)
            )
        for code in cap.supply_regions or []:
            if code not in trade_profile["regions"]:
                trade_profile["regions"].append(code)

    return profiles


async def _fetch_booth_candidates(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID
) -> list[MatchCandidate]:
    stmt = (
        select(
            Recommendable.recommendable_id,
            Booth.booth_id,
            Booth.participation_id,
            Booth.operating_status,
            Booth.congestion_level,
            Booth.estimated_wait_minutes,
            Booth.zone_id,
            Booth.map_x,
            Booth.map_y,
            Booth.status_observed_at,
            ExhibitorParticipation.exhibitor_id,
            ExhibitorParticipation.participation_status,
            ExhibitorParticipation.consultation_enabled,
            Exhibitor.company_name,
            Exhibitor.master_approval_status,
            Booth.created_at,
        )
        .join(Recommendable, Recommendable.booth_id == Booth.booth_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Booth.participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
            Recommendable.active.is_(True),
        )
        .limit(RAW_FETCH_CAP)
    )
    rows = await db.execute(stmt)
    candidates: list[MatchCandidate] = []
    for row in rows:
        candidates.append(
            MatchCandidate(
                object_type="BOOTH",
                object_id=row.booth_id,
                recommendable_id=row.recommendable_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                public_object_id=str(row.booth_id),
                payload={
                    "participation_status": row.participation_status,
                    "operating_status": row.operating_status,
                    "congestion_level": row.congestion_level,
                    "estimated_wait_minutes": row.estimated_wait_minutes,
                    "zone_id": row.zone_id,
                    "map_x": row.map_x,
                    "map_y": row.map_y,
                    "status_observed_at": row.status_observed_at,
                    "exhibitor_name": row.company_name,
                    "exhibitor_master_approval_status": row.master_approval_status,
                    "consultation_enabled": row.consultation_enabled,
                    "created_at": row.created_at,
                },
            )
        )
    return candidates


async def _fetch_product_candidates(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID
) -> list[MatchCandidate]:
    stmt = (
        select(
            Recommendable.recommendable_id,
            EventProduct.event_product_id,
            EventProduct.participation_id,
            EventProduct.product_id,
            EventProduct.retail_price_amount,
            EventProduct.event_price_amount,
            EventProduct.tasting_status,
            EventProduct.purchase_status,
            EventProduct.inventory_status,
            EventProduct.approval_status,
            EventProduct.status_observed_at,
            EventProduct.created_at,
            Product.product_name,
            Product.alcohol_percentage,
            Product.master_approval_status,
            ProductProfile.category_code,
            ProductProfile.taste_json,
            ProductProfile.aroma_json,
            ProductProfile.usage_json,
            ProductProfile.consumer_score,
            ProductProfile.buyer_score,
            ProductProfile.approval_status.label("product_profile_approval_status"),
            ProductProfile.feature_json,
            ExhibitorParticipation.exhibitor_id,
            ExhibitorParticipation.participation_status,
            ExhibitorParticipation.consultation_enabled,
            Booth.booth_id,
            Booth.map_x,
            Booth.map_y,
        )
        .join(
            Recommendable,
            Recommendable.event_product_id == EventProduct.event_product_id,
        )
        .join(Product, Product.product_id == EventProduct.product_id)
        .outerjoin(ProductProfile, ProductProfile.product_id == Product.product_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == EventProduct.participation_id,
        )
        .outerjoin(Booth, Booth.participation_id == EventProduct.participation_id)
        .where(
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
            Recommendable.active.is_(True),
        )
        .limit(RAW_FETCH_CAP)
    )
    rows = await db.execute(stmt)
    candidates: list[MatchCandidate] = []
    seen: set[uuid.UUID] = set()
    for row in rows:
        if row.event_product_id in seen:
            continue
        seen.add(row.event_product_id)
        candidates.append(
            MatchCandidate(
                object_type="PRODUCT",
                object_id=row.event_product_id,
                recommendable_id=row.recommendable_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                public_object_id=str(row.product_id),
                payload={
                    "product_id": row.product_id,
                    "product_name": row.product_name,
                    "alcohol_percentage": float(row.alcohol_percentage)
                    if row.alcohol_percentage is not None
                    else None,
                    "master_approval_status": row.master_approval_status,
                    "participation_status": row.participation_status,
                    "consultation_enabled": row.consultation_enabled,
                    "category_code": row.category_code,
                    "taste_json": row.taste_json or {},
                    "aroma_json": row.aroma_json or {},
                    "usage_json": row.usage_json or [],
                    "consumer_score": float(row.consumer_score)
                    if row.consumer_score is not None
                    else 0.0,
                    "buyer_score": float(row.buyer_score)
                    if row.buyer_score is not None
                    else 0.0,
                    "product_profile_approval_status": row.product_profile_approval_status,
                    "feature_json": row.feature_json or [],
                    "retail_price_amount": row.retail_price_amount,
                    "event_price_amount": row.event_price_amount,
                    "tasting_status": row.tasting_status,
                    "purchase_status": row.purchase_status,
                    "inventory_status": row.inventory_status,
                    "approval_status": row.approval_status,
                    "status_observed_at": row.status_observed_at,
                    "booth_id": row.booth_id,
                    "map_x": row.map_x,
                    "map_y": row.map_y,
                    "created_at": row.created_at,
                },
            )
        )
    return candidates


async def _fetch_exhibitor_candidates(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID
) -> list[MatchCandidate]:
    stmt = (
        select(
            Recommendable.recommendable_id,
            ExhibitorParticipation.participation_id,
            ExhibitorParticipation.exhibitor_id,
            ExhibitorParticipation.participation_status,
            ExhibitorParticipation.consultation_enabled,
            ExhibitorParticipation.created_at,
            Exhibitor.company_name,
            Exhibitor.master_approval_status,
        )
        .join(
            Recommendable,
            Recommendable.participation_id == ExhibitorParticipation.participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
            Recommendable.active.is_(True),
        )
        .limit(RAW_FETCH_CAP)
    )
    rows = await db.execute(stmt)
    candidates: list[MatchCandidate] = []
    for row in rows:
        candidates.append(
            MatchCandidate(
                object_type="EXHIBITOR",
                object_id=row.exhibitor_id,
                recommendable_id=row.recommendable_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                public_object_id=str(row.exhibitor_id),
                payload={
                    "company_name": row.company_name,
                    "master_approval_status": row.master_approval_status,
                    "participation_status": row.participation_status,
                    "consultation_enabled": row.consultation_enabled,
                    "created_at": row.created_at,
                },
            )
        )
    return candidates


async def _fetch_program_candidates(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID
) -> list[MatchCandidate]:
    stmt = (
        select(
            Recommendable.recommendable_id,
            Program.program_id,
            Program.program_name,
            Program.program_type,
            Program.start_at,
            Program.end_at,
            Program.capacity,
            Program.status,
            Program.zone_id,
            Program.created_at,
        )
        .join(Recommendable, Recommendable.program_id == Program.program_id)
        .where(
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
            Recommendable.active.is_(True),
        )
        .limit(RAW_FETCH_CAP)
    )
    rows = await db.execute(stmt)
    candidates: list[MatchCandidate] = []
    for row in rows:
        candidates.append(
            MatchCandidate(
                object_type="PROGRAM",
                object_id=row.program_id,
                recommendable_id=row.recommendable_id,
                exhibitor_id=None,
                participation_id=None,
                public_object_id=str(row.program_id),
                payload={
                    "program_name": row.program_name,
                    "program_type": row.program_type,
                    "start_at": row.start_at,
                    "end_at": row.end_at,
                    "capacity": row.capacity,
                    "status": row.status,
                    "zone_id": row.zone_id,
                    "created_at": row.created_at,
                },
            )
        )
    return candidates


def _candidate_codes(candidate: MatchCandidate) -> set[str]:
    """구조화 관련도 계산에 쓸 후보의 taxonomy 코드 전체 (카테고리/맛/향/채널/지역)."""

    payload = candidate.payload
    codes: set[str] = set()
    if payload.get("category_code"):
        codes.add(payload["category_code"])
    codes.update((payload.get("taste_json") or {}).keys())
    codes.update((payload.get("aroma_json") or {}).keys())
    codes.update(payload.get("usage_json") or [])
    codes.update(payload.get("business_types") or [])
    supply_profile = payload.get("supply_profile") or {}
    codes.update(supply_profile.get("business_types") or [])
    trade_profile = supply_profile.get("trade_profile") or {}
    codes.update(trade_profile.get("channels") or [])
    codes.update(trade_profile.get("regions") or [])
    return codes


def _relevance_score(
    candidate: MatchCandidate, profile: ResolvedProfile, catalog
) -> float:
    profile_codes = profile.all_codes(
        profile.categories,
        profile.channels,
        profile.regions,
        profile.taste,
        profile.aroma,
    )
    if not profile_codes:
        return 0.0
    return max_match_strength(catalog, profile_codes, _candidate_codes(candidate))


def _quality_score(candidate: MatchCandidate, user_type: str) -> float:
    payload = candidate.payload
    if candidate.object_type == "PRODUCT":
        return (
            payload.get("buyer_score", 0.0) / 100.0
            if user_type == "BUYER"
            else payload.get("consumer_score", 0.0) / 100.0
        )
    supply_profile = payload.get("supply_profile") or {}
    score = supply_profile.get("trade_readiness_score")
    return (score / 100.0) if score is not None else 0.0


def _candidate_identity(candidate: MatchCandidate) -> tuple[str, str]:
    return candidate.object_type, str(candidate.object_id)


def _apply_vector_recall(
    pool: list[MatchCandidate],
    selected: dict[tuple[str, uuid.UUID], MatchCandidate],
    *,
    recall: ProfileSemanticRecall,
    user_type: str,
) -> int:
    """Merge semantic participation hits without allowing product-rich domination."""

    eligible = [
        candidate
        for candidate in pool
        if candidate.participation_id in recall.participation_scores
    ]
    eligible.sort(
        key=lambda candidate: (
            -recall.participation_scores.get(candidate.participation_id, 0.0),
            -_quality_score(candidate, user_type),
            *_candidate_identity(candidate),
        )
    )

    per_participation: dict[uuid.UUID, int] = {}
    applied = 0
    for candidate in eligible:
        if applied >= VECTOR_LIMIT:
            break
        participation_id = candidate.participation_id
        if participation_id is None:
            continue
        participation_count = per_participation.get(participation_id, 0)
        if participation_count >= VECTOR_OBJECTS_PER_PARTICIPATION:
            continue

        score = recall.participation_scores[participation_id]
        key = (candidate.object_type, candidate.object_id)
        target = selected.get(key, candidate)
        target.source_channels.add("VECTOR")
        target.payload["vector_relevance_score"] = score
        target.payload["vector_profile_fingerprint"] = recall.input_fingerprint
        if recall.model_version_id is not None:
            target.payload["vector_model_version_id"] = str(recall.model_version_id)
        selected[key] = target
        per_participation[participation_id] = participation_count + 1
        applied += 1
    return applied


async def _interest_related_ids(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    subject_user_id: uuid.UUID | None,
    subject_guest_session_id: uuid.UUID | None,
) -> set[uuid.UUID]:
    """사용자가 저장한(FAVORITE류) 대상의 exhibitor_id 집합. 같은 업체의 다른 후보를
    "관심목록 연관 후보" 채널로 끌어올리는 데 쓴다.
    """

    stmt = select(InteractionEvent.recommendable_id).where(
        InteractionEvent.tenant_id == tenant_id,
        InteractionEvent.event_id == event_id,
        InteractionEvent.event_type.in_(_INTEREST_EVENT_TYPES),
        InteractionEvent.recommendable_id.is_not(None),
    )
    if subject_user_id is not None:
        stmt = stmt.where(InteractionEvent.user_id == subject_user_id)
    elif subject_guest_session_id is not None:
        stmt = stmt.where(InteractionEvent.guest_session_id == subject_guest_session_id)
    else:
        return set()
    rows = await db.execute(stmt.limit(200))
    recommendable_ids = {row.recommendable_id for row in rows}
    if not recommendable_ids:
        return set()
    exhibitor_rows = await db.execute(
        select(Recommendable.participation_id).where(
            Recommendable.recommendable_id.in_(recommendable_ids)
        )
    )
    participation_ids = {row[0] for row in exhibitor_rows if row[0] is not None}
    if not participation_ids:
        return set()
    exhibitor_id_rows = await db.execute(
        select(ExhibitorParticipation.exhibitor_id).where(
            ExhibitorParticipation.participation_id.in_(participation_ids)
        )
    )
    return {row.exhibitor_id for row in exhibitor_id_rows}


async def generate_candidates(
    db: AsyncSession,
    *,
    validated: ValidatedRequest,
    profile: ResolvedProfile,
    context: ResolvedContext,
    semantic_scorer: SemanticScorer | None = None,
) -> tuple[list[MatchCandidate], dict[str, int]]:
    tenant_id = validated.subject.tenant_id
    event_id = validated.subject.event_id
    object_types = _target_object_types(validated.recommendation_type)

    fetchers = {
        "BOOTH": _fetch_booth_candidates,
        "PRODUCT": _fetch_product_candidates,
        "EXHIBITOR": _fetch_exhibitor_candidates,
        "PROGRAM": _fetch_program_candidates,
    }

    pool: list[MatchCandidate] = []
    for object_type in object_types:
        pool.extend(
            await fetchers[object_type](db, tenant_id=tenant_id, event_id=event_id)
        )

    exhibitor_ids = [c.exhibitor_id for c in pool if c.exhibitor_id is not None]
    supply_profiles = await _load_supply_profiles(db, exhibitor_ids)
    for candidate in pool:
        if (
            candidate.exhibitor_id is not None
            and candidate.exhibitor_id in supply_profiles
        ):
            candidate.payload["supply_profile"] = supply_profiles[
                candidate.exhibitor_id
            ]

    catalog = get_catalog()
    channel_counts: dict[str, int] = {}
    selected: dict[tuple[str, uuid.UUID], MatchCandidate] = {}

    # 1. 구조화 속성 검색: 프로파일 코드와의 관련도 상위 STRUCTURED_LIMIT.
    scored = sorted(
        pool,
        key=lambda candidate: (
            -_relevance_score(candidate, profile, catalog),
            *_candidate_identity(candidate),
        ),
    )
    for candidate in scored[:STRUCTURED_LIMIT]:
        candidate.source_channels.add("STRUCTURED")
        selected[(candidate.object_type, candidate.object_id)] = candidate
    channel_counts["STRUCTURED"] = min(STRUCTURED_LIMIT, len(pool))

    # 2. 프로파일 의미 검색. 개인정보 원문이 아닌 온톨로지 코드만 임베딩하며,
    # 장애/비활성화 시 구조화 채널을 그대로 유지한다.
    vector_recall = await recall_profile_participations(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        profile=profile,
        semantic_scorer=semantic_scorer or NullSemanticScorer(),
    )
    channel_counts["VECTOR"] = _apply_vector_recall(
        pool,
        selected,
        recall=vector_recall,
        user_type=profile.user_type,
    )
    if vector_recall.status == "DISABLED":
        channel_counts["VECTOR_DISABLED"] = 1
    elif vector_recall.status == "UNAVAILABLE":
        channel_counts["VECTOR_UNAVAILABLE"] = 1

    # 3. 인기·품질 기반 후보.
    quality_sorted = sorted(
        pool,
        key=lambda candidate: (
            -_quality_score(candidate, profile.user_type),
            *_candidate_identity(candidate),
        ),
    )
    added = 0
    for candidate in quality_sorted:
        if added >= POPULARITY_LIMIT:
            break
        key = (candidate.object_type, candidate.object_id)
        existing = selected.get(key)
        if existing is not None:
            existing.source_channels.add("POPULARITY")
            continue
        candidate.source_channels.add("POPULARITY")
        selected[key] = candidate
        added += 1
    channel_counts["POPULARITY"] = added

    # 4. 운영자 지정 후보 - 큐레이션 테이블이 없어 no-op.
    channel_counts["OPERATOR_PINNED"] = 0

    # 5. 사용자 관심목록 연관 후보.
    interest_exhibitor_ids = await _interest_related_ids(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        subject_user_id=validated.subject.user_id,
        subject_guest_session_id=validated.subject.guest_session_id,
    )
    added = 0
    if interest_exhibitor_ids:
        for candidate in sorted(pool, key=_candidate_identity):
            if added >= INTEREST_LIMIT:
                break
            if candidate.exhibitor_id not in interest_exhibitor_ids:
                continue
            key = (candidate.object_type, candidate.object_id)
            existing = selected.get(key)
            if existing is not None:
                existing.source_channels.add("INTEREST")
                continue
            candidate.source_channels.add("INTEREST")
            selected[key] = candidate
            added += 1
    channel_counts["INTEREST"] = added

    # 6. 탐색·신규성 후보 - 최근 승인된 순.
    recency_sorted = sorted(
        pool,
        key=lambda c: (
            c.payload.get("created_at") or context.server_time - timedelta(days=3650)
        ),
        reverse=True,
    )
    added = 0
    for candidate in recency_sorted:
        if added >= EXPLORATION_LIMIT:
            break
        key = (candidate.object_type, candidate.object_id)
        existing = selected.get(key)
        if existing is not None:
            existing.source_channels.add("EXPLORATION")
            continue
        candidate.source_channels.add("EXPLORATION")
        selected[key] = candidate
        added += 1
    channel_counts["EXPLORATION"] = added

    merged = list(selected.values())[:TOTAL_POOL_CAP]
    channel_counts["TOTAL_MERGED"] = len(merged)
    return merged, channel_counts

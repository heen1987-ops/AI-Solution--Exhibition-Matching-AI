"""바이어 매칭 세션 생성/조회 오케스트레이션.

``ai.buyer_matching`` 라이브러리에 대한 메모 (AI-BUYER-MATCH 트랙과의 통합 지점)
------------------------------------------------------------------------------
작업 지시는 이 오케스트레이터가 "ai.buyer_matching 라이브러리를 호출"하도록 요구했지만,
이 트랙이 실행되는 시점에 ``ai/`` 아래에는 ``query_interpreter.py``/``keyword_retriever.py``만
있고 바이어 매칭 전용 모듈은 아직 없다(그리고 이 트랙의 owned_paths에는 ``ai/**``가 포함되지
않으므로 여기서 새로 만들 수도 없다). 대신 이 모듈은 그 라이브러리가 맡을 책임
(하드필터를 통과한 후보에 대한 점수·등급·근거코드·unknown_fields 계산)을
``app/services/buyer_match/eligibility.py``·``scoring.py``의 순수 함수로 자체 구현했다.

**통합 시 해야 할 일**: ``ai.buyer_matching`` 모듈이 게시되면, 이 파일의
``_score_candidates`` 호출부만 그 라이브러리 호출로 교체하면 된다 - 나머지(세션 영속화,
접근제어, 하드필터로 절대 통과 못 하는 후보를 애초에 결과에 넣지 않는 것)는 그대로 유지된다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_match import BuyerMatchCandidate, BuyerMatchSession
from app.models.exhibitor import (
    Exhibitor,
    ExhibitorParticipation,
    ExhibitorProfile,
    ParticipationCategory,
    TradeCondition,
)
from app.models.ontology_refs import concept
from app.models.profile import BuyerNeed
from app.services.buyer_match.access import BuyerContext
from app.services.buyer_match.eligibility import (
    BuyerCriteria,
    CandidateRow,
    hard_filter,
)
from app.services.buyer_match.scoring import score_candidate

#: 이 트랙이 자체 정의한 개방형 정책 버전 문자열. 정식 matching.match_policy_version으로
#: 승격하기 전까지는 상수로 관리한다(app/models/buyer_match.py BuyerMatchSession.policy_version
#: 컬럼 주석 참고).
POLICY_VERSION = "buyer_match_policy_v1_2026_08_02"
DEFAULT_LIMIT = 20
#: access.py LIMITED 등급 바이어에게 적용하는 정책상 결과 축소 (Blocker Score 5~6 가정,
#: access.py 모듈 docstring 참고).
LIMITED_TIER_MAX_LIMIT = 10
DEFAULT_SESSION_TTL = timedelta(hours=6)


async def _load_candidate_rows(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_id: uuid.UUID
) -> list[CandidateRow]:
    """승인된 업체·행사참가만 후보로 올린다 (미승인 데이터는 절대 노출하지 않는다)."""

    stmt = (
        select(Exhibitor, ExhibitorParticipation, ExhibitorProfile, TradeCondition, concept.c.concept_code)
        .select_from(Exhibitor)
        .join(
            ExhibitorParticipation,
            and_(
                ExhibitorParticipation.exhibitor_id == Exhibitor.exhibitor_id,
                ExhibitorParticipation.tenant_id == Exhibitor.tenant_id,
            ),
        )
        .outerjoin(ExhibitorProfile, ExhibitorProfile.exhibitor_id == Exhibitor.exhibitor_id)
        .outerjoin(
            TradeCondition,
            and_(
                TradeCondition.participation_id == ExhibitorParticipation.participation_id,
                TradeCondition.event_product_id.is_(None),
            ),
        )
        .outerjoin(concept, concept.c.concept_id == Exhibitor.region_concept_id)
        .where(
            Exhibitor.tenant_id == tenant_id,
            Exhibitor.deleted_at.is_(None),
            Exhibitor.master_approval_status == "APPROVED",
            ExhibitorParticipation.event_id == event_id,
            ExhibitorParticipation.participation_status == "APPROVED",
        )
    )
    rows = (await db.execute(stmt)).all()

    # 업체 공통 거래조건이 데이터 이상으로 여러 행 존재하면 첫 번째만 사용한다(방어적 처리).
    seen: dict[uuid.UUID, tuple] = {}
    for row in rows:
        exhibitor = row[0]
        if exhibitor.exhibitor_id not in seen:
            seen[exhibitor.exhibitor_id] = row

    participation_ids = [row[1].participation_id for row in seen.values()]
    categories_by_participation: dict[uuid.UUID, set[str]] = {}
    if participation_ids:
        category_rows = (
            await db.execute(
                select(ParticipationCategory.participation_id, concept.c.concept_code).join(
                    concept, concept.c.concept_id == ParticipationCategory.concept_id
                ).where(ParticipationCategory.participation_id.in_(participation_ids))
            )
        ).all()
        for participation_id, code in category_rows:
            categories_by_participation.setdefault(participation_id, set()).add(code)

    candidates: list[CandidateRow] = []
    for exhibitor, participation, profile, trade_condition, region_code in seen.values():
        candidates.append(
            CandidateRow(
                exhibitor_id=exhibitor.exhibitor_id,
                participation_id=participation.participation_id,
                category_codes=frozenset(
                    categories_by_participation.get(participation.participation_id, set())
                ),
                region_code=region_code,
                has_trade_condition=trade_condition is not None,
                oem_status=(trade_condition.oem_status if trade_condition else None),
                private_label_status=(
                    trade_condition.private_label_status if trade_condition else None
                ),
                export_status=(trade_condition.export_status if trade_condition else None),
                min_order_quantity=(
                    trade_condition.min_order_quantity if trade_condition else None
                ),
                max_order_quantity=(
                    trade_condition.max_order_quantity if trade_condition else None
                ),
                wholesale_price_min=(
                    trade_condition.wholesale_price_min_amount if trade_condition else None
                ),
                wholesale_price_max=(
                    trade_condition.wholesale_price_max_amount if trade_condition else None
                ),
                profile_approved=(profile is not None and profile.approval_status == "APPROVED"),
            )
        )
    return candidates


async def _resolve_criteria(
    db: AsyncSession, *, buyer: BuyerContext, filters: BuyerCriteria
) -> BuyerCriteria:
    """요청 필터가 비워둔 축은 BuyerNeed(바이어가 등록한 기본 희망조건)로 보강한다."""

    if filters.price_min is not None or filters.price_max is not None:
        return filters
    buyer_need = await db.get(BuyerNeed, buyer.profile_id)
    if buyer_need is None:
        return filters
    return BuyerCriteria(
        categories=filters.categories,
        channels=filters.channels,
        regions=filters.regions,
        price_min=buyer_need.target_price_min_amount,
        price_max=buyer_need.target_price_max_amount,
        monthly_units_min=filters.monthly_units_min or buyer_need.monthly_units_min,
        monthly_units_max=filters.monthly_units_max or buyer_need.monthly_units_max,
        oem_required=filters.oem_required,
        private_label_required=filters.private_label_required,
        export_required=filters.export_required,
    )


async def create_buyer_match_session(
    db: AsyncSession,
    *,
    buyer: BuyerContext,
    filters: BuyerCriteria,
    limit: int | None,
) -> BuyerMatchSession:
    effective_limit = limit or DEFAULT_LIMIT
    if buyer.verification_tier == "LIMITED":
        effective_limit = min(effective_limit, LIMITED_TIER_MAX_LIMIT)

    effective_criteria = await _resolve_criteria(db, buyer=buyer, filters=filters)
    candidates = await _load_candidate_rows(
        db, tenant_id=buyer.tenant_id, event_id=buyer.event_id
    )
    candidate_count = len(candidates)

    scored = []
    for row in candidates:
        outcome = hard_filter(row, effective_criteria)
        if not outcome.passed:
            continue
        scored.append(score_candidate(row, effective_criteria))
    filtered_count = candidate_count - len(scored)

    scored.sort(key=lambda item: item.score, reverse=True)
    top = scored[:effective_limit]

    now = datetime.now(UTC)
    session = BuyerMatchSession(
        tenant_id=buyer.tenant_id,
        event_id=buyer.event_id,
        buyer_profile_id=buyer.profile_id,
        profile_version=buyer.profile_version,
        policy_version=POLICY_VERSION,
        verification_tier=buyer.verification_tier,
        filters_json=filters.to_json(),
        candidate_count=candidate_count,
        filtered_count=filtered_count,
        result_count=len(top),
        status="ACTIVE",
        generated_at=now,
        expires_at=now + DEFAULT_SESSION_TTL,
    )
    db.add(session)
    await db.flush()

    for rank, item in enumerate(top, start=1):
        db.add(
            BuyerMatchCandidate(
                buyer_match_session_id=session.buyer_match_session_id,
                tenant_id=buyer.tenant_id,
                exhibitor_id=item.exhibitor_id,
                participation_id=item.participation_id,
                rank=rank,
                score=item.score,
                grade=item.grade,
                hard_filter_passed=True,
                reason_codes=item.reason_codes,
                unknown_fields=item.unknown_fields,
            )
        )

    await db.commit()
    await db.refresh(session, attribute_names=["candidates"])
    return session


class BuyerMatchSessionNotAccessible(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def get_buyer_match_session_for_buyer(
    db: AsyncSession, *, buyer_match_session_id: uuid.UUID, buyer_profile_id: uuid.UUID
) -> BuyerMatchSession:
    """본인 소유 세션만 반환한다. 미존재/타인소유를 구분해서 노출하지 않는다."""

    session = await db.get(BuyerMatchSession, buyer_match_session_id)
    if session is None or session.buyer_profile_id != buyer_profile_id:
        raise BuyerMatchSessionNotAccessible(
            "BUYER_MATCH_SESSION_FORBIDDEN",
            "본인 소유의 매칭 세션만 조회할 수 있습니다.",
        )
    # AsyncSession의 기본 지연로딩(lazy="select")은 명시적으로 await하지 않으면 async 컨텍스트
    # 밖에서 접근 시 오류가 나므로, 반환 전에 candidates 관계를 명시적으로 로드해 둔다.
    await db.refresh(session, attribute_names=["candidates"])
    return session

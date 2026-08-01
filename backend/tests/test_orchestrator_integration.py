"""오케스트레이터 종단 통합테스트 (실제 Postgres 필요).

이전에는 GENERAL_VISITOR/BUYER 경로를 검증하는 수동 스크립트(smoke_test_orchestrator.py,
smoke_test_buyer.py)만 있었고 정식 pytest 스위트에는 없었다 - 비동기 DB 통합테스트
관례가 이 저장소에 없었기 때문이다(conftest.py 참고). 이제 그 관례가 생겼으므로 두 스크립트를
이 파일로 옮기고, 카테고리 매칭 보정(structured_search_exhibitors의 category_concept_ids
채움)을 검증하는 시나리오를 하나 추가했다.

TEST_DATABASE_URL에 연결할 수 없으면 conftest.db_engine이 이 모듈의 테스트 전부를
건너뛴다. conftest.db_session이 트랜잭션을 자동으로 롤백해주지 않으므로(conftest.py
모듈 docstring 참고) tenant_code/concept_code 등 UNIQUE 컬럼에는 매 호출마다
`_unique_suffix()`로 접미사를 붙여 테스트끼리, 그리고 재실행 사이에 충돌하지 않게 한다.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Event, Tenant
from app.models.exhibitor import (
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
    ProductAttribute,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.identity import GuestSession, UserAccount
from app.models.matching import MatchPolicyVersion, MatchResult, Recommendable
from app.models.profile import BuyerNeed, ProfileAttribute, ProfileVersion, UserProfile
from app.services.matching.orchestrator import (
    BuyerRecommendationRequest,
    GeneralVisitorRecommendationRequest,
    generate_buyer_recommendations,
    generate_general_visitor_recommendations,
)


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _seed_ontology_concept(
    session: AsyncSession, *, suffix: str, concept_code: str, concept_type: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """온톨로지 개념 하나를 최소 시딩한다(ORM 모델이 아직 없어 raw SQL, feature_builder.py
    모듈 docstring "concept 기반 구성요소" 참고). taxonomy_version은 DRAFT로 남겨둔다 -
    PUBLISHED로 만들면 불변성 트리거가 concept_revision INSERT를 막는다. semantic_version은
    (tenant_id, semantic_version) UNIQUE(NULLS NOT DISTINCT) 대상이고 tenant_id는 항상
    NULL이라 suffix로 유일성을 보장해야 한다. 반환값은 (taxonomy_version_id, concept_id)."""

    taxonomy_version_id = uuid.uuid4()
    concept_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO ontology.taxonomy_version "
            "(taxonomy_version_id, semantic_version, status, checksum) "
            "VALUES (:tvid, :semver, 'DRAFT', :checksum)"
        ),
        {
            "tvid": taxonomy_version_id,
            "semver": f"1.0.0-it-{suffix}",
            "checksum": hashlib.sha256(f"it-{suffix}".encode()).digest(),
        },
    )
    await session.execute(
        text(
            "INSERT INTO ontology.concept "
            "(concept_id, concept_code, concept_type) "
            "VALUES (:cid, :code, :ctype)"
        ),
        {"cid": concept_id, "code": concept_code, "ctype": concept_type},
    )
    await session.execute(
        text(
            "INSERT INTO ontology.concept_revision "
            "(taxonomy_version_id, concept_id) VALUES (:tvid, :cid)"
        ),
        {"tvid": taxonomy_version_id, "cid": concept_id},
    )
    return taxonomy_version_id, concept_id


async def _seed_general_visitor_scenario(
    session: AsyncSession,
    *,
    require_sensory: bool = False,
    tag_product_sensory: bool = False,
) -> GeneralVisitorRecommendationRequest:
    suffix = _unique_suffix()
    tenant = Tenant(
        tenant_code=f"it-general-visitor-{suffix}", tenant_name="IT General Visitor"
    )
    session.add(tenant)
    await session.flush()

    event = Event(
        tenant_id=tenant.tenant_id,
        event_code=f"it-event-general-visitor-{suffix}",
        event_name="IT Event",
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 11),
    )
    session.add(event)
    await session.flush()

    exhibitor = Exhibitor(
        tenant_id=tenant.tenant_id,
        company_name="IT Brewery",
        master_approval_status="APPROVED",
    )
    session.add(exhibitor)
    await session.flush()

    product = Product(
        exhibitor_id=exhibitor.exhibitor_id,
        product_name="IT Soju",
        master_approval_status="APPROVED",
    )
    session.add(product)
    await session.flush()

    participation = ExhibitorParticipation(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        exhibitor_id=exhibitor.exhibitor_id,
        participation_status="APPROVED",
    )
    session.add(participation)
    await session.flush()

    event_product = EventProduct(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        participation_id=participation.participation_id,
        product_id=product.product_id,
        event_price_amount=20_000,
        approval_status="APPROVED",
    )
    session.add(event_product)
    await session.flush()

    sensory_concept_id: uuid.UUID | None = None
    sensory_taxonomy_version_id: uuid.UUID | None = None
    if require_sensory or tag_product_sensory:
        sensory_taxonomy_version_id, sensory_concept_id = await _seed_ontology_concept(
            session,
            suffix=suffix,
            concept_code=f"TASTE.DRY.X{suffix.upper()}",
            concept_type="TASTE",
        )
        if tag_product_sensory:
            session.add(
                ProductAttribute(
                    product_id=product.product_id,
                    taxonomy_version_id=sensory_taxonomy_version_id,
                    concept_id=sensory_concept_id,
                    text_value="DRY",
                    source="OPERATOR",
                    review_status="APPROVED",
                )
            )
            await session.flush()

    recommendable = Recommendable(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        object_type="EVENT_PRODUCT",
        event_product_id=event_product.event_product_id,
    )
    session.add(recommendable)

    policy = MatchPolicyVersion(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        user_type="GENERAL_VISITOR",
        version="v1",
        status="ACTIVE",
    )
    session.add(policy)

    guest_session = GuestSession(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        session_token_hmac=uuid.uuid4().bytes,
        entry_channel="WEB",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(guest_session)
    await session.flush()

    profile = UserProfile(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        user_id=None,
        guest_session_id=guest_session.guest_session_id,
        user_type="GENERAL_VISITOR",
    )
    session.add(profile)
    await session.flush()

    profile_version = ProfileVersion(
        profile_id=profile.profile_id,
        version_number=1,
        snapshot_json={},
        change_reason="USER_UPDATE",
    )
    session.add(profile_version)

    if require_sensory:
        assert sensory_concept_id is not None
        assert sensory_taxonomy_version_id is not None
        session.add(
            ProfileAttribute(
                profile_id=profile.profile_id,
                taxonomy_version_id=sensory_taxonomy_version_id,
                concept_id=sensory_concept_id,
                attribute_code=f"TASTE.DRY.X{suffix.upper()}",
                value_json={"selected": True},
                requirement_level="PREFERRED",
                source_type="USER_SELECTED",
            )
        )

    await session.commit()

    return GeneralVisitorRecommendationRequest(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        profile_id=profile.profile_id,
        visit_session_id=None,
        policy_version_id=policy.policy_version_id,
        required_category_concept_ids=frozenset(),
        price_min=None,
        price_max=50_000,
        limit=10,
    )


async def test_generate_general_visitor_recommendations_end_to_end(
    db_session: AsyncSession,
) -> None:
    request = await _seed_general_visitor_scenario(db_session)

    recommendation_session = await generate_general_visitor_recommendations(
        db_session, request
    )
    await db_session.commit()

    assert recommendation_session.result_count == 1

    results = (
        (
            await db_session.execute(
                select(MatchResult).where(
                    MatchResult.recommendation_session_id
                    == recommendation_session.recommendation_session_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(results) == 1
    assert results[0].recommended_action == "VISIT_NOW"
    assert float(results[0].normalized_score) == pytest.approx(100.0)


async def test_generate_general_visitor_recommendations_scores_lower_on_sensory_mismatch(
    db_session: AsyncSession,
) -> None:
    """profile_resolver의 ProfileAttribute를 온톨로지 concept_type(attribute_code 접두어)
    으로 해석해 feature_builder의 sensory 구성요소를 채우는 연결(item 3)을 검증한다:
    후보가 프로파일이 요구하는 맛(TASTE.DRY)을 실제로 갖고 있는 시나리오가, 같은 요구를
    갖고 있지만 후보에는 그 속성이 없는 시나리오보다 raw_score가 높아야 한다."""

    matching_request = await _seed_general_visitor_scenario(
        db_session, require_sensory=True, tag_product_sensory=True
    )
    matching_session = await generate_general_visitor_recommendations(
        db_session, matching_request
    )
    await db_session.commit()

    mismatched_request = await _seed_general_visitor_scenario(
        db_session, require_sensory=True, tag_product_sensory=False
    )
    mismatched_session = await generate_general_visitor_recommendations(
        db_session, mismatched_request
    )
    await db_session.commit()

    matching_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == matching_session.recommendation_session_id
            )
        )
    ).scalar_one()
    mismatched_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == mismatched_session.recommendation_session_id
            )
        )
    ).scalar_one()

    assert float(matching_result.raw_score) > float(mismatched_result.raw_score)


async def _seed_buyer_scenario(
    session: AsyncSession,
    *,
    with_matching_category: bool,
    require_channel: bool = False,
    tag_exhibitor_channel: bool = False,
) -> BuyerRecommendationRequest:
    suffix = _unique_suffix()
    category_label = "category" if with_matching_category else "no-category"
    tenant_code = f"it-buyer-{category_label}-{suffix}"
    tenant = Tenant(tenant_code=tenant_code, tenant_name="IT Buyer")
    session.add(tenant)
    await session.flush()

    event = Event(
        tenant_id=tenant.tenant_id,
        event_code=f"{tenant_code}-event",
        event_name="IT Buyer Event",
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 11),
    )
    session.add(event)
    await session.flush()

    exhibitor = Exhibitor(
        tenant_id=tenant.tenant_id,
        company_name="IT Distillery",
        master_approval_status="APPROVED",
    )
    session.add(exhibitor)
    await session.flush()

    participation = ExhibitorParticipation(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        exhibitor_id=exhibitor.exhibitor_id,
        participation_status="APPROVED",
    )
    session.add(participation)
    await session.flush()

    trade_condition = TradeCondition(
        participation_id=participation.participation_id,
        event_product_id=None,
        min_order_quantity=100,
        monthly_capacity=3_000,
        wholesale_price_max_amount=40_000,
        approval_status="APPROVED",
    )
    session.add(trade_condition)
    await session.flush()

    required_category_concept_ids: frozenset[uuid.UUID] = frozenset()
    if with_matching_category:
        # concept_code CHECK 제약(^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$)은 각 점 구간이
        # 문자로 시작해야 한다 - hex suffix 앞에 "X"를 붙인다.
        taxonomy_version_id, category_concept_id = await _seed_ontology_concept(
            session,
            suffix=suffix,
            concept_code=f"CATEGORY.SPIRITS.SOJU.X{suffix.upper()}",
            concept_type="CATEGORY",
        )

        product = Product(
            exhibitor_id=exhibitor.exhibitor_id,
            product_name="IT Premium Soju",
            category_taxonomy_version_id=taxonomy_version_id,
            category_concept_id=category_concept_id,
        )
        session.add(product)
        await session.flush()

        event_product = EventProduct(
            tenant_id=tenant.tenant_id,
            event_id=event.event_id,
            participation_id=participation.participation_id,
            product_id=product.product_id,
            approval_status="APPROVED",
        )
        session.add(event_product)
        await session.flush()

        required_category_concept_ids = frozenset({category_concept_id})

    channel_concept_id: uuid.UUID | None = None
    channel_taxonomy_version_id: uuid.UUID | None = None
    if require_channel or tag_exhibitor_channel:
        channel_taxonomy_version_id, channel_concept_id = await _seed_ontology_concept(
            session,
            suffix=suffix,
            concept_code=f"CHANNEL.HORECA.X{suffix.upper()}",
            concept_type="CHANNEL",
        )
        if tag_exhibitor_channel:
            session.add(
                TradeConditionTerm(
                    trade_condition_id=trade_condition.trade_condition_id,
                    term_type="CHANNEL",
                    taxonomy_version_id=channel_taxonomy_version_id,
                    concept_id=channel_concept_id,
                )
            )
            await session.flush()

    recommendable = Recommendable(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        object_type="EXHIBITOR",
        participation_id=participation.participation_id,
    )
    session.add(recommendable)

    policy = MatchPolicyVersion(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        user_type="BUYER",
        version="v1",
        status="ACTIVE",
    )
    session.add(policy)

    buyer_account = UserAccount(
        authentication_state="ACCOUNT_AUTHENTICATED", account_status="ACTIVE"
    )
    session.add(buyer_account)
    await session.flush()

    profile = UserProfile(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        user_id=buyer_account.user_id,
        guest_session_id=None,
        user_type="BUYER",
    )
    session.add(profile)
    await session.flush()

    profile_version = ProfileVersion(
        profile_id=profile.profile_id,
        version_number=1,
        snapshot_json={},
        change_reason="USER_UPDATE",
    )
    session.add(profile_version)

    if require_channel:
        assert channel_concept_id is not None
        assert channel_taxonomy_version_id is not None
        session.add(
            ProfileAttribute(
                profile_id=profile.profile_id,
                taxonomy_version_id=channel_taxonomy_version_id,
                concept_id=channel_concept_id,
                attribute_code=f"CHANNEL.HORECA.X{suffix.upper()}",
                value_json={"selected": True},
                requirement_level="PREFERRED",
                source_type="USER_SELECTED",
            )
        )

    buyer_need = BuyerNeed(profile_id=profile.profile_id)
    session.add(buyer_need)
    await session.commit()

    return BuyerRecommendationRequest(
        tenant_id=tenant.tenant_id,
        event_id=event.event_id,
        profile_id=profile.profile_id,
        visit_session_id=None,
        policy_version_id=policy.policy_version_id,
        required_category_concept_ids=required_category_concept_ids,
        target_price_max=50_000,
        max_order_quantity=200,
        requested_monthly_units=100,
        limit=10,
    )


async def test_generate_buyer_recommendations_end_to_end(
    db_session: AsyncSession,
) -> None:
    request = await _seed_buyer_scenario(db_session, with_matching_category=False)

    recommendation_session = await generate_buyer_recommendations(db_session, request)
    await db_session.commit()

    assert recommendation_session.result_count == 1

    results = (
        (
            await db_session.execute(
                select(MatchResult).where(
                    MatchResult.recommendation_session_id
                    == recommendation_session.recommendation_session_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(results) == 1
    assert results[0].recommended_action == "REQUEST_MEETING"


async def test_generate_buyer_recommendations_scores_higher_with_matching_category(
    db_session: AsyncSession,
) -> None:
    """구조화 검색이 업체의 출품 제품 카테고리를 채우면(candidate_generator._exhibitor_
    category_concept_ids) build_buyer_components의 product 구성요소가 더 이상 항상
    None이 아니게 된다 - 카테고리가 일치하는 시나리오의 raw_score가, 요구 카테고리를
    지정하지 않은 시나리오보다 높아야 한다(모든 조건이 같고 product 구성요소만 다르다)."""

    baseline_request = await _seed_buyer_scenario(
        db_session, with_matching_category=False
    )
    baseline_session = await generate_buyer_recommendations(
        db_session, baseline_request
    )
    await db_session.commit()

    matching_request = await _seed_buyer_scenario(
        db_session, with_matching_category=True
    )
    matching_session = await generate_buyer_recommendations(
        db_session, matching_request
    )
    await db_session.commit()

    baseline_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == baseline_session.recommendation_session_id
            )
        )
    ).scalar_one()
    matching_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == matching_session.recommendation_session_id
            )
        )
    ).scalar_one()

    assert float(matching_result.raw_score) > float(baseline_result.raw_score)


async def test_generate_buyer_recommendations_scores_lower_on_channel_mismatch(
    db_session: AsyncSession,
) -> None:
    """buyer_profile_facts.required_concept_ids_by_component(ProfileAttribute의
    CHANNEL.* 접두어를 해석한 결과)와 exhibition.trade_condition_term(term_type='CHANNEL')
    을 연결한 부분(item 3)을 검증한다: 바이어가 요구하는 유통채널을 업체가 실제로 등록해
    둔 시나리오가, 같은 요구를 갖고 있지만 업체 쪽에 등록이 없는 시나리오보다 raw_score가
    높아야 한다."""

    matching_request = await _seed_buyer_scenario(
        db_session,
        with_matching_category=False,
        require_channel=True,
        tag_exhibitor_channel=True,
    )
    matching_session = await generate_buyer_recommendations(
        db_session, matching_request
    )
    await db_session.commit()

    mismatched_request = await _seed_buyer_scenario(
        db_session,
        with_matching_category=False,
        require_channel=True,
        tag_exhibitor_channel=False,
    )
    mismatched_session = await generate_buyer_recommendations(
        db_session, mismatched_request
    )
    await db_session.commit()

    matching_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == matching_session.recommendation_session_id
            )
        )
    ).scalar_one()
    mismatched_result = (
        await db_session.execute(
            select(MatchResult).where(
                MatchResult.recommendation_session_id
                == mismatched_session.recommendation_session_id
            )
        )
    ).scalar_one()

    assert float(matching_result.raw_score) > float(mismatched_result.raw_score)

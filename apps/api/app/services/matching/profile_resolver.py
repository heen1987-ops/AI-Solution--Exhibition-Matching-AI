"""② Profile Resolver - docs/05-ai-matching-engine-architecture.md 5.2절.

여러 위치에 저장된 사용자 데이터를 하나의 추천용 프로파일로 통합한다. 출력 형태는 이 단계의
근거문서 우선순위 원칙(도메인별로는 07/08 문서가 db-erd보다 우선)에 따라
docs/07-user-profile-model.md 26.5·27절의 JSON 스펙을 그대로 따른다. 05번 문서 5.6절
Feature Builder가 요구하는 취향(taste)·향(aroma) 축은 27절 예시에는 없지만 같은 모양
(TaxonomyItem 목록)으로 자연스럽게 확장했다 - 27절이 "requirements" 아래 categories/
channels/regions만 예시한 것은 지면상 생략일 뿐, 05번 문서 5.6절이 "맛 선호 일치도"를
명시적으로 요구하므로 같은 구조로 채워 넣지 않으면 뒷단 단계가 동작할 수 없다.

프로파일 우선순위(05번 문서 5.2절 "사용자 직접 입력 > 사용자가 수정한 값 > 최근 명시적
피드백 > 반복 행동에서 추론한 값 > AI 자연어 추출값 > 기본값")는 profile.profile_attribute의
source_type과 requirement_level로 이미 반영되어 있다고 보고(작성 시점 값이 이미 그 우선순위를
거쳐 확정된 값이라는 전제), 이 단계에서는 activate=True인 속성을 그대로 신뢰한다. 우선순위
자체를 적용하는 것은 프로파일 갱신 API(다른 에이전트 책임)의 몫이다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import UserAccount
from app.models.profile import (
    BuyerNeed,
    ContextProfile,
    ProfileAttribute,
    ProfileVersion,
    UserProfile,
    VisitSession,
)
from app.services.matching import errors
from app.services.matching.ontology_support import concept_type_of, get_catalog
from app.services.matching.types import (
    GoalItem,
    ResolvedProfile,
    SubjectContext,
    TaxonomyItem,
)

_GOAL_CONCEPT_TYPES = {"VISIT_GOAL", "BUSINESS_GOAL"}
_BUCKET_CONCEPT_TYPES = {
    "PRODUCT_CATEGORY": "categories",
    "CHANNEL": "channels",
    "REGION": "regions",
    "TASTE": "taste",
    "AROMA": "aroma",
}


async def resolve_profile(
    db: AsyncSession, *, subject: SubjectContext
) -> ResolvedProfile:
    profile = await db.get(UserProfile, subject.profile_id)
    if profile is None or profile.deleted_at is not None:
        raise errors.profile_incomplete("추천을 생성하려면 먼저 프로파일이 필요합니다.")

    attrs = (
        (
            await db.execute(
                select(ProfileAttribute).where(
                    ProfileAttribute.profile_id == profile.profile_id,
                    ProfileAttribute.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    catalog = get_catalog()
    goals: list[GoalItem] = []
    buckets: dict[str, list[TaxonomyItem]] = {
        name: [] for name in _BUCKET_CONCEPT_TYPES.values()
    }
    extra: dict[str, list[TaxonomyItem]] = {}

    for attr in attrs:
        concept_type = concept_type_of(catalog, attr.attribute_code)
        item = TaxonomyItem(
            code=attr.attribute_code,
            level=attr.requirement_level,
            confidence=float(attr.confidence),
        )
        if concept_type in _GOAL_CONCEPT_TYPES:
            goals.append(
                GoalItem(
                    code=attr.attribute_code,
                    priority=attr.priority,
                    requirement_level=attr.requirement_level,
                    confidence=float(attr.confidence),
                    source=attr.source_type,
                )
            )
        elif concept_type in _BUCKET_CONCEPT_TYPES:
            buckets[_BUCKET_CONCEPT_TYPES[concept_type]].append(item)
        else:
            key = (concept_type or "UNCLASSIFIED").lower()
            extra.setdefault(key, []).append(item)

    numeric_conditions: dict[str, Any] = {}
    buyer_need: BuyerNeed | None = None
    if profile.user_type == "BUYER":
        buyer_need = await db.get(BuyerNeed, profile.profile_id)
        if buyer_need is not None:
            price_key_max = (
                "wholesale_price_max"
                if buyer_need.price_basis == "WHOLESALE_PRICE"
                else "retail_price_max"
            )
            price_key_min = (
                "wholesale_price_min"
                if buyer_need.price_basis == "WHOLESALE_PRICE"
                else "retail_price_min"
            )
            if buyer_need.target_price_max_amount is not None:
                numeric_conditions[price_key_max] = buyer_need.target_price_max_amount
            if buyer_need.target_price_min_amount is not None:
                numeric_conditions[price_key_min] = buyer_need.target_price_min_amount
            if buyer_need.monthly_units_min is not None:
                numeric_conditions["monthly_units_min"] = buyer_need.monthly_units_min
            if buyer_need.monthly_units_max is not None:
                numeric_conditions["monthly_units_max"] = buyer_need.monthly_units_max
    else:
        # 07/08 문서 모두 일반 관람객의 가격 상한을 담을 전용 컬럼을 정의하지 않는다.
        # PRICE_BAND concept_type 속성의 value_json에 {"max": ...}/{"min": ...} 형태로
        # 저장된 값을 관례적으로 찾는다. TODO(07번 문서 가격 필드 확정 후 재검토).
        for attr in attrs:
            if concept_type_of(catalog, attr.attribute_code) != "PRICE_BAND":
                continue
            if not isinstance(attr.value_json, dict):
                continue
            if "max" in attr.value_json:
                numeric_conditions.setdefault(
                    "retail_price_max", attr.value_json["max"]
                )
            if "min" in attr.value_json:
                numeric_conditions.setdefault(
                    "retail_price_min", attr.value_json["min"]
                )

    raw_context: dict[str, Any] = {}
    visit_session = (
        await db.execute(
            select(VisitSession)
            .where(VisitSession.profile_id == profile.profile_id)
            .order_by(VisitSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if visit_session is not None:
        latest_ctx = (
            await db.execute(
                select(ContextProfile)
                .where(
                    ContextProfile.visit_session_id == visit_session.visit_session_id
                )
                .order_by(ContextProfile.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        raw_context["remaining_minutes"] = (
            latest_ctx.remaining_minutes
            if latest_ctx is not None
            else visit_session.available_minutes
        )
        raw_context["current_zone"] = None
        raw_context["avoid_congestion"] = (
            bool(latest_ctx.avoid_congestion) if latest_ctx is not None else False
        )

    if profile.user_type == "BUYER" and buyer_need is not None:
        user_account = (
            await db.get(UserAccount, profile.user_id)
            if profile.user_id is not None
            else None
        )
        identity_verification = None
        if user_account is not None:
            identity_verification = (
                1.0
                if user_account.email_verified_at is not None
                else (0.6 if user_account.phone_verified_at is not None else 0.3)
            )
        verification_parts = [
            (identity_verification, 0.20),
            (1.0 if buyer_need.company_verified else 0.0, 0.25),
            (1.0 if buyer_need.business_email_verified else 0.0, 0.20),
            (min(max(float(profile.completeness_score) / 100.0, 0.0), 1.0), 0.20),
        ]
        present_verification = [
            (value, weight) for value, weight in verification_parts if value is not None
        ]
        verification_weight = sum(weight for _, weight in present_verification)
        raw_context["buyer_verification"] = (
            sum(float(value) * weight for value, weight in present_verification)
            / verification_weight
        )
        raw_context["decision_timeline"] = buyer_need.decision_timeline

        readiness_signals = (
            bool(extra.get("meeting_topic")),
            bool(buckets["categories"]),
            (
                buyer_need.monthly_units_min is not None
                or buyer_need.monthly_units_max is not None
            ),
            buyer_need.decision_timeline is not None,
            visit_session is not None,
        )
        raw_context["meeting_readiness"] = sum(readiness_signals) / len(
            readiness_signals
        )

    latest_version = (
        await db.execute(
            select(ProfileVersion)
            .where(ProfileVersion.profile_id == profile.profile_id)
            .order_by(ProfileVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return ResolvedProfile(
        profile_id=profile.profile_id,
        profile_version=profile.current_version,
        profile_version_id=latest_version.profile_version_id
        if latest_version is not None
        else None,
        user_type=profile.user_type,
        completeness=float(profile.completeness_score),
        goals=goals,
        categories=buckets["categories"],
        channels=buckets["channels"],
        regions=buckets["regions"],
        taste=buckets["taste"],
        aroma=buckets["aroma"],
        extra=extra,
        numeric_conditions=numeric_conditions,
        raw_context=raw_context,
    )

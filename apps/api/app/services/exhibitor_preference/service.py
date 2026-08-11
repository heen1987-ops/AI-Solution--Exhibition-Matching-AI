"""``app/models/exhibitor_preference.py``를 기존 exhibition 도메인 테이블과 합성하는 서비스.

이 트랙(WAVE2C BACKEND-EXHIBITOR-PREFERENCE)이 실제로 저장하는 것은 두 테이블뿐이다
(``ExhibitorTradeAvailability``, ``ExhibitorPreferredCooperationType`` - 모델 모듈 docstring
참고). 나머지 "공개 거래조건"·"희망 바이어" 필드는 이미 다른 트랙이 구현·소유한 저장소
(``exhibitor.TradeCondition``/``TradeConditionTerm``/``ExhibitorBuyerPreference``)를 읽기
전용으로 조회해 합성한다. 이 파일이 그 조합 로직의 유일한 위치다 - 라우터는 이 함수들만
호출해야 하고 직접 다른 도메인 테이블에 쿼리를 새로 짜면 안 된다(합성 규칙이 두 곳에
흩어지는 것을 막기 위함).

멀티에이전트 안전 관행 메모
----------------------------
``app/models/exhibitor.py``를 여기서 import한다 - 모델 모듈끼리는 서로 import하지 않는다는
관행이 있지만, 그건 "동시에 같은 파일을 여러 에이전트가 고치는 위험"을 줄이기 위한 것이고
서비스 계층에서 이미 병합이 끝난 모델을 읽기 전용으로 참조하는 것은 그 위험에 해당하지
않는다(``app/api/v1/routers/partner.py``가 이미 동일하게 exhibitor.py를 import하는 선례를
따른다).

공개 승인 게이트 (통합 MERGE STEP 16 (c))
-------------------------------------------
``GET /exhibitor-preference/{exhibitor_id}``는 인증 없이 열려 있다. 통합 전 이 합성 뷰는
업체 자신의 승인상태를 전혀 보지 않았고(라우터의 ``_get_exhibitor_or_404``는 ``deleted_at``
만 확인한다), ``ExhibitorTradeAvailability.approval_status``도 무시했다 - 그런데
:func:`upsert_trade_availability`는 선언을 수정할 때마다 그 값을 DRAFT로 되돌린다. 결과적으로
미검수 상태의 신규거래/상담가능 선언이 즉시 익명 공개면에 실렸고, 이는 "미승인·미공개 업체
데이터는 공개 검색/추천/키오스크에 도달하지 않는다"는 제품 불변식 위반이다.

그래서 이 모듈이 만드는 공개 뷰는 두 겹으로 막는다.

1. 업체 자체가 ``Exhibitor.master_approval_status == 'APPROVED'``가 아니면 전체 뷰를
   억제한다(모든 값 UNKNOWN, 목록 비움).
2. 업체가 승인됐더라도 ``ExhibitorTradeAvailability.approval_status``가 APPROVED가 아니면
   그 선언만 UNKNOWN으로 억제한다.

억제는 삭제가 아니라 "미선언(UNKNOWN)"으로 떨어뜨리는 방식이다 -
``app/services/buyer_match/compare.py``의 :func:`build_compare_row`가 승인되지 않은 업체를
``available=False`` + 전 필드 UNKNOWN으로 돌려주는 것과 동일한 관례이며, UNKNOWN이 암묵적으로
YES/NO로 치환되지 않는다는 스키마 계약과도 맞는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from functools import lru_cache

from meet_ai.ontology import Catalog, load_catalog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import (
    Exhibitor,
    ExhibitorBuyerPreference,
    ExhibitorParticipation,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.exhibitor_preference import (
    ExhibitorPreferredCooperationType,
    ExhibitorTradeAvailability,
)
from app.models.ontology_refs import concept as ontology_concept_table
from app.schemas.exhibitor_preference import (
    ExhibitorBuyerPreferenceSummaryRead,
    ExhibitorPreferenceRead,
    ExhibitorPublicTradePreferenceRead,
    MinOrderScale,
    TaxonomyRef,
)


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    """프로세스당 1회 로드. ``services/matching/ontology_support.py``와 동일한 전략이지만
    다른 트랙 소유 모듈을 import하지 않기 위해 독립적으로 캐시한다(둘 다 순수 함수인
    ``load_catalog()``를 감싸므로 결과는 항상 같다)."""

    return load_catalog()


async def _resolve_codes(
    db: AsyncSession, concept_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """ontology.concept에서 concept_id -> concept_code 일괄 조회.

    exhibitor_preference/exhibitor.py 양쪽 모두 (taxonomy_version_id, concept_id) 복합
    FK만 갖고 코드 문자열 캐시를 두지 않으므로 이 역해석이 필요하다.
    """

    ids = {c for c in concept_ids if c is not None}
    if not ids:
        return {}
    stmt = select(
        ontology_concept_table.c.concept_id, ontology_concept_table.c.concept_code
    ).where(ontology_concept_table.c.concept_id.in_(ids))
    result = await db.execute(stmt)
    return {row.concept_id: row.concept_code for row in result}


def _validate_concept_type(
    refs: Sequence[TaxonomyRef],
    codes_by_concept: dict[uuid.UUID, str],
    *,
    expected_concept_type: str,
) -> None:
    """참조된 코드가 (a) 실제 카탈로그에 존재하고 (b) 기대한 concept_type인지 검증한다.

    DB의 (taxonomy_version_id, concept_id) 복합 FK는 "온톨로지에 존재하는 개념인가"만
    보장하고 "그 개념이 이 필드에 맞는 종류인가"는 보장하지 않는다(예: REGION 코드를
    cooperation_types에 잘못 넣는 실수) - 그래서 애플리케이션 계층에서 259개 카탈로그의
    concept_type을 추가로 검증한다.
    """

    catalog = _catalog()
    for ref in refs:
        code = codes_by_concept.get(ref.concept_id)
        if code is None:
            raise ValueError(f"UNKNOWN_ONTOLOGY_CONCEPT:{ref.concept_id}")
        try:
            concept_type = str(catalog.get(code)["concept_type"])
        except KeyError as exc:
            raise ValueError(f"UNKNOWN_ONTOLOGY_CONCEPT:{code}") from exc
        if concept_type != expected_concept_type:
            raise ValueError(
                f"UNEXPECTED_CONCEPT_TYPE:{code}:{concept_type}!={expected_concept_type}"
            )


# ---------------------------------------------------------------------------
# 쓰기: 이 트랙이 실제로 소유하는 두 저장소만.
# ---------------------------------------------------------------------------


async def upsert_trade_availability(
    db: AsyncSession,
    exhibitor_id: uuid.UUID,
    *,
    new_trade_available: str | None = None,
    meeting_available: str | None = None,
) -> ExhibitorTradeAvailability:
    """부분수정(partial update) - None인 필드는 기존 값을 그대로 둔다.

    스키마 docstring(``ExhibitorTradeAvailabilityUpdate``) 참고: "미제공"과 "UNKNOWN으로
    설정"을 구분하는 것이 "UNKNOWN이 암묵적으로 YES/NO로 치환되지 않는다"는 요구사항의
    핵심이다.
    """

    stmt = select(ExhibitorTradeAvailability).where(
        ExhibitorTradeAvailability.exhibitor_id == exhibitor_id
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        # 컬럼 기본값(UNKNOWN)은 실제 flush 시점에야 적용되므로, 커밋 전에도 이 함수가
        # 반환하는 객체가 즉시 올바른 값을 갖도록 여기서도 명시한다.
        row = ExhibitorTradeAvailability(
            exhibitor_id=exhibitor_id,
            new_trade_available="UNKNOWN",
            meeting_available="UNKNOWN",
            approval_status="DRAFT",
        )
        db.add(row)

    changed = False
    if new_trade_available is not None and new_trade_available != row.new_trade_available:
        row.new_trade_available = new_trade_available
        changed = True
    if meeting_available is not None and meeting_available != row.meeting_available:
        row.meeting_available = meeting_available
        changed = True

    # exhibitor.py 여러 곳(ExhibitorProfile.approval_status 등)의 관례와 동일: 공개 선언을
    # 고치면 재검수가 필요하므로 승인상태를 되돌린다.
    if changed and row.approval_status in ("APPROVED", "REJECTED"):
        row.approval_status = "DRAFT"

    await db.commit()
    await db.refresh(row)
    return row


async def replace_cooperation_types(
    db: AsyncSession,
    exhibitor_id: uuid.UUID,
    refs: Sequence[TaxonomyRef],
) -> list[ExhibitorPreferredCooperationType]:
    """협력유형 선호를 전체 교체한다 (TRADE_TYPE 온톨로지만 허용).

    하드 삭제 대신 ``active`` 플래그로 소프트 삭제한다(모델 docstring 참고) - 기존
    exhibitor.py의 "active" 플래그 관례(ExhibitorBuyerPreference.active,
    ExhibitorStaff.active)와 맞춘 것이며, 감사 추적을 남긴다.
    """

    codes_by_concept = await _resolve_codes(db, [ref.concept_id for ref in refs])
    _validate_concept_type(refs, codes_by_concept, expected_concept_type="TRADE_TYPE")

    existing_stmt = select(ExhibitorPreferredCooperationType).where(
        ExhibitorPreferredCooperationType.exhibitor_id == exhibitor_id
    )
    existing_rows = list((await db.execute(existing_stmt)).scalars().all())
    existing_by_concept = {row.concept_id: row for row in existing_rows}
    requested_concepts = {ref.concept_id for ref in refs}

    for row in existing_rows:
        if row.concept_id not in requested_concepts and row.active:
            row.active = False

    result_rows: list[ExhibitorPreferredCooperationType] = []
    for ref in refs:
        row = existing_by_concept.get(ref.concept_id)
        if row is not None:
            row.active = True
            row.taxonomy_version_id = ref.taxonomy_version_id
            result_rows.append(row)
            continue
        row = ExhibitorPreferredCooperationType(
            exhibitor_id=exhibitor_id,
            taxonomy_version_id=ref.taxonomy_version_id,
            concept_id=ref.concept_id,
            active=True,
        )
        db.add(row)
        result_rows.append(row)

    await db.commit()
    for row in result_rows:
        await db.refresh(row)
    return result_rows


# ---------------------------------------------------------------------------
# 읽기: 기존 저장소를 조회해 합성한다.
# ---------------------------------------------------------------------------


def _common_trade_condition_stmt(exhibitor_id: uuid.UUID):
    """업체 공통조건(참가 단위, event_product_id IS NULL) 중 승인된 것만, 최신순으로 하나.

    "미승인/미공개 업체 데이터는 공개 결과에 노출되지 않는다"를 만족하기 위해
    approval_status='APPROVED'만 채택한다 - candidate_generator.py(매칭 파이프라인)는
    승인 여부를 걸지 않지만(그 트랙 책임 범위), 이 함수가 만드는 "공개" 뷰는 별도로
    더 엄격한 기준을 적용한다.

    statement 생성만 분리해 두는 이유는 ``catalog_search._candidate_pool_stmt``와 동일한
    관례를 따르기 위함이다 - 라이브 DB 없이도 ``.compile(compile_kwargs={"literal_binds":
    True})``로 WHERE 절을 검증할 수 있다(test_exhibitor_preference_api.py 참고).
    """

    return (
        select(TradeCondition)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == TradeCondition.participation_id,
        )
        .where(
            ExhibitorParticipation.exhibitor_id == exhibitor_id,
            TradeCondition.event_product_id.is_(None),
            TradeCondition.approval_status == "APPROVED",
        )
        .order_by(TradeCondition.updated_at.desc())
        .limit(1)
    )


async def _load_common_trade_condition(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> TradeCondition | None:
    stmt = _common_trade_condition_stmt(exhibitor_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_public_trade_preference(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> ExhibitorPublicTradePreferenceRead:
    availability_stmt = select(ExhibitorTradeAvailability).where(
        ExhibitorTradeAvailability.exhibitor_id == exhibitor_id
    )
    availability = (await db.execute(availability_stmt)).scalar_one_or_none()
    # MERGE STEP 16 (c): 선언 자체가 승인되지 않았으면 공개 뷰에서는 미선언과 같이 다룬다.
    # upsert_trade_availability()가 수정 시마다 approval_status를 DRAFT로 되돌리므로, 이
    # 확인이 없으면 "수정 직후 ~ 재검수 전" 구간의 값이 그대로 익명 공개면에 실린다.
    availability_published = (
        availability is not None and availability.approval_status == "APPROVED"
    )
    new_trade_available = (
        availability.new_trade_available if availability_published else "UNKNOWN"
    )
    meeting_available = (
        availability.meeting_available if availability_published else "UNKNOWN"
    )

    common_condition = await _load_common_trade_condition(db, exhibitor_id)
    if common_condition is None:
        return ExhibitorPublicTradePreferenceRead(
            exhibitor_id=exhibitor_id,
            new_trade_available=new_trade_available,  # type: ignore[arg-type]
            oem_available="UNKNOWN",
            pb_available="UNKNOWN",
            export_available="UNKNOWN",
            meeting_available=meeting_available,  # type: ignore[arg-type]
            distribution_channel_codes=[],
            supply_region_codes=[],
            moq=None,
            expected_lead_time_days=None,
            source_trade_condition_approved=False,
        )

    terms_stmt = select(TradeConditionTerm).where(
        TradeConditionTerm.trade_condition_id == common_condition.trade_condition_id
    )
    terms = list((await db.execute(terms_stmt)).scalars().all())
    codes_by_concept = await _resolve_codes(db, [t.concept_id for t in terms])

    channel_codes: list[str] = []
    region_codes: list[str] = []
    for term in terms:
        code = codes_by_concept.get(term.concept_id)
        if code is None:
            continue
        if term.term_type == "CHANNEL" and code not in channel_codes:
            channel_codes.append(code)
        elif term.term_type == "REGION" and code not in region_codes:
            region_codes.append(code)

    return ExhibitorPublicTradePreferenceRead(
        exhibitor_id=exhibitor_id,
        new_trade_available=new_trade_available,  # type: ignore[arg-type]
        oem_available=common_condition.oem_status,  # type: ignore[arg-type]
        pb_available=common_condition.private_label_status,  # type: ignore[arg-type]
        export_available=common_condition.export_status,  # type: ignore[arg-type]
        meeting_available=meeting_available,  # type: ignore[arg-type]
        distribution_channel_codes=channel_codes,
        supply_region_codes=region_codes,
        moq=common_condition.min_order_quantity,
        expected_lead_time_days=common_condition.lead_time_days,
        source_trade_condition_approved=True,
    )


async def _load_buyer_preference_summary(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> ExhibitorBuyerPreferenceSummaryRead:
    buyer_pref_stmt = select(ExhibitorBuyerPreference).where(
        ExhibitorBuyerPreference.exhibitor_id == exhibitor_id,
        ExhibitorBuyerPreference.active.is_(True),
    )
    buyer_prefs = list((await db.execute(buyer_pref_stmt)).scalars().all())

    concept_ids: list[uuid.UUID | None] = []
    for row in buyer_prefs:
        concept_ids.extend(
            [row.buyer_type_concept_id, row.channel_concept_id, row.region_concept_id]
        )
    codes_by_concept = await _resolve_codes(db, concept_ids)

    preferred_buyer_types: list[str] = []
    preferred_channels: list[str] = []
    preferred_regions: list[str] = []
    volume_mins: list[int] = []
    volume_maxs: list[int] = []
    for row in buyer_prefs:
        code = codes_by_concept.get(row.buyer_type_concept_id) if row.buyer_type_concept_id else None
        if code and code not in preferred_buyer_types:
            preferred_buyer_types.append(code)
        code = codes_by_concept.get(row.channel_concept_id) if row.channel_concept_id else None
        if code and code not in preferred_channels:
            preferred_channels.append(code)
        code = codes_by_concept.get(row.region_concept_id) if row.region_concept_id else None
        if code and code not in preferred_regions:
            preferred_regions.append(code)
        if row.volume_min is not None:
            volume_mins.append(row.volume_min)
        if row.volume_max is not None:
            volume_maxs.append(row.volume_max)

    cooperation_stmt = select(ExhibitorPreferredCooperationType).where(
        ExhibitorPreferredCooperationType.exhibitor_id == exhibitor_id,
        ExhibitorPreferredCooperationType.active.is_(True),
    )
    cooperation_rows = list((await db.execute(cooperation_stmt)).scalars().all())
    cooperation_codes_by_concept = await _resolve_codes(
        db, [row.concept_id for row in cooperation_rows]
    )
    cooperation_types = [
        cooperation_codes_by_concept[row.concept_id]
        for row in cooperation_rows
        if row.concept_id in cooperation_codes_by_concept
    ]

    return ExhibitorBuyerPreferenceSummaryRead(
        preferred_buyer_types=preferred_buyer_types,
        preferred_channels=preferred_channels,
        preferred_regions=preferred_regions,
        min_order_scale=MinOrderScale(
            min=min(volume_mins) if volume_mins else None,
            max=max(volume_maxs) if volume_maxs else None,
        ),
        cooperation_types=cooperation_types,
        has_buyer_preference=bool(buyer_prefs) or bool(cooperation_rows),
    )


def exhibitor_master_approved_stmt(exhibitor_id: uuid.UUID):
    """공개 뷰가 요구하는 업체 승인 조건을 담은 statement.

    ``_common_trade_condition_stmt``와 같은 이유로 statement 생성만 분리해 둔다 - 라이브
    DB 없이 ``.compile(compile_kwargs={"literal_binds": True})``로 WHERE 절을 검증할 수
    있게 하기 위함이다.
    """

    return select(Exhibitor.exhibitor_id).where(
        Exhibitor.exhibitor_id == exhibitor_id,
        Exhibitor.deleted_at.is_(None),
        Exhibitor.master_approval_status == "APPROVED",
    )


async def is_publicly_visible(db: AsyncSession, exhibitor_id: uuid.UUID) -> bool:
    """업체 자체가 공개 가능한 승인 상태인지(MERGE STEP 16 (c) 1단계)."""

    row = (await db.execute(exhibitor_master_approved_stmt(exhibitor_id))).first()
    return row is not None


def _suppressed_preference_view(exhibitor_id: uuid.UUID) -> ExhibitorPreferenceRead:
    """미승인 업체용 전면 억제 뷰 - compare.py의 ``available=False`` 행과 같은 모양."""

    return ExhibitorPreferenceRead(
        exhibitor_id=exhibitor_id,
        trade=ExhibitorPublicTradePreferenceRead(
            exhibitor_id=exhibitor_id,
            new_trade_available="UNKNOWN",
            oem_available="UNKNOWN",
            pb_available="UNKNOWN",
            export_available="UNKNOWN",
            meeting_available="UNKNOWN",
            distribution_channel_codes=[],
            supply_region_codes=[],
            moq=None,
            expected_lead_time_days=None,
            source_trade_condition_approved=False,
        ),
        buyer_preference=ExhibitorBuyerPreferenceSummaryRead(
            preferred_buyer_types=[],
            preferred_channels=[],
            preferred_regions=[],
            min_order_scale=MinOrderScale(min=None, max=None),
            cooperation_types=[],
            has_buyer_preference=False,
        ),
    )


async def get_exhibitor_preference_view(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> ExhibitorPreferenceRead:
    """GET /exhibitor-preference/{exhibitor_id}가 반환할 전체 합성 뷰.

    업체가 ``master_approval_status='APPROVED'``가 아니면 아무것도 조회하지 않고 전면
    억제된 뷰를 돌려준다(모듈 docstring "공개 승인 게이트" 참고).
    """

    if not await is_publicly_visible(db, exhibitor_id):
        return _suppressed_preference_view(exhibitor_id)

    trade = await _load_public_trade_preference(db, exhibitor_id)
    buyer_preference = await _load_buyer_preference_summary(db, exhibitor_id)
    return ExhibitorPreferenceRead(
        exhibitor_id=exhibitor_id, trade=trade, buyer_preference=buyer_preference
    )


async def has_buyer_preference(db: AsyncSession, exhibitor_id: uuid.UUID) -> bool:
    """AI-BUYER-MATCH 트랙용 저비용 헬퍼 - 전체 뷰를 조립하지 않고 존재 여부만 확인한다.

    false는 "선호 없음"이 아니라 "미선언"이다. 호출자는 이 값을 감점 신호로 쓰지 말고
    (PROJECT_SCOPE 규칙: "누락된 업체 희망 바이어 조건을 감점으로 취급하지 않는다"),
    한쪽 방향(바이어->업체) 점수만으로 폴백해야 한다.
    """

    buyer_pref_count = (
        await db.execute(
            select(func.count(ExhibitorBuyerPreference.exhibitor_buyer_preference_id)).where(
                ExhibitorBuyerPreference.exhibitor_id == exhibitor_id,
                ExhibitorBuyerPreference.active.is_(True),
            )
        )
    ).scalar_one()
    if buyer_pref_count > 0:
        return True

    cooperation_count = (
        await db.execute(
            select(
                func.count(ExhibitorPreferredCooperationType.exhibitor_cooperation_type_id)
            ).where(
                ExhibitorPreferredCooperationType.exhibitor_id == exhibitor_id,
                ExhibitorPreferredCooperationType.active.is_(True),
            )
        )
    ).scalar_one()
    return cooperation_count > 0

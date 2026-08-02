"""InterpretedQuery -> list[SearchCandidate] 키워드 검색기.

두 계층으로 나뉜다.

1. 순수 스코어링(``score_candidate``) - 온톨로지 카탈로그와 후보의 개념 코드 집합만으로
   동작하는 순수 함수다. DB도, apps/api도 몰라야 한다 - ``ai/tests/``에서 실제 Postgres 없이
   단위 테스트할 수 있는 부분은 이 함수뿐이다.
2. DB 조회 오케스트레이션(``retrieve``) - 실제 exhibition 스키마(apps/api/app/models/exhibitor.py,
   matching.py의 Recommendable 레지스트리)에 대해 SQLAlchemy 쿼리를 만든다. 임무 지시대로 DB
   세션은 인자로만 받는다(``db: AsyncSession`` 매개변수) - 이 모듈이 직접 세션/엔진을 만들지
   않는다. 다른 트랙(BACKEND-008의 POST /search 라우터)이 자신의 세션을 주입해 호출한다.

승인 규칙(AGENTS.md 절대 규칙: "미승인 업체/제품은 공개 API·검색·추천 어디에도 노출하지
않는다")은 ``retrieve``가 항상 무조건 강제한다 - ``AccessScope``에 이를 끌 수 있는 필드를
두지 않았다(ai/types.py 참고).

이 파일이 아직 다루지 못한 것 (TODO, 후속 트랙 작업 필요):
    - BOOTH_SERVICE 개념은 부스 자체의 정규화 테이블이 아직 없어(도메인 모델에 booth_service
      정규화 테이블 미확인) EventProduct.tasting_status/purchase_status +
      ExhibitorParticipation.consultation_enabled로부터 근사한다(``_booth_service_codes``).
      전용 정규화 테이블이 추가되면 이 근사를 대체해야 한다.
    - 벡터 검색은 이 모듈의 책임이 아니다(candidate_generator.py의 ``_vector_search_candidates``와
      동일한 경계) - 하이브리드 결합은 BACKEND-008 라우터가 KeywordRetriever 결과와 별도
      벡터 채널 결과를 합쳐서 한다.
    - PostgreSQL FTS(ts_vector/ts_query)는 아직 안 쓴다. candidate_text에 대한 단순 토큰
      포함 비율(``_text_overlap_score``)로 대신한다 - BACKEND-008이 실제 FTS 인덱스를 붙이면
      이 함수만 교체하면 된다(다른 모든 로직은 그대로).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from meet_ai.ontology import Catalog
from meet_ai.ontology.catalog import normalize_text

from ai.types import AccessScope, InterpretedQuery, SearchCandidate

# 구조화 검색과 동일한 철학(docs/05-ai-matching-engine-architecture.md 5.4절): 이 단계는
# 재현율 확보가 목적이므로 넉넉히 가져온 뒤 파이썬에서 스코어링·필터링한다.
_RAW_FETCH_CAP = 500


# ---------------------------------------------------------------------------
# 1. 순수 스코어링. DB·apps.api에 의존하지 않는다.
# ---------------------------------------------------------------------------


def _max_match_strength(catalog: Catalog, requested: Iterable[str], offered: Iterable[str]) -> float:
    """두 코드 집합 사이의 최대 일치도(조상 관계 감쇠 포함).

    apps/api/app/services/matching/ontology_support.py의 ``max_match_strength``와 동일한
    로직이다. 이 파일(순수 스코어링 계층)이 apps/api 내부 모듈에 의존하지 않도록 여기서
    ``Catalog.match_strength`` 위에 다시 얇게 얹었다(공개 API인 Catalog.match_strength만
    사용하므로 중복이라기보다 동일 공개 계약의 재구현에 가깝다).
    """

    requested_list = [code for code in requested if code]
    offered_list = [code for code in offered if code]
    if not requested_list or not offered_list:
        return 0.0
    best = 0.0
    for req in requested_list:
        for off in offered_list:
            try:
                score = float(catalog.match_strength(req, off))
            except KeyError:
                continue
            if score > best:
                best = score
    return best


def _group_by_concept_type(catalog: Catalog, codes: Sequence[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for code in codes:
        concept = catalog.by_code.get(code)
        if concept is None:
            continue
        groups.setdefault(str(concept.get("concept_type", "")), []).append(code)
    return groups


def _text_overlap_score(candidate_text: str, normalized_query: str) -> float:
    candidate_normalized = normalize_text(candidate_text or "")
    if not candidate_normalized or not normalized_query:
        return 0.0
    tokens = [token for token in normalized_query.split(" ") if token]
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in candidate_normalized)
    return hits / len(tokens)


@dataclass(frozen=True)
class ScoreResult:
    eligible: bool
    required_hit_count: int
    preferred_hit_count: int
    text_match_score: float
    matched_concept_codes: tuple[str, ...]
    keyword_score: float

    @staticmethod
    def rejected() -> ScoreResult:
        return ScoreResult(False, 0, 0, 0.0, (), 0.0)


def score_candidate(
    catalog: Catalog,
    candidate_concept_codes: Iterable[str],
    candidate_text: str,
    interpreted: InterpretedQuery,
) -> ScoreResult:
    """후보 하나를 InterpretedQuery에 대해 채점한다. DB를 전혀 모르는 순수 함수.

    필수조건(``required_concepts``)은 개념유형별로 묶어, 같은 유형 안에서는 하나라도
    겹치면 통과(OR), 서로 다른 유형끼리는 전부 통과해야 한다(AND) -
    apps/api/app/services/matching/hard_filter.py의 지역/채널 불일치 판정과 동일한 규칙이다
    (예: "REGION.KR.SEOUL 또는 REGION.KR.GYEONGGI 둘 중 하나만 맞아도 지역조건은 통과"하되
    "지역조건과 채널조건은 둘 다 통과해야 한다").

    배제조건(``excluded_concepts``)은 하나라도 겹치면 후보 전체를 탈락시킨다(조상 관계 포함
    - "탁주 말고"는 ALCOHOL.TAKJU의 하위 개념도 함께 배제한다).
    """

    candidate_codes = set(candidate_concept_codes)

    if interpreted.excluded_concepts and _max_match_strength(
        catalog, interpreted.excluded_concepts, candidate_codes
    ) > 0:
        return ScoreResult.rejected()

    matched: set[str] = set()
    required_groups = _group_by_concept_type(catalog, interpreted.required_concepts)
    for group_codes in required_groups.values():
        if _max_match_strength(catalog, group_codes, candidate_codes) <= 0:
            return ScoreResult.rejected()
        for code in group_codes:
            if _max_match_strength(catalog, [code], candidate_codes) > 0:
                matched.add(code)

    preferred_hits = 0
    for code in interpreted.preferred_concepts:
        if _max_match_strength(catalog, [code], candidate_codes) > 0:
            preferred_hits += 1
            matched.add(code)

    text_score = _text_overlap_score(candidate_text, interpreted.normalized_query)
    required_hits = len(matched & set(interpreted.required_concepts))
    keyword_score = required_hits * 1.0 + preferred_hits * 0.4 + text_score * 0.2

    return ScoreResult(
        eligible=True,
        required_hit_count=required_hits,
        preferred_hit_count=preferred_hits,
        text_match_score=text_score,
        matched_concept_codes=tuple(sorted(matched)),
        keyword_score=keyword_score,
    )


# ---------------------------------------------------------------------------
# 2. DB 조회 오케스트레이션. apps/api의 실제 스키마(SQLAlchemy 모델)에 의존한다.
#    임무 지시: "DB 세션은 인자로 주입받게 설계해라" - 이 아래 함수들은 세션을 만들지 않고
#    전부 인자로만 받는다.
# ---------------------------------------------------------------------------


async def retrieve(
    db: object,
    interpreted_query: InterpretedQuery,
    access_scope: AccessScope,
    limit: int = 20,
) -> list[SearchCandidate]:
    """InterpretedQuery + AccessScope -> 순위가 매겨진 SearchCandidate 목록.

    ``db``는 ``sqlalchemy.ext.asyncio.AsyncSession``을 기대한다(타입힌트를 ``object``로 둔
    이유는 apps/api 모델 임포트를 지연시키기 위함이 아니라 - 아래에서 바로 임포트한다 -
    이 시그니처 자체는 어떤 비동기 세션 구현체든 받을 수 있음을 드러내기 위해서다).
    """

    from sqlalchemy.ext.asyncio import AsyncSession

    if not isinstance(db, AsyncSession):
        raise TypeError("db must be a sqlalchemy.ext.asyncio.AsyncSession instance")

    from app.services.matching.ontology_support import get_catalog

    catalog = get_catalog()
    target_types = interpreted_query.target_types or ("EXHIBITOR", "PRODUCT", "BOOTH")

    candidates: list[SearchCandidate] = []
    if "EXHIBITOR" in target_types:
        candidates.extend(
            await _retrieve_exhibitor_candidates(db, catalog, interpreted_query, access_scope)
        )
    if "PRODUCT" in target_types:
        candidates.extend(
            await _retrieve_product_candidates(db, catalog, interpreted_query, access_scope)
        )
    if "BOOTH" in target_types:
        candidates.extend(
            await _retrieve_booth_candidates(db, catalog, interpreted_query, access_scope)
        )

    candidates.sort(key=lambda candidate: candidate.keyword_score, reverse=True)
    return candidates[: max(limit, 0)]


async def _retrieve_exhibitor_candidates(
    db: object,
    catalog: Catalog,
    interpreted_query: InterpretedQuery,
    access_scope: AccessScope,
) -> list[SearchCandidate]:
    from sqlalchemy import select

    from app.models.exhibitor import Exhibitor, ExhibitorBusinessType, ExhibitorParticipation
    from app.models.matching import Recommendable
    from app.services.matching.ontology_support import resolve_concept_codes

    stmt = (
        select(
            ExhibitorParticipation.participation_id,
            ExhibitorParticipation.exhibitor_id,
            Exhibitor.company_name,
            Exhibitor.company_summary,
        )
        .join(
            Recommendable,
            Recommendable.participation_id == ExhibitorParticipation.participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Recommendable.tenant_id == access_scope.tenant_id,
            Recommendable.event_id == access_scope.event_id,
            Recommendable.active.is_(True),
            # AGENTS.md 절대 규칙: 미승인 업체는 검색 어디에도 노출하지 않는다.
            Exhibitor.master_approval_status == "APPROVED",
            ExhibitorParticipation.participation_status == "APPROVED",
        )
        .limit(_RAW_FETCH_CAP)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    exhibitor_ids = [row.exhibitor_id for row in rows]
    business_type_rows = (
        await db.execute(
            select(
                ExhibitorBusinessType.exhibitor_id, ExhibitorBusinessType.concept_id
            ).where(ExhibitorBusinessType.exhibitor_id.in_(exhibitor_ids))
        )
    ).all()
    concept_code_by_id = await resolve_concept_codes(
        db, [row.concept_id for row in business_type_rows]
    )
    codes_by_exhibitor: dict[uuid.UUID, set[str]] = {}
    for row in business_type_rows:
        code = concept_code_by_id.get(row.concept_id)
        if code:
            codes_by_exhibitor.setdefault(row.exhibitor_id, set()).add(code)

    results: list[SearchCandidate] = []
    for row in rows:
        codes = codes_by_exhibitor.get(row.exhibitor_id, set())
        text = f"{row.company_name} {row.company_summary or ''}"
        score = score_candidate(catalog, codes, text, interpreted_query)
        if not score.eligible:
            continue
        results.append(
            SearchCandidate(
                object_type="EXHIBITOR",
                object_id=row.exhibitor_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                booth_id=None,
                display_name=row.company_name,
                summary=row.company_summary,
                matched_concept_codes=score.matched_concept_codes,
                required_hit_count=score.required_hit_count,
                preferred_hit_count=score.preferred_hit_count,
                text_match_score=score.text_match_score,
                keyword_score=score.keyword_score,
            )
        )
    return results


async def _retrieve_product_candidates(
    db: object,
    catalog: Catalog,
    interpreted_query: InterpretedQuery,
    access_scope: AccessScope,
) -> list[SearchCandidate]:
    from sqlalchemy import select

    from app.models.exhibitor import (
        EventProduct,
        Exhibitor,
        ExhibitorParticipation,
        Product,
        ProductAttribute,
        ProductProfile,
    )
    from app.models.matching import Recommendable
    from app.services.matching.ontology_support import resolve_concept_codes

    stmt = (
        select(
            EventProduct.event_product_id,
            EventProduct.participation_id,
            ExhibitorParticipation.exhibitor_id,
            Product.product_id,
            Product.product_name,
            Product.product_summary,
            ProductProfile.category_code,
            ProductProfile.taste_json,
            ProductProfile.aroma_json,
            ProductProfile.usage_json,
            ProductProfile.feature_json,
        )
        .join(Recommendable, Recommendable.event_product_id == EventProduct.event_product_id)
        .join(Product, Product.product_id == EventProduct.product_id)
        .outerjoin(ProductProfile, ProductProfile.product_id == Product.product_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == EventProduct.participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Recommendable.tenant_id == access_scope.tenant_id,
            Recommendable.event_id == access_scope.event_id,
            Recommendable.active.is_(True),
            # AGENTS.md 절대 규칙: 미승인 업체/제품은 검색 어디에도 노출하지 않는다.
            Exhibitor.master_approval_status == "APPROVED",
            ExhibitorParticipation.participation_status == "APPROVED",
            Product.master_approval_status == "APPROVED",
            EventProduct.approval_status == "APPROVED",
        )
        .limit(_RAW_FETCH_CAP)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    product_ids = [row.product_id for row in rows]
    attribute_rows = (
        await db.execute(
            select(ProductAttribute.product_id, ProductAttribute.concept_id).where(
                ProductAttribute.product_id.in_(product_ids),
                # 08 문서 24절: 검수 전 AI 추출 속성은 검색근거로 쓰지 않는다.
                ProductAttribute.review_status == "APPROVED",
            )
        )
    ).all()
    concept_code_by_id = await resolve_concept_codes(
        db, [row.concept_id for row in attribute_rows]
    )
    attribute_codes_by_product: dict[uuid.UUID, set[str]] = {}
    for row in attribute_rows:
        code = concept_code_by_id.get(row.concept_id)
        if code:
            attribute_codes_by_product.setdefault(row.product_id, set()).add(code)

    results: list[SearchCandidate] = []
    for row in rows:
        codes: set[str] = set(attribute_codes_by_product.get(row.product_id, set()))
        if row.category_code:
            codes.add(row.category_code)
        codes.update((row.taste_json or {}).keys())
        codes.update((row.aroma_json or {}).keys())
        codes.update(row.usage_json or [])
        codes.update(row.feature_json or [])

        text = f"{row.product_name} {row.product_summary or ''}"
        score = score_candidate(catalog, codes, text, interpreted_query)
        if not score.eligible:
            continue
        results.append(
            SearchCandidate(
                object_type="PRODUCT",
                object_id=row.event_product_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                booth_id=None,
                display_name=row.product_name,
                summary=row.product_summary,
                matched_concept_codes=score.matched_concept_codes,
                required_hit_count=score.required_hit_count,
                preferred_hit_count=score.preferred_hit_count,
                text_match_score=score.text_match_score,
                keyword_score=score.keyword_score,
            )
        )
    return results


async def _retrieve_booth_candidates(
    db: object,
    catalog: Catalog,
    interpreted_query: InterpretedQuery,
    access_scope: AccessScope,
) -> list[SearchCandidate]:
    from sqlalchemy import select

    from app.models.exhibitor import Booth, EventProduct, Exhibitor, ExhibitorParticipation
    from app.models.matching import Recommendable

    stmt = (
        select(
            Booth.booth_id,
            Booth.booth_number,
            Booth.participation_id,
            ExhibitorParticipation.exhibitor_id,
            ExhibitorParticipation.consultation_enabled,
            Exhibitor.company_name,
            Exhibitor.company_summary,
        )
        .join(Recommendable, Recommendable.booth_id == Booth.booth_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Booth.participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Recommendable.tenant_id == access_scope.tenant_id,
            Recommendable.event_id == access_scope.event_id,
            Recommendable.active.is_(True),
            Exhibitor.master_approval_status == "APPROVED",
            ExhibitorParticipation.participation_status == "APPROVED",
            # 08 문서 12.3절: 운영 종료 상태는 현장 추천/검색에서 제외한다.
            Booth.operating_status != "CLOSED",
        )
        .limit(_RAW_FETCH_CAP)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    participation_ids = [row.participation_id for row in rows]
    service_rows = (
        await db.execute(
            select(
                EventProduct.participation_id,
                EventProduct.tasting_status,
                EventProduct.purchase_status,
            ).where(
                EventProduct.participation_id.in_(participation_ids),
                EventProduct.approval_status == "APPROVED",
            )
        )
    ).all()
    services_by_participation: dict[uuid.UUID, set[str]] = {}
    for row in service_rows:
        bucket = services_by_participation.setdefault(row.participation_id, set())
        if row.tasting_status == "AVAILABLE":
            bucket.add("SERVICE.TASTING")
        if row.purchase_status == "AVAILABLE":
            bucket.add("SERVICE.PURCHASE")

    results: list[SearchCandidate] = []
    for row in rows:
        codes = set(services_by_participation.get(row.participation_id, set()))
        if row.consultation_enabled:
            codes.add("SERVICE.CONSULTATION")

        text = f"{row.company_name} {row.booth_number} {row.company_summary or ''}"
        score = score_candidate(catalog, codes, text, interpreted_query)
        if not score.eligible:
            continue
        results.append(
            SearchCandidate(
                object_type="BOOTH",
                object_id=row.booth_id,
                exhibitor_id=row.exhibitor_id,
                participation_id=row.participation_id,
                booth_id=row.booth_id,
                display_name=f"{row.company_name} ({row.booth_number})",
                summary=row.company_summary,
                matched_concept_codes=score.matched_concept_codes,
                required_hit_count=score.required_hit_count,
                preferred_hit_count=score.preferred_hit_count,
                text_match_score=score.text_match_score,
                keyword_score=score.keyword_score,
            )
        )
    return results

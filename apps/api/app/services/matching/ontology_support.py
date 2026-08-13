"""매칭 파이프라인이 공유하는 온톨로지 카탈로그 헬퍼.

6단계(매칭 분류체계·온톨로지) 문서는 작업 지시 시점 기준 아직 확정 세부설계가 없는 것으로
전제했지만, 실제로는 src/meet_ai/ontology/catalog.v1.json(taxonomy_version 1.0.0)이 이미
애플리케이션 산출물로 존재하고 backend/app/api/v1/endpoints/ontology.py가 이를
``GET /api/v1/ontology*``로 공개한다. 매칭엔진이 태그·속성 코드값을 하드코딩 enum으로 들고
있지 않고 이 카탈로그(그리고 DB의 ontology.taxonomy_version/concept/concept_revision 범용
테이블)에서 조회하도록, 이 모듈이 공용 접근점을 제공한다.

카탈로그가 이미 제공하는 것:
    - ``Catalog.get(code)`` - 코드 -> 개념 메타데이터(concept_type 포함).
    - ``Catalog.match_strength(requested, offered)`` - 조상 관계 감쇠를 반영한 코드 간 일치도.
    - ``Catalog.relations`` - MATCHES_GOAL/RELATED_TO/CONFLICTS_WITH 등 개념 간 관계.
    - ``Catalog.derive_band`` - 가격대·도수 구간 코드 산출.

이 모듈은 위 위에 매칭엔진 특화 편의 함수(집합 간 최대 일치도, 관계 기반 목적 일치, DB
concept_id -> concept_code 역해석)만 얹는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal
from functools import lru_cache

from meet_ai.ontology import Catalog, load_catalog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ontology_refs import concept as ontology_concept_table


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """프로세스당 한 번만 로드하는 온톨로지 카탈로그.

    app/api/v1/endpoints/ontology.py의 ``_catalog()``와 동일한 캐싱 전략이다(같은 프로세스
    안에서 로드 비용을 두 번 지불하지 않는다). 두 모듈이 같은 캐시를 공유하지는 않지만
    ``load_catalog()`` 자체가 순수 함수라 결과는 항상 동일하다.
    """

    return load_catalog()


def concept_type_of(catalog: Catalog, code: str) -> str | None:
    """코드의 concept_type을 안전하게 조회한다. 존재하지 않는 코드는 None."""

    try:
        return str(catalog.get(code)["concept_type"])
    except KeyError:
        return None


def max_match_strength(
    catalog: Catalog, requested: Iterable[str], offered: Iterable[str]
) -> float:
    """두 코드 집합 사이의 최대 일치도.

    ``Catalog.match_strength``는 (requested, offered) 코드 하나씩만 비교하므로, 프로파일이
    보유한 코드 목록과 후보가 보유한 코드 목록 사이의 "가장 잘 맞는 쌍"을 찾아야 하는 매칭
    엔진 특성상 이 헬퍼가 필요하다. 둘 중 하나라도 비어 있으면 신호가 없다는 뜻이므로 0.0을
    반환한다(반대편이 있어도 "일치"라고 볼 수 없음 - 데이터 부족과 불일치를 구분하는 것은
    호출자의 책임이다).
    """

    requested_list = list(requested)
    offered_list = list(offered)
    if not requested_list or not offered_list:
        return 0.0
    best = Decimal(0)
    for req in requested_list:
        for off in offered_list:
            try:
                score = catalog.match_strength(req, off)
            except KeyError:
                continue
            best = max(best, score)
    return float(best)


def relation_weight(
    catalog: Catalog,
    sources: Iterable[str],
    relation_type: str,
    targets: Iterable[str],
) -> float:
    """``sources`` 중 하나가 ``relation_type``으로 ``targets`` 중 하나를 가리키는 관계의
    최대 가중치. 예: USE.GIFT --MATCHES_GOAL--> GOAL.GIFT_SEARCH (catalog.v1.json 예시).
    """

    target_set = set(targets)
    if not target_set:
        return 0.0
    best = 0.0
    for relation in catalog.relations:
        if relation.get("type") != relation_type:
            continue
        if relation.get("source") not in set(sources):
            continue
        if relation.get("target") not in target_set:
            continue
        weight = float(relation.get("weight", 0))
        best = max(best, weight)
    return best


async def resolve_concept_codes(
    db: AsyncSession, concept_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """ontology.concept에서 concept_id -> concept_code를 일괄 조회한다.

    exhibition 도메인의 일부 테이블(예: TradeConditionTerm, ExhibitorBuyerPreference)은
    (taxonomy_version_id, concept_id) 복합 FK만 갖고 코드 문자열 캐시를 두지 않으므로,
    매칭엔진이 온톨로지 코드로 비교하려면 이 역해석이 필요하다.
    """

    ids = {c for c in concept_ids if c is not None}
    if not ids:
        return {}
    stmt = select(
        ontology_concept_table.c.concept_id, ontology_concept_table.c.concept_code
    ).where(ontology_concept_table.c.concept_id.in_(ids))
    result = await db.execute(stmt)
    return {row.concept_id: row.concept_code for row in result}

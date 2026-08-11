"""AI-EXTRACTION 전용 온톨로지 카탈로그 헬퍼.

``apps/api/app/services/matching/ontology_support.py``와 같은 캐싱 철학
(프로세스당 1회 로드)이지만, ``ai/**``가 ``apps/api``에 의존하지 않도록(트랙 경계 -
.harness/locks.yaml) 독립적으로 얇게 둔다. 두 모듈 모두 결국
``meet_ai.ontology.load_catalog()``라는 같은 순수 함수를 감쌀 뿐이라 결과는 항상 동일하다.
"""

from __future__ import annotations

from functools import lru_cache

from meet_ai.ontology import Catalog, load_catalog


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()


def is_valid_concept_code(catalog: Catalog, code: str) -> bool:
    return code in catalog.by_code


def concept_label(catalog: Catalog, code: str) -> str | None:
    concept = catalog.by_code.get(code)
    if concept is None:
        return None
    return str(concept.get("label_ko", ""))

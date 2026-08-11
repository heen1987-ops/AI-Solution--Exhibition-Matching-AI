"""259개 개념 온톨로지 카탈로그(DECISION-004) 대조 헬퍼.

``app/services/matching/ontology_support.py``, ``ai/extraction/ontology_support.py``와 같은
"프로세스당 1회 로드" 캐싱 철학을 따른다. 이 트랙 전용으로 별도 파일을 두는 이유는 두 기존
모듈 어느 쪽도 이 트랙의 owned_paths(``app/services/extraction/**``)가 아니라서 직접
import해 결합을 만들지 않기 위해서다(다른 트랙 파일이 바뀌면 이 라우터가 조용히 깨질 위험 -
``app/api/v1/routers/exhibitor_preference.py`` 모듈 docstring이 이미 채택한 것과 같은 원칙).
"""

from __future__ import annotations

from functools import lru_cache

from meet_ai.ontology import Catalog, load_catalog


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()


def is_valid_concept_code(code: str, *, catalog: Catalog | None = None) -> bool:
    """``code``가 catalog.v1.json에 실재하는지 확인한다.

    WAVE2D-CONTRACTS §7: extracted_attribute.concept_codes는 "구현자가 애플리케이션
    계층에서 검증해야 하는, DB FK보다 약한 필드"라고 명시적으로 경고한다 - 이 함수가 그
    검증을 제공한다(``app/services/extraction/ingestion.py``가 수집 시점에 호출한다).
    """

    active_catalog = catalog or get_catalog()
    return code in active_catalog.by_code


def invalid_concept_codes(
    codes: list[str] | tuple[str, ...] | None, *, catalog: Catalog | None = None
) -> list[str]:
    """``codes`` 중 카탈로그에 없는 것만 순서를 보존해 반환한다. 빈 리스트면 전부 유효."""

    if not codes:
        return []
    active_catalog = catalog or get_catalog()
    return [code for code in codes if code not in active_catalog.by_code]

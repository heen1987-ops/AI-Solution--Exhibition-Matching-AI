"""Minimal keyword/synonym -> ontology concept-code matcher for free-text search.

TODO(AI_SEARCH track): replace ``interpret_query`` with
``ai.query_interpreter.QueryInterpreter`` once that interface is published
(see PROJECT_SCOPE.md / .harness/backlog.yaml BACKEND-008 note: "자연어 질의
구조화(온톨로지 코드 추출)는 별도 에이전트가 ai/query_interpreter.py에
QueryInterpreter 클래스로 만들고 있다"). Until then this module is a
deliberately small, dependency-free substring matcher against the published
259-concept catalog (src/meet_ai/ontology/catalog.v1.json, loaded through the
canonical ``meet_ai.ontology`` package — see AGENTS.md/DECISION-004: never
hardcode ad-hoc concept codes here).

It fails soft: a missing/invalid catalog or a query with no recognizable
terms both return an empty concept list rather than raising, so
``/search`` can always fall back to plain keyword search over the raw query
text (mandatory per BACKEND-008: "검색 자체가 죽으면 안 된다").
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from meet_ai.ontology.catalog import Catalog, load_catalog, normalize_text

# Concept types that are meaningful *search facets* for an anonymous
# exhibitor/product query. Visitor-profile-only or operational-state concept
# types (PROFILE_TYPE, BOOTH_STATUS, CONGESTION, BUYER_TYPE, ACTION, ...) are
# deliberately excluded so a stray label substring can't silently redirect a
# search query.
_SEARCHABLE_CONCEPT_TYPES = frozenset(
    {
        "PRODUCT_CATEGORY",
        "INGREDIENT",
        "TASTE",
        "AROMA",
        "ALCOHOL_LEVEL",
        "USE_CASE",
        "REGION",
        "PRICE_BAND",
        "TRADE_TYPE",
        "CHANNEL",
        "SUPPLY_CAPACITY",
        "PRODUCT_FEATURE",
        "VISIT_GOAL",
        "BUSINESS_GOAL",
    }
)

# A bare 1-character label match (e.g. a single hangul syllable) is too noisy
# to trust as a concept hit.
_MIN_LABEL_LENGTH = 2


@dataclass(frozen=True)
class InterpretedQuery:
    concept_codes: tuple[str, ...]
    matched_terms: tuple[str, ...]


@lru_cache
def _catalog() -> Catalog | None:
    try:
        return load_catalog()
    except (OSError, ValueError):
        # A malformed or missing catalog file must never break search.
        return None


def interpret_query(query: str, *, locale: str = "ko-KR") -> InterpretedQuery:
    """Map free-text ``query`` to zero or more ontology concept codes.

    Uses substring containment (not exact-match ``resolve_synonym``) because
    real user queries are full sentences ("막걸리 파는 업체 찾아줘"), not bare
    synonym phrases.
    """

    catalog = _catalog()
    normalized_query = normalize_text(query)
    if catalog is None or not normalized_query:
        return InterpretedQuery(concept_codes=(), matched_terms=())

    hits: dict[str, str] = {}

    # 1) curated synonyms first (highest precision, editorially reviewed).
    for synonym in catalog.synonyms:
        if synonym.get("locale", "ko-KR") != locale:
            continue
        text = normalize_text(str(synonym.get("text", "")))
        if len(text) >= _MIN_LABEL_LENGTH and text in normalized_query:
            code = synonym.get("concept_code")
            if code and code not in hits:
                hits[code] = text

    # 2) concept Korean labels themselves, restricted to search-relevant types.
    for item in catalog.concepts:
        code = item.get("code")
        if not code or code in hits:
            continue
        if item.get("concept_type") not in _SEARCHABLE_CONCEPT_TYPES:
            continue
        label = normalize_text(str(item.get("label_ko", "")))
        if len(label) >= _MIN_LABEL_LENGTH and label in normalized_query:
            hits[code] = label

    return InterpretedQuery(
        concept_codes=tuple(hits.keys()), matched_terms=tuple(hits.values())
    )

"""AI 검색 트랙(QueryInterpreter + KeywordRetriever)이 공유하는 데이터 구조.

apps/api/app/services/matching/types.py와 같은 원칙을 따른다 - 파이프라인 단계마다 새
dataclass를 만드는 대신, 이 모듈이 정의하는 소수의 구조를 단계 사이에서 그대로 주고받는다.

여기 등장하는 모든 온톨로지 코드값은 예시를 포함해 전부
``src/meet_ai/ontology/catalog.v1.json``(``meet_ai.ontology.load_catalog``)에 실재하는 코드다.
DECISION-004(.harness/decisions.md)가 이 카탈로그를 유일한 온톨로지 소스로 고정했으므로,
docs/vibe-coding-master-spec-v1.md §30의 INDUSTRY.MANUFACTURING/TECH.AI 같은 예시 코드는
이 모듈은 물론 이 패키지 어디에서도 재사용하지 않는다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# BACKEND-008 수용기준("search_session에 channel(WEB/KIOSK) 구분 필드 저장")과 동일한 값 집합.
CHANNELS: tuple[str, ...] = ("WEB", "KIOSK")

DEFAULT_CHANNEL = "WEB"

# 자연어 질의 의도. 이름은 재설계 문서(docs/vibe-coding-master-spec-v1.md §30)가 쓰던 것을
# 그대로 재사용하지만, 그 문서의 예시 코드값(INDUSTRY.* 등)은 재사용하지 않는다(DECISION-004).
INTENTS: tuple[str, ...] = (
    "SEARCH_EXHIBITOR",
    "SEARCH_PRODUCT_SERVICE",
    "SEARCH_BOOTH",
    "UNKNOWN",
)

# InterpretedQuery.target_types가 가질 수 있는 값. BACKEND-008 acceptance의 공개 조회 대상과
# 이름을 맞춘다(GET /events/{id}/exhibitors, .../products, GET /booths/{id}).
TARGET_TYPES: tuple[str, ...] = ("EXHIBITOR", "PRODUCT", "BOOTH")

REQUIREMENT_LEVELS: tuple[str, ...] = ("REQUIRED", "PREFERRED", "EXCLUDED")

_INTENT_TARGET_TYPES: dict[str, tuple[str, ...]] = {
    "SEARCH_EXHIBITOR": ("EXHIBITOR",),
    "SEARCH_PRODUCT_SERVICE": ("PRODUCT",),
    "SEARCH_BOOTH": ("BOOTH",),
    "UNKNOWN": (),
}


def target_types_for_intent(intent: str) -> tuple[str, ...]:
    """intent -> target_types 매핑. QueryInterpreter와 그 테스트가 공유하는 단일 진실 공급원."""

    return _INTENT_TARGET_TYPES.get(intent, ())


@dataclass(frozen=True)
class MatchedTerm:
    """질의 문장 안에서 온톨로지 개념 하나를 인식한 근거 한 건.

    같은 개념이 동의어 사전과 라벨 직접일치 양쪽에서 잡히더라도 QueryInterpreter는 개념
    코드당 이 구조체 하나만 남긴다(우선순위가 더 좋은 근거를 선택한다).
    """

    concept_code: str
    concept_type: str
    matched_text: str
    source: str  # SYNONYM | LABEL
    requirement_level: str  # REQUIRED | PREFERRED | EXCLUDED


@dataclass(frozen=True)
class InterpretedQuery:
    """QueryInterpreter.interpret()의 출력이자 KeywordRetriever.retrieve()의 유일한 질의
    입력 계약. required/preferred/excluded는 catalog.v1.json metadata.requirement_levels와
    이름을 맞췄다(ACCEPTABLE은 규칙기반 1단계에서 별도로 산출하지 않는다).
    """

    raw_query: str
    normalized_query: str
    channel: str
    language: str
    intent: str
    target_types: tuple[str, ...]
    concept_codes: tuple[str, ...]
    required_concepts: tuple[str, ...]
    preferred_concepts: tuple[str, ...]
    excluded_concepts: tuple[str, ...]
    confidence: float
    clarification_required: bool
    clarification: str | None
    matched_terms: tuple[MatchedTerm, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AccessScope:
    """KeywordRetriever.retrieve()가 검색을 허용할 범위.

    approval_status 필터는 여기 두지 않는다 - PROJECT_SCOPE.md/AGENTS.md 절대 규칙("미승인
    업체/제품은 공개 API·검색·추천 어디에도 노출하지 않는다")을 호출자가 끌 수 없도록,
    KeywordRetriever가 항상 무조건 강제한다(ai/keyword_retriever.py 참고).
    """

    tenant_id: uuid.UUID
    event_id: uuid.UUID
    taxonomy_version_id: uuid.UUID
    channel: str
    is_verified_buyer: bool = False


@dataclass(frozen=True)
class SearchCandidate:
    """KeywordRetriever.retrieve()가 반환하는 후보 한 건.

    최종 순위/다양성 보정은 이 모듈의 책임이 아니다(docs/05-ai-matching-engine-architecture.md
    5.4절 Candidate Generator와 동일한 경계 - "충분한 재현율을 확보하는 것이 목적"). keyword_score는
    이후 하이브리드 랭킹 단계가 벡터 채널 점수와 합칠 원시 키워드 채널 신호일 뿐이다.
    """

    object_type: str  # EXHIBITOR | PRODUCT | BOOTH
    object_id: uuid.UUID
    exhibitor_id: uuid.UUID | None
    participation_id: uuid.UUID | None
    booth_id: uuid.UUID | None
    display_name: str
    summary: str | None
    matched_concept_codes: tuple[str, ...]
    required_hit_count: int
    preferred_hit_count: int
    text_match_score: float
    keyword_score: float
    source: str = "KEYWORD"

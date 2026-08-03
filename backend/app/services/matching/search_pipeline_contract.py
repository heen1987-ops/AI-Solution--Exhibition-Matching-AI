"""AIS-009 search pipeline contract for BAC-008.

This module is intentionally pure. It fixes the provider order, keyword/vector
availability requirements, score component mapping, and fallback persistence
contract without pretending that FTS indexes or query embeddings already exist.
BAC-008 can import this contract while wiring the API facade, then replace the
unavailable providers with real implementations once the follow-up DB work is
done.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.services.matching.search_recovery import SearchRecoveryAction

ProviderName = Literal["STRUCTURED", "KEYWORD", "VECTOR", "POPULAR"]
ProviderStatus = Literal["READY", "DISABLED_PENDING_DB", "DISABLED_PENDING_AI"]
FallbackReason = Literal["NO_RESULT", "AI_SERVICE_UNAVAILABLE", "INVALID_QUERY"]
ScoreComponent = Literal["structured_score", "keyword_score", "semantic_score"]
TargetType = Literal["BOOTH", "EVENT_PRODUCT", "EXHIBITOR", "PROGRAM"]


@dataclass(frozen=True)
class ProviderReadiness:
    provider_name: ProviderName
    status: ProviderStatus
    reason_codes: tuple[str, ...] = ()
    fallback_reason: FallbackReason | None = None

    @property
    def available(self) -> bool:
        return self.status == "READY"


@dataclass(frozen=True)
class ProviderContract:
    provider_name: ProviderName
    score_component: ScoreComponent
    target_fields_by_type: Mapping[TargetType, tuple[str, ...]]
    rank_normalization: str
    required_db_objects: tuple[str, ...]
    unavailable_readiness: ProviderReadiness


KEYWORD_SEARCH_CONTRACT = ProviderContract(
    provider_name="KEYWORD",
    score_component="keyword_score",
    target_fields_by_type={
        "EVENT_PRODUCT": (
            "exhibition.product.product_name",
            "exhibition.product.product_summary",
            "exhibition.product.production_method",
            "ai.embedding_document.content_excerpt(content_type IN PRODUCT,SUMMARY)",
        ),
        "EXHIBITOR": (
            "exhibition.exhibitor.company_name",
            "exhibition.exhibitor.company_summary",
            "exhibition.exhibitor_participation.promotion_summary",
            "exhibition.product.product_name/product_summary via approved participation",
            "ai.embedding_document.content_excerpt(content_type IN EXHIBITOR,TRADE,SUMMARY)",
        ),
        "BOOTH": (),
        "PROGRAM": (),
    },
    rank_normalization=(
        "Order by PostgreSQL ts_rank_cd DESC, then convert provider rank to "
        "0..1 with candidate_generator.rank_based_score before RRF."
    ),
    required_db_objects=(
        "0013_search_web_only_indexes expression GIN FTS indexes over approved exhibitor/product text",
        "PostgreSQL simple text search configuration as safe multilingual fallback",
        "approval filters: exhibitor/product/event_product master approval and recommendable.active",
    ),
    unavailable_readiness=ProviderReadiness(
        provider_name="KEYWORD",
        status="DISABLED_PENDING_DB",
        reason_codes=("KEYWORD_PROVIDER_SQL_MISSING",),
        fallback_reason="NO_RESULT",
    ),
)


VECTOR_SEARCH_CONTRACT = ProviderContract(
    provider_name="VECTOR",
    score_component="semantic_score",
    target_fields_by_type={
        "EVENT_PRODUCT": (
            "ai.embedding_document.recommendable_id where content_type IN PRODUCT,SUMMARY",
        ),
        "EXHIBITOR": (
            "ai.embedding_document.recommendable_id where content_type IN EXHIBITOR,TRADE,SUMMARY",
        ),
        "BOOTH": (),
        "PROGRAM": (),
    },
    rank_normalization=(
        "Use pgvector cosine distance for active vectors with matching model and "
        "dimension; semantic_score = clamp(1 - cosine_distance, 0, 1), ordered DESC."
    ),
    required_db_objects=(
        "ai.embedding_document(active=true,event_id,locale,recommendable_id)",
        "ai.embedding_vector(active=true,embedding_model,embedding_dimension,embedding)",
        "query embedding generator that returns the same model/dimension as stored vectors",
        "0013_search_web_only_indexes partial HNSW cosine ANN index on ai.embedding_vector.embedding::vector(1536)",
    ),
    unavailable_readiness=ProviderReadiness(
        provider_name="VECTOR",
        status="DISABLED_PENDING_AI",
        reason_codes=(
            "QUERY_EMBEDDING_ADAPTER_MISSING",
            "ACTIVE_EMBEDDING_DATA_UNVERIFIED",
        ),
        fallback_reason="AI_SERVICE_UNAVAILABLE",
    ),
)


DEFAULT_PROVIDER_READINESS: Mapping[ProviderName, ProviderReadiness] = {
    "STRUCTURED": ProviderReadiness(provider_name="STRUCTURED", status="READY"),
    "KEYWORD": KEYWORD_SEARCH_CONTRACT.unavailable_readiness,
    "VECTOR": VECTOR_SEARCH_CONTRACT.unavailable_readiness,
    "POPULAR": ProviderReadiness(
        provider_name="POPULAR",
        status="DISABLED_PENDING_DB",
        reason_codes=("POPULAR_PROVIDER_SQL_MISSING",),
        fallback_reason="NO_RESULT",
    ),
}


@dataclass(frozen=True)
class PipelineStep:
    order: int
    name: str
    detail: str


BAC008_SEARCH_PIPELINE: tuple[PipelineStep, ...] = (
    PipelineStep(
        1,
        "validate_actor",
        "Resolve REGISTERED_WEB/BUYER_WEB user or GUEST_WEB guest_session without PII.",
    ),
    PipelineStep(
        2,
        "interpret_intent",
        "Run AIS-005 intent parsing when query_text is present; reject invented concepts.",
    ),
    PipelineStep(
        3,
        "build_search_query",
        "Convert valid concept_codes to concept_ids and preserve raw_text/locale/channel.",
    ),
    PipelineStep(
        4,
        "run_available_providers",
        "Run STRUCTURED, then KEYWORD/VECTOR only when their readiness is READY.",
    ),
    PipelineStep(
        5,
        "combine_candidates",
        "Merge provider results with ReciprocalRankFusionCombiner.",
    ),
    PipelineStep(
        6,
        "decide_recovery",
        "Apply decide_search_recovery for no-result, low-confidence, and ontology gaps.",
    ),
    PipelineStep(
        7,
        "persist_search",
        "Persist matching.search_session/search_query/search_result with fallback_reason.",
    ),
    PipelineStep(
        8,
        "respond",
        "Return SearchResponse.results plus meta.code=SEARCH_NO_RESULT when applicable.",
    ),
)


def provider_order_for_channel(
    channel: Literal["REGISTERED_WEB", "GUEST_WEB", "BUYER_WEB", "ADMIN_PREVIEW"],
) -> tuple[ProviderName, ...]:
    if channel == "BUYER_WEB":
        return ("STRUCTURED", "KEYWORD", "VECTOR")
    if channel == "ADMIN_PREVIEW":
        return ("STRUCTURED", "KEYWORD", "VECTOR", "POPULAR")
    return ("STRUCTURED", "KEYWORD", "VECTOR", "POPULAR")


def enabled_provider_names(
    readiness: Mapping[ProviderName, ProviderReadiness] = DEFAULT_PROVIDER_READINESS,
) -> tuple[ProviderName, ...]:
    return tuple(name for name, state in readiness.items() if state.available)


def unavailable_fallback_reasons(
    readiness: Mapping[ProviderName, ProviderReadiness] = DEFAULT_PROVIDER_READINESS,
) -> tuple[FallbackReason, ...]:
    reasons = {
        state.fallback_reason
        for state in readiness.values()
        if not state.available and state.fallback_reason is not None
    }
    return tuple(sorted(reasons))


def fallback_reason_for_recovery(
    action: SearchRecoveryAction,
    *,
    provider_unavailable: bool = False,
) -> FallbackReason | None:
    if provider_unavailable:
        return "AI_SERVICE_UNAVAILABLE"
    if action == "NONE":
        return None
    if action in {
        "CLARIFY",
        "BROADEN_CONCEPTS",
        "POPULAR_FALLBACK",
        "CATEGORY_FALLBACK",
    }:
        return "NO_RESULT"
    raise ValueError(f"unsupported recovery action: {action}")

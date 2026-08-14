"""Fail-soft query embeddings and pgvector recall for public catalog search."""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, case, func, literal, literal_column, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1, Settings
from app.models.ai import ModelVersion, ObjectEmbedding
from app.models.exhibitor import (
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
)
from app.models.matching import Recommendable

logger = logging.getLogger(__name__)

SemanticStatus = Literal["AVAILABLE", "DISABLED", "UNAVAILABLE"]
_HNSW_EF_SEARCH_MIN = 200
_HNSW_MAX_SCAN_TUPLES = 50_000


class EmbeddingProviderError(RuntimeError):
    """Expected provider or response-validation failure safe for fallback."""


class QueryEmbeddingProvider(Protocol):
    model: str
    dimensions: int

    async def embed(self, text: str) -> tuple[float, ...]: ...

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]: ...


@dataclass(frozen=True, slots=True)
class SemanticScoreBatch:
    participation_scores: dict[uuid.UUID, float]
    status: SemanticStatus
    model_version_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class PreparedSemanticQuery:
    embedding: tuple[float, ...] | None
    status: SemanticStatus
    model_version_id: uuid.UUID | None = None
    provider_latency_ms: float = 0.0


class SemanticScorer(Protocol):
    async def prepare(self, *, query: str) -> PreparedSemanticQuery: ...

    async def score(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        language: str,
        prepared: PreparedSemanticQuery,
    ) -> SemanticScoreBatch: ...


class NullSemanticScorer:
    async def prepare(self, *, query: str) -> PreparedSemanticQuery:
        del query
        return PreparedSemanticQuery(None, "DISABLED")

    async def score(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        language: str,
        prepared: PreparedSemanticQuery,
    ) -> SemanticScoreBatch:
        del db, tenant_id, event_id, language, prepared
        return SemanticScoreBatch({}, "DISABLED")


class _EmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_EmbeddingItem]
    model: str


class OpenAIQueryEmbeddingProvider:
    """OpenAI embeddings REST adapter isolated from search policy code."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = f"{base_url.rstrip('/')}/"
        self.model = model
        self.dimensions = dimensions
        self._timeout_seconds = timeout_seconds

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        normalized = [" ".join(text.split()) for text in texts]
        if not normalized or any(not text for text in normalized):
            raise EmbeddingProviderError("embedding input must not be empty")

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    "embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "input": normalized,
                        "dimensions": self.dimensions,
                        "encoding_format": "float",
                    },
                )
                response.raise_for_status()
                payload = _EmbeddingResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise EmbeddingProviderError(type(exc).__name__) from exc

        if payload.model != self.model or len(payload.data) != len(normalized):
            raise EmbeddingProviderError("embedding response contract mismatch")

        by_index = {item.index: item.embedding for item in payload.data}
        if set(by_index) != set(range(len(normalized))):
            raise EmbeddingProviderError("embedding response indexes are invalid")

        vectors: list[tuple[float, ...]] = []
        for index in range(len(normalized)):
            vector = tuple(float(value) for value in by_index[index])
            if len(vector) != self.dimensions:
                raise EmbeddingProviderError("embedding dimension mismatch")
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingProviderError("embedding contains a non-finite value")
            if not any(value != 0.0 for value in vector):
                raise EmbeddingProviderError("embedding must not be a zero vector")
            vectors.append(vector)
        return vectors

    async def embed(self, text: str) -> tuple[float, ...]:
        return (await self.embed_many([text]))[0]


def _semantic_hits_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    query_embedding: tuple[float, ...],
    model_version_id: uuid.UUID,
    language: str,
    top_k: int,
    model_config_hash: str = SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
):
    """Build top-K vector recall followed by mandatory public exposure filters."""

    distance = ObjectEmbedding.embedding.cosine_distance(list(query_embedding))
    languages = list(dict.fromkeys([language, "und"]))
    participation_id = case(
        (
            Recommendable.object_type == "EXHIBITOR",
            Recommendable.participation_id,
        ),
        (
            Recommendable.object_type == "EVENT_PRODUCT",
            EventProduct.participation_id,
        ),
        else_=None,
    )
    raw_hits = (
        select(
            participation_id.label("participation_id"),
            (literal(1.0) - distance).label("raw_similarity"),
        )
        .join(
            ModelVersion,
            ModelVersion.model_version_id == ObjectEmbedding.model_version_id,
        )
        .join(
            Recommendable,
            Recommendable.recommendable_id == ObjectEmbedding.recommendable_id,
        )
        .outerjoin(
            EventProduct,
            EventProduct.event_product_id == Recommendable.event_product_id,
        )
        .outerjoin(Product, Product.product_id == EventProduct.product_id)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == participation_id,
        )
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            ObjectEmbedding.tenant_id == tenant_id,
            ObjectEmbedding.event_id == event_id,
            ObjectEmbedding.model_version_id == model_version_id,
            ObjectEmbedding.language.in_(languages),
            # One active SUMMARY exists per participation/language, and its
            # backfill text includes that participation's approved products.
            # Restricting recall to SUMMARY prevents product-rich exhibitors
            # from monopolizing the raw ANN window.
            # Render the frozen discriminator as a SQL literal. PostgreSQL cannot
            # prove that a bind parameter implies the partial-index predicate.
            ObjectEmbedding.content_type == literal_column("'SUMMARY'"),
            ObjectEmbedding.active.is_(True),
            ModelVersion.model_type == "EMBEDDING",
            ModelVersion.provider == "OPENAI",
            ModelVersion.model_name == "text-embedding-3-small",
            ModelVersion.gateway_adapter == "OPENAI_DIRECT",
            ModelVersion.config_hash == model_config_hash,
            ModelVersion.status == "DEPLOYED",
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
            Recommendable.active.is_(True),
            Recommendable.object_type.in_(("EXHIBITOR", "EVENT_PRODUCT")),
            ExhibitorParticipation.tenant_id == tenant_id,
            ExhibitorParticipation.event_id == event_id,
            ExhibitorParticipation.participation_status == "APPROVED",
            Exhibitor.tenant_id == tenant_id,
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
            participation_id.is_not(None),
            or_(
                Recommendable.object_type == "EXHIBITOR",
                and_(
                    Recommendable.object_type == "EVENT_PRODUCT",
                    EventProduct.tenant_id == tenant_id,
                    EventProduct.event_id == event_id,
                    EventProduct.approval_status == "APPROVED",
                    Product.exhibitor_id == Exhibitor.exhibitor_id,
                    Product.master_approval_status == "APPROVED",
                    Product.deleted_at.is_(None),
                ),
            ),
        )
        .order_by(distance)
        # Requested language plus `und` means at most two rows per participation.
        # A 2x window therefore contains top_k unique participations when enough
        # eligible summaries exist (subject to ANN recall, monitored at G3).
        .limit(top_k * len(languages))
        .subquery("semantic_raw_hits")
    )

    semantic_score = func.greatest(
        literal(0.0),
        func.least(literal(1.0), func.max(raw_hits.c.raw_similarity)),
    ).label("semantic_score")

    return (
        select(raw_hits.c.participation_id, semantic_score)
        .select_from(raw_hits)
        .group_by(raw_hits.c.participation_id)
        .order_by(semantic_score.desc(), raw_hits.c.participation_id)
        .limit(top_k)
    )


class PgvectorSemanticScorer:
    def __init__(
        self,
        *,
        provider: QueryEmbeddingProvider,
        model_version_id: uuid.UUID,
        minimum_relevance: float,
        top_k: int,
        model_config_hash: str = SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
    ) -> None:
        self._provider = provider
        self._model_version_id = model_version_id
        self._minimum_relevance = minimum_relevance
        self._top_k = top_k
        self._model_config_hash = model_config_hash

    async def prepare(self, *, query: str) -> PreparedSemanticQuery:
        if not query.strip():
            return PreparedSemanticQuery(None, "DISABLED", self._model_version_id)

        started_at = time.perf_counter()
        try:
            query_embedding = await self._provider.embed(query)
        except EmbeddingProviderError as exc:
            logger.warning(
                "semantic query embedding unavailable",
                extra={
                    "provider_error_type": type(exc.__cause__ or exc).__name__,
                    "model_version_id": str(self._model_version_id),
                    "semantic_latency_ms": round(
                        (time.perf_counter() - started_at) * 1000, 2
                    ),
                },
            )
            return PreparedSemanticQuery(
                None,
                "UNAVAILABLE",
                self._model_version_id,
                round((time.perf_counter() - started_at) * 1000, 2),
            )
        return PreparedSemanticQuery(
            query_embedding,
            "AVAILABLE",
            self._model_version_id,
            round((time.perf_counter() - started_at) * 1000, 2),
        )

    async def score(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        language: str,
        prepared: PreparedSemanticQuery,
    ) -> SemanticScoreBatch:
        if prepared.status != "AVAILABLE" or prepared.embedding is None:
            return SemanticScoreBatch({}, prepared.status, prepared.model_version_id)

        started_at = time.perf_counter()
        try:
            async with db.begin_nested():
                # pgvector 0.8+ iterative scans continue past globally-near rows
                # removed by event/model/language/approval filters.
                await db.execute(
                    select(
                        func.set_config(
                            "hnsw.iterative_scan",
                            "strict_order",
                            True,
                        )
                    )
                )
                await db.execute(
                    select(
                        func.set_config(
                            "hnsw.ef_search",
                            str(max(_HNSW_EF_SEARCH_MIN, self._top_k * 2)),
                            True,
                        )
                    )
                )
                await db.execute(
                    select(
                        func.set_config(
                            "hnsw.max_scan_tuples",
                            str(_HNSW_MAX_SCAN_TUPLES),
                            True,
                        )
                    )
                )
                rows = (
                    await db.execute(
                        _semantic_hits_stmt(
                            tenant_id=tenant_id,
                            event_id=event_id,
                            query_embedding=prepared.embedding,
                            model_version_id=self._model_version_id,
                            language=language,
                            top_k=self._top_k,
                            model_config_hash=self._model_config_hash,
                        )
                    )
                ).all()
        except SQLAlchemyError as exc:
            logger.warning(
                "semantic pgvector channel unavailable",
                extra={
                    "database_error_type": type(exc).__name__,
                    "model_version_id": str(self._model_version_id),
                    "semantic_latency_ms": round(
                        prepared.provider_latency_ms
                        + (time.perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            return SemanticScoreBatch({}, "UNAVAILABLE", self._model_version_id)

        scores: dict[uuid.UUID, float] = {}
        for participation_id, value in rows:
            score = min(max(float(value or 0.0), 0.0), 1.0)
            if score >= self._minimum_relevance:
                scores[participation_id] = score
        logger.info(
            "semantic search channel completed",
            extra={
                "model_version_id": str(self._model_version_id),
                "semantic_hit_count": len(scores),
                "semantic_latency_ms": round(
                    prepared.provider_latency_ms
                    + (time.perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        return SemanticScoreBatch(scores, "AVAILABLE", self._model_version_id)


def get_query_embedding_provider(
    settings: Settings,
) -> QueryEmbeddingProvider | None:
    if not settings.SEARCH_EMBEDDING_ENABLED:
        return None

    secret = settings.SEARCH_EMBEDDING_OPENAI_API_KEY
    if secret is None:
        # Settings validation normally prevents this. Keep the factory fail-safe for
        # tests and for future settings sources that may bypass BaseSettings parsing.
        return None

    return OpenAIQueryEmbeddingProvider(
        api_key=secret.get_secret_value().strip(),
        base_url=settings.SEARCH_EMBEDDING_BASE_URL,
        model=settings.SEARCH_EMBEDDING_MODEL,
        dimensions=settings.SEARCH_EMBEDDING_DIMENSIONS,
        timeout_seconds=settings.SEARCH_EMBEDDING_TIMEOUT_SECONDS,
    )


def get_semantic_scorer(settings: Settings) -> SemanticScorer:
    provider = get_query_embedding_provider(settings)
    if provider is None:
        return NullSemanticScorer()
    return PgvectorSemanticScorer(
        provider=provider,
        model_version_id=settings.SEARCH_EMBEDDING_MODEL_VERSION_ID,
        minimum_relevance=settings.SEARCH_EMBEDDING_MIN_RELEVANCE,
        top_k=settings.SEARCH_EMBEDDING_TOP_K,
        model_config_hash=SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
    )

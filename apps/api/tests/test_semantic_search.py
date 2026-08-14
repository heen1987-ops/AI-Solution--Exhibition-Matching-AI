from __future__ import annotations

import math
import uuid
from typing import Self

import httpx
import pytest
from app.core.config import Settings
from app.db.base import Base
from app.models.ai import SEARCH_EMBEDDING_DIMENSIONS
from app.services.matching.kiosk_search_score import (
    KioskSearchSignals,
    score_kiosk_search,
)
from app.services.matching.semantic_search import (
    EmbeddingProviderError,
    OpenAIQueryEmbeddingProvider,
    PgvectorSemanticScorer,
    _semantic_hits_stmt,
)
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError


def test_kiosk_search_score_uses_the_frozen_coefficients() -> None:
    score = score_kiosk_search(
        KioskSearchSignals(
            semantic=0.8,
            keyword=0.7,
            category=0.6,
            data_quality=0.5,
            booth_availability=0.4,
        )
    )

    assert score == pytest.approx(
        0.45 * 0.8 + 0.30 * 0.7 + 0.15 * 0.6 + 0.05 * 0.5 + 0.05 * 0.4
    )


def test_kiosk_search_score_clamps_invalid_signals() -> None:
    score = score_kiosk_search(
        KioskSearchSignals(
            semantic=math.nan,
            keyword=2.0,
            category=-1.0,
            data_quality=math.inf,
            booth_availability=1.0,
        )
    )

    assert score == pytest.approx(0.35)


def test_object_embedding_metadata_pins_dimension_and_active_indexes() -> None:
    table = Base.metadata.tables["ai.object_embedding"]
    indexes = {index.name: index for index in table.indexes}

    assert str(table.c.embedding.type) == "VECTOR(512)"
    assert indexes["uq_object_embedding_active_pointer"].unique is True
    assert (
        str(
            indexes["uq_object_embedding_active_pointer"].dialect_options["postgresql"][
                "where"
            ]
        ).upper()
        == "ACTIVE IS TRUE"
    )
    hnsw = indexes["ix_object_embedding_active_hnsw_cosine"]
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }
    assert (
        str(hnsw.dialect_options["postgresql"]["where"]).upper()
        == "ACTIVE IS TRUE AND CONTENT_TYPE = 'SUMMARY'"
    )


def test_semantic_search_rejects_a_blank_provider_secret() -> None:
    with pytest.raises(ValidationError, match="SEARCH_EMBEDDING_OPENAI_API_KEY"):
        Settings(
            SEARCH_EMBEDDING_ENABLED=True,
            SEARCH_EMBEDDING_OPENAI_API_KEY="   ",
        )


def test_semantic_search_rejects_uncontracted_model_or_provider_endpoint() -> None:
    with pytest.raises(ValidationError, match="model version requires a new contract"):
        Settings(SEARCH_EMBEDDING_MODEL_VERSION_ID=uuid.uuid4())

    with pytest.raises(
        ValidationError, match="base URL requires a new provider contract"
    ):
        Settings(SEARCH_EMBEDDING_BASE_URL="https://example.invalid/v1")


class _FakeResponse:
    def __init__(self, body: dict[str, object], status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                "provider error", request=request, response=response
            )


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.request_json: dict[str, object] | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(
        self,
        path: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> _FakeResponse:
        assert path == "embeddings"
        assert headers["Authorization"].startswith("Bearer ")
        self.request_json = json
        return self.response


@pytest.mark.asyncio
async def test_openai_embedding_adapter_validates_dimension_and_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = [0.0] * SEARCH_EMBEDDING_DIMENSIONS
    vector[0] = 1.0
    client = _FakeClient(
        _FakeResponse(
            {
                "model": "text-embedding-3-small",
                "data": [{"index": 0, "embedding": vector}],
            }
        )
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAIQueryEmbeddingProvider(
        api_key="test-only-key",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
        dimensions=SEARCH_EMBEDDING_DIMENSIONS,
        timeout_seconds=1.0,
    )

    result = await provider.embed("부드러운 전통주")

    assert len(result) == SEARCH_EMBEDDING_DIMENSIONS
    assert client.request_json is not None
    assert client.request_json["dimensions"] == SEARCH_EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_openai_embedding_adapter_rejects_bad_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _FakeResponse(
            {
                "model": "text-embedding-3-small",
                "data": [{"index": 0, "embedding": [1.0, 2.0]}],
            }
        )
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAIQueryEmbeddingProvider(
        api_key="test-only-key",
        base_url="https://api.openai.com/v1",
        model="text-embedding-3-small",
        dimensions=SEARCH_EMBEDDING_DIMENSIONS,
        timeout_seconds=1.0,
    )

    with pytest.raises(EmbeddingProviderError, match="dimension"):
        await provider.embed("검색어")


class _FailingProvider:
    model = "text-embedding-3-small"
    dimensions = SEARCH_EMBEDDING_DIMENSIONS

    async def embed(self, text: str) -> tuple[float, ...]:
        del text
        raise EmbeddingProviderError("simulated outage")

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        del texts
        raise EmbeddingProviderError("simulated outage")


@pytest.mark.asyncio
async def test_pgvector_scorer_falls_back_when_provider_is_unavailable() -> None:
    scorer = PgvectorSemanticScorer(
        provider=_FailingProvider(),
        model_version_id=uuid.uuid4(),
        minimum_relevance=0.35,
        top_k=80,
    )

    prepared = await scorer.prepare(query="막걸리")
    result = await scorer.score(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        language="ko",
        prepared=prepared,
    )

    assert result.status == "UNAVAILABLE"
    assert result.participation_scores == {}


class _WorkingProvider:
    model = "text-embedding-3-small"
    dimensions = SEARCH_EMBEDDING_DIMENSIONS

    async def embed(self, text: str) -> tuple[float, ...]:
        del text
        return tuple([1.0] + [0.0] * (SEARCH_EMBEDDING_DIMENSIONS - 1))

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [await self.embed(text) for text in texts]


class _NestedTransaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


class _FailingVectorSession:
    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    async def execute(self, statement: object) -> None:
        del statement
        raise SQLAlchemyError("simulated pgvector outage")


@pytest.mark.asyncio
async def test_pgvector_scorer_falls_back_inside_a_savepoint() -> None:
    scorer = PgvectorSemanticScorer(
        provider=_WorkingProvider(),
        model_version_id=uuid.uuid4(),
        minimum_relevance=0.35,
        top_k=80,
    )

    prepared = await scorer.prepare(query="막걸리")
    result = await scorer.score(
        _FailingVectorSession(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        language="ko",
        prepared=prepared,
    )

    assert result.status == "UNAVAILABLE"
    assert result.participation_scores == {}


class _VectorRows:
    def __init__(self, rows: list[tuple[uuid.UUID, float]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[uuid.UUID, float]]:
        return self._rows


class _SuccessfulVectorSession:
    def __init__(self, participation_id: uuid.UUID) -> None:
        self._participation_id = participation_id
        self.statements: list[str] = []

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    async def execute(self, statement: object) -> _VectorRows:
        self.statements.append(
            str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
        )
        if len(self.statements) < 4:
            return _VectorRows([])
        return _VectorRows([(self._participation_id, 0.82)])


@pytest.mark.asyncio
async def test_pgvector_scorer_enables_filtered_iterative_hnsw_scan() -> None:
    participation_id = uuid.uuid4()
    session = _SuccessfulVectorSession(participation_id)
    scorer = PgvectorSemanticScorer(
        provider=_WorkingProvider(),
        model_version_id=uuid.uuid4(),
        minimum_relevance=0.35,
        top_k=80,
    )

    prepared = await scorer.prepare(query="부드러운 전통주")
    result = await scorer.score(
        session,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        language="ko",
        prepared=prepared,
    )

    assert result.participation_scores == {participation_id: pytest.approx(0.82)}
    assert "hnsw.iterative_scan" in session.statements[0]
    assert "strict_order" in session.statements[0]
    assert "hnsw.ef_search" in session.statements[1]
    assert "hnsw.max_scan_tuples" in session.statements[2]


def test_semantic_query_enforces_model_and_public_approval_filters() -> None:
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    model_version_id = uuid.uuid4()
    query = tuple([1.0] + [0.0] * (SEARCH_EMBEDDING_DIMENSIONS - 1))

    sql = str(
        _semantic_hits_stmt(
            tenant_id=tenant_id,
            event_id=event_id,
            query_embedding=query,
            model_version_id=model_version_id,
            language="ko",
            top_k=80,
        ).compile(dialect=postgresql.dialect())
    )

    assert "<=>" in sql
    assert "ai.object_embedding.active IS true" in sql
    assert "ai.object_embedding.content_type = 'SUMMARY'" in sql
    assert "content_type_" not in sql
    assert "ai.model_version.status" in sql
    assert "ai.model_version.provider" in sql
    assert "ai.model_version.gateway_adapter" in sql
    assert "ai.model_version.config_hash" in sql
    assert "ai.object_embedding.tenant_id" in sql
    assert "exhibition.recommendable.tenant_id" in sql
    assert "exhibition.exhibitor_participation.participation_status" in sql
    assert "exhibition.exhibitor.master_approval_status" in sql
    assert "exhibition.exhibitor.deleted_at IS NULL" in sql
    assert "exhibition.event_product.approval_status" in sql
    assert "exhibition.product.master_approval_status" in sql
    assert "exhibition.product.exhibitor_id" in sql
    assert "exhibition.product.deleted_at IS NULL" in sql
    assert sql.index("participation_status") < sql.index("LIMIT")

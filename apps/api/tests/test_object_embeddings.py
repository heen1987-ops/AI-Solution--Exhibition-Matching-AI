from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import (
    SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
    SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
)
from app.models.ai import SEARCH_EMBEDDING_DIMENSIONS, ObjectEmbedding
from app.services.object_embeddings import (
    MAX_EMBEDDING_REQUEST_BYTES,
    MAX_EMBEDDING_SOURCE_BYTES,
    EmbeddingDocument,
    _embedding_batches,
    _public_text,
    _summary_public_text,
    backfill_catalog_embeddings,
)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Result:
        return self


def test_embedding_inputs_obey_individual_and_aggregate_provider_limits() -> None:
    text = _public_text("🍶" * 3_000)
    assert len(text.encode("utf-8")) <= MAX_EMBEDDING_SOURCE_BYTES

    documents = [
        EmbeddingDocument(
            tenant_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            recommendable_id=uuid.uuid4(),
            content_type="SUMMARY",
            language="und",
            text="x" * MAX_EMBEDDING_SOURCE_BYTES,
            content_hash=b"x" * 32,
        )
        for _ in range(64)
    ]
    batches = list(_embedding_batches(documents, max_documents=64))

    assert len(batches) > 1
    assert all(
        sum(len(document.text.encode("utf-8")) for document in batch)
        <= MAX_EMBEDDING_REQUEST_BYTES
        for batch in batches
    )


def test_summary_preserves_later_product_names_before_fairly_truncating_details() -> (
    None
):
    text = _summary_public_text(
        company_name="승인 양조장",
        company_summary="공개 업체 소개",
        promotion_summary="현장 공개 행사",
        products=[
            ("첫 제품", "가" * 9_000, "장기 숙성"),
            ("희귀 타깃 제품", "소량 한정", "옹기 발효"),
        ],
    )

    assert "첫 제품" in text
    assert "희귀 타깃 제품" in text
    assert len(text.encode("utf-8")) <= MAX_EMBEDDING_SOURCE_BYTES


class _BackfillSession:
    def __init__(
        self,
        *,
        event_id: uuid.UUID,
        snapshot_changed: bool = False,
    ) -> None:
        tenant_id = uuid.uuid4()
        participation_id = uuid.uuid4()
        exhibitor_rows = [
            (
                tenant_id,
                event_id,
                uuid.uuid4(),
                participation_id,
                "승인 양조장",
                "공개 업체 소개",
                "현장 공개 행사",
            )
        ]
        product_rows = [
            (
                tenant_id,
                event_id,
                uuid.uuid4(),
                participation_id,
                "승인 전통주",
                "공개 제품 소개",
                "저온 숙성",
            )
        ]
        latest_product_rows = product_rows
        if snapshot_changed:
            latest_product_rows = [
                (*product_rows[0][:5], "catalog changed", product_rows[0][6])
            ]
        self._results = [
            _Result(exhibitor_rows),
            _Result(product_rows),
            _Result([]),
            _Result([]),
            _Result(exhibitor_rows),
            _Result(latest_product_rows),
        ]
        self.added: list[ObjectEmbedding] = []
        self.executed: list[Any] = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self) -> bool:
        return False

    async def get(self, model: type, key: uuid.UUID) -> Any:
        del model, key
        return SimpleNamespace(
            model_type="EMBEDDING",
            status="DEPLOYED",
            provider="OPENAI",
            model_name="text-embedding-3-small",
            gateway_adapter="OPENAI_DIRECT",
            config_hash=SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
            config_json={
                "dimensions": SEARCH_EMBEDDING_DIMENSIONS,
                "distance": "COSINE",
            },
        )

    async def execute(self, statement: Any) -> _Result:
        self.executed.append(statement)
        if "pg_advisory_xact_lock" in str(statement):
            return _Result([])
        if not self._results and "FROM ai.object_embedding" in str(statement):
            return _Result(self.added)
        return self._results.pop(0) if self._results else _Result([])

    def add(self, row: ObjectEmbedding) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _RecordingProvider:
    model = "text-embedding-3-small"
    dimensions = SEARCH_EMBEDDING_DIMENSIONS

    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        self.inputs.extend(texts)
        vector = tuple([1.0] + [0.0] * (self.dimensions - 1))
        return [vector for _ in texts]

    async def embed(self, text: str) -> tuple[float, ...]:
        return (await self.embed_many([text]))[0]


class _InvalidModelSession(_BackfillSession):
    async def get(self, model: type, key: uuid.UUID) -> Any:
        value = await super().get(model, key)
        value.gateway_adapter = "UNCONTRACTED"
        return value


class _FailOnSecondBatchProvider(_RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated second-batch provider failure")
        return await super().embed_many(texts)


@pytest.mark.asyncio
async def test_backfill_uses_only_approved_public_documents_and_activates_atomically() -> (
    None
):
    event_id = uuid.uuid4()
    session = _BackfillSession(event_id=event_id)
    provider = _RecordingProvider()

    result = await backfill_catalog_embeddings(
        session,  # type: ignore[arg-type]
        provider=provider,
        model_version_id=SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
        event_id=event_id,
        activate=True,
    )

    assert result.discovered == 2
    assert result.embedded == 2
    assert result.reused == 0
    assert result.activated == 2
    assert len(session.added) == 2
    assert all(row.active for row in session.added)
    assert {row.language for row in session.added} == {"und"}
    assert {row.content_type for row in session.added} == {"SUMMARY", "PRODUCT"}
    assert all(len(row.content_hash) == 32 for row in session.added)
    assert all(
        len(row.embedding) == SEARCH_EMBEDDING_DIMENSIONS for row in session.added
    )
    assert provider.inputs == [
        "승인 양조장 승인 전통주 공개 업체 소개 현장 공개 행사 공개 제품 소개 저온 숙성",
        "승인 전통주 공개 제품 소개 저온 숙성",
    ]
    assert session.flushes == 3
    assert session.commits == 3
    assert session.rollbacks == 0
    activation_sql = str(
        session.executed[-1].compile(compile_kwargs={"literal_binds": True})
    )
    lock_sql = "\n".join(
        str(item.compile(compile_kwargs={"literal_binds": True}))
        for item in session.executed
        if "pg_advisory_xact_lock" in str(item)
    )
    assert "catalog-embedding-stage:" in lock_sql
    assert "catalog-embedding-source" in lock_sql
    assert all("FOR UPDATE" not in str(item) for item in session.executed)
    assert "UPDATE ai.object_embedding" in activation_sql
    assert "content_type IN" not in activation_sql
    assert "set active=false" in activation_sql.lower()
    assert "active is true" in activation_sql.lower()


@pytest.mark.asyncio
async def test_backfill_rejects_a_nonpositive_batch_size() -> None:
    with pytest.raises(ValueError, match="batch size"):
        await backfill_catalog_embeddings(
            object(),  # type: ignore[arg-type]
            provider=_RecordingProvider(),
            model_version_id=SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
            event_id=uuid.uuid4(),
            batch_size=0,
        )


@pytest.mark.asyncio
async def test_backfill_rolls_back_a_model_contract_failure() -> None:
    event_id = uuid.uuid4()
    session = _InvalidModelSession(event_id=event_id)

    with pytest.raises(ValueError, match="model-version contract"):
        await backfill_catalog_embeddings(
            session,  # type: ignore[arg-type]
            provider=_RecordingProvider(),
            model_version_id=SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
            event_id=event_id,
        )

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_backfill_aborts_when_the_approved_catalog_changes_during_provider_io() -> (
    None
):
    event_id = uuid.uuid4()
    session = _BackfillSession(event_id=event_id, snapshot_changed=True)

    with pytest.raises(ValueError, match="approved catalog changed"):
        await backfill_catalog_embeddings(
            session,  # type: ignore[arg-type]
            provider=_RecordingProvider(),
            model_version_id=SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
            event_id=event_id,
            activate=True,
        )

    assert session.commits == 2
    assert session.rollbacks == 1
    assert len(session.added) == 2
    assert all(not row.active for row in session.added)


@pytest.mark.asyncio
async def test_backfill_commits_inactive_batches_for_retry_reuse() -> None:
    event_id = uuid.uuid4()
    session = _BackfillSession(event_id=event_id)

    with pytest.raises(RuntimeError, match="second-batch provider failure"):
        await backfill_catalog_embeddings(
            session,  # type: ignore[arg-type]
            provider=_FailOnSecondBatchProvider(),
            model_version_id=SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
            event_id=event_id,
            activate=True,
            batch_size=1,
        )

    assert session.commits == 2
    assert len(session.added) == 1
    assert session.added[0].active is False

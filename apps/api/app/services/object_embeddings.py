"""Backfill and atomically publish approved public-catalog embeddings."""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import (
    SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
    SEARCH_EMBEDDING_MODEL_VERSION_ID_V1,
)
from app.models.ai import ModelVersion, ObjectEmbedding
from app.models.exhibitor import (
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
)
from app.models.matching import Recommendable
from app.services.matching.semantic_search import QueryEmbeddingProvider

# The embeddings API caps one input at 8,192 tokens and one request at 300,000
# tokens. A byte-level BPE cannot emit more tokens than UTF-8 input bytes, so
# these conservative byte ceilings remain valid without a model tokenizer at
# runtime and leave room for provider-side framing.
MAX_EMBEDDING_SOURCE_BYTES = 8_000
MAX_EMBEDDING_REQUEST_BYTES = 240_000
MAX_EMBEDDING_REQUEST_DOCUMENTS = 256


@dataclass(frozen=True, slots=True)
class EmbeddingDocument:
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    recommendable_id: uuid.UUID
    content_type: str
    language: str
    text: str
    content_hash: bytes


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillResult:
    discovered: int
    embedded: int
    reused: int
    activated: int


def _normalize_public_part(part: str | None) -> str:
    return " ".join(part.split()) if part else ""


def _truncate_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def _public_text(*parts: str | None) -> str:
    normalized = " ".join(
        normalized_part
        for part in parts
        if (normalized_part := _normalize_public_part(part))
    )
    return _truncate_utf8(normalized, MAX_EMBEDDING_SOURCE_BYTES)


def _fair_public_text(parts: list[str | None], *, max_bytes: int) -> str:
    """Fit every source fairly instead of letting the first long field consume the tail."""

    normalized = list(
        dict.fromkeys(
            normalized_part
            for part in parts
            if (normalized_part := _normalize_public_part(part))
        )
    )
    if not normalized or max_bytes <= 0:
        return ""

    joined = " ".join(normalized)
    if len(joined.encode("utf-8")) <= max_bytes:
        return joined

    # Reserve separators, then allocate the remaining byte budget one Unicode
    # character per source per round. Short product names finish first; a single
    # oversized description therefore cannot erase every later product.
    content_budget = max(0, max_bytes - (len(normalized) - 1))
    prefixes: list[list[str]] = [[] for _ in normalized]
    offsets = [0 for _ in normalized]
    active = list(range(len(normalized)))
    while content_budget and active:
        next_active: list[int] = []
        progressed = False
        for index in active:
            value = normalized[index]
            if offsets[index] >= len(value):
                continue
            character = value[offsets[index]]
            size = len(character.encode("utf-8"))
            if size <= content_budget:
                prefixes[index].append(character)
                offsets[index] += 1
                content_budget -= size
                progressed = True
                if offsets[index] < len(value):
                    next_active.append(index)
            else:
                next_active.append(index)
        if not progressed:
            break
        active = next_active

    return _truncate_utf8(
        " ".join("".join(prefix) for prefix in prefixes if prefix),
        max_bytes,
    )


def _summary_public_text(
    *,
    company_name: str | None,
    company_summary: str | None,
    promotion_summary: str | None,
    products: list[tuple[str | None, str | None, str | None]],
) -> str:
    """Prioritize every public product name, then fairly spend the remaining budget."""

    identifiers = _fair_public_text(
        [company_name, *(product[0] for product in products)],
        max_bytes=MAX_EMBEDDING_SOURCE_BYTES,
    )
    remaining = MAX_EMBEDDING_SOURCE_BYTES - len(identifiers.encode("utf-8"))
    if remaining <= 1:
        return identifiers

    descriptions = _fair_public_text(
        [
            company_summary,
            promotion_summary,
            *(_public_text(product[1], product[2]) for product in products),
        ],
        max_bytes=remaining - 1,
    )
    return f"{identifiers} {descriptions}" if descriptions else identifiers


def _document(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    recommendable_id: uuid.UUID,
    content_type: str,
    language: str,
    text: str,
) -> EmbeddingDocument:
    return EmbeddingDocument(
        tenant_id=tenant_id,
        event_id=event_id,
        recommendable_id=recommendable_id,
        content_type=content_type,
        language=language,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).digest(),
    )


async def load_approved_catalog_documents(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    language: str,
) -> list[EmbeddingDocument]:
    """Load only approved, non-deleted public fields; never identity/profile data."""

    exhibitor_stmt = (
        select(
            Recommendable.tenant_id,
            Recommendable.event_id,
            Recommendable.recommendable_id,
            Recommendable.participation_id,
            Exhibitor.company_name,
            Exhibitor.company_summary,
            ExhibitorParticipation.promotion_summary,
        )
        .join(
            ExhibitorParticipation,
            and_(
                ExhibitorParticipation.participation_id
                == Recommendable.participation_id,
                ExhibitorParticipation.tenant_id == Recommendable.tenant_id,
                ExhibitorParticipation.event_id == Recommendable.event_id,
            ),
        )
        .join(
            Exhibitor,
            and_(
                Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id,
                Exhibitor.tenant_id == ExhibitorParticipation.tenant_id,
            ),
        )
        .where(
            Recommendable.event_id == event_id,
            Recommendable.object_type == "EXHIBITOR",
            Recommendable.active.is_(True),
            ExhibitorParticipation.participation_status == "APPROVED",
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
        )
        .order_by(Recommendable.recommendable_id)
    )
    exhibitor_rows = (await db.execute(exhibitor_stmt)).all()

    product_stmt = (
        select(
            Recommendable.tenant_id,
            Recommendable.event_id,
            Recommendable.recommendable_id,
            EventProduct.participation_id,
            Product.product_name,
            Product.product_summary,
            Product.production_method,
        )
        .join(
            EventProduct,
            and_(
                EventProduct.event_product_id == Recommendable.event_product_id,
                EventProduct.tenant_id == Recommendable.tenant_id,
                EventProduct.event_id == Recommendable.event_id,
            ),
        )
        .join(Product, Product.product_id == EventProduct.product_id)
        .join(
            ExhibitorParticipation,
            and_(
                ExhibitorParticipation.participation_id
                == EventProduct.participation_id,
                ExhibitorParticipation.tenant_id == EventProduct.tenant_id,
                ExhibitorParticipation.event_id == EventProduct.event_id,
            ),
        )
        .join(
            Exhibitor,
            and_(
                Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id,
                Exhibitor.tenant_id == ExhibitorParticipation.tenant_id,
            ),
        )
        .where(
            Recommendable.event_id == event_id,
            Recommendable.object_type == "EVENT_PRODUCT",
            Recommendable.active.is_(True),
            EventProduct.approval_status == "APPROVED",
            Product.exhibitor_id == Exhibitor.exhibitor_id,
            Product.master_approval_status == "APPROVED",
            Product.deleted_at.is_(None),
            ExhibitorParticipation.participation_status == "APPROVED",
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
        )
        .order_by(EventProduct.participation_id, Recommendable.recommendable_id)
    )
    product_rows = (await db.execute(product_stmt)).all()

    product_documents: list[EmbeddingDocument] = []
    product_sources_by_participation: dict[
        uuid.UUID, list[tuple[str | None, str | None, str | None]]
    ] = {}
    for (
        tenant_id,
        row_event_id,
        recommendable_id,
        participation_id,
        name,
        summary,
        method,
    ) in product_rows:
        text = _public_text(name, summary, method)
        if text:
            product_sources_by_participation.setdefault(participation_id, []).append(
                (name, summary, method)
            )
            product_documents.append(
                _document(
                    tenant_id=tenant_id,
                    event_id=row_event_id,
                    recommendable_id=recommendable_id,
                    content_type="PRODUCT",
                    language=language,
                    text=text,
                )
            )

    summary_documents: list[EmbeddingDocument] = []
    for (
        tenant_id,
        row_event_id,
        recommendable_id,
        participation_id,
        name,
        summary,
        promotion,
    ) in exhibitor_rows:
        text = _summary_public_text(
            company_name=name,
            company_summary=summary,
            promotion_summary=promotion,
            products=product_sources_by_participation.get(participation_id, []),
        )
        if text:
            summary_documents.append(
                _document(
                    tenant_id=tenant_id,
                    event_id=row_event_id,
                    recommendable_id=recommendable_id,
                    content_type="SUMMARY",
                    language=language,
                    text=text,
                )
            )
    return [*summary_documents, *product_documents]


def _embedding_key(
    document: EmbeddingDocument,
) -> tuple[uuid.UUID, str, bytes, str]:
    return (
        document.recommendable_id,
        document.content_type,
        document.content_hash,
        document.language,
    )


def _embedding_batches(
    documents: list[EmbeddingDocument],
    *,
    max_documents: int,
) -> Iterator[list[EmbeddingDocument]]:
    batch: list[EmbeddingDocument] = []
    batch_bytes = 0
    for document in documents:
        document_bytes = len(document.text.encode("utf-8"))
        if batch and (
            len(batch) >= max_documents
            or batch_bytes + document_bytes > MAX_EMBEDDING_REQUEST_BYTES
        ):
            yield batch
            batch = []
            batch_bytes = 0
        batch.append(document)
        batch_bytes += document_bytes
    if batch:
        yield batch


def _embedding_stage_lock_stmt(event_id: uuid.UUID, language: str):
    """Serialize same-snapshot staging without blocking unrelated providers."""

    return select(
        func.pg_advisory_xact_lock(
            func.hashtextextended(
                f"catalog-embedding-stage:{event_id}:{language}",
                0,
            )
        )
    )


def _catalog_source_lock_stmt():
    """Match the global lock used by catalog source-invalidation triggers."""

    return select(
        func.pg_advisory_xact_lock(func.hashtextextended("catalog-embedding-source", 0))
    )


async def _load_existing_embeddings(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    model_version_id: uuid.UUID,
    language: str,
    documents: list[EmbeddingDocument],
) -> dict[tuple[uuid.UUID, str, bytes, str], ObjectEmbedding]:
    hashes = [document.content_hash for document in documents]
    if not hashes:
        return {}
    rows = (
        (
            await db.execute(
                select(ObjectEmbedding).where(
                    ObjectEmbedding.event_id == event_id,
                    ObjectEmbedding.model_version_id == model_version_id,
                    ObjectEmbedding.language == language,
                    ObjectEmbedding.content_hash.in_(hashes),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        (row.recommendable_id, row.content_type, row.content_hash, row.language): row
        for row in rows
    }


async def backfill_catalog_embeddings(
    db: AsyncSession,
    *,
    provider: QueryEmbeddingProvider,
    model_version_id: uuid.UUID,
    event_id: uuid.UUID,
    language: str = "und",
    activate: bool = False,
    batch_size: int = 64,
) -> EmbeddingBackfillResult:
    """Stage immutable vectors, then optionally switch active pointers atomically.

    This command service owns its transaction boundaries and therefore requires a
    clean session. Provider I/O occurs after the read transaction commits; only the
    short source recheck, insert, and pointer swap hold a DB connection and lock.
    """

    if batch_size < 1:
        raise ValueError("embedding batch size must be positive")
    if db.in_transaction():
        raise RuntimeError("embedding backfill requires a clean database session")
    if model_version_id != SEARCH_EMBEDDING_MODEL_VERSION_ID_V1:
        raise ValueError("embedding model version requires a published contract")

    try:
        model = await db.get(ModelVersion, model_version_id)
        if model is None or model.model_type != "EMBEDDING":
            raise ValueError("embedding model version is not published")
        if model.status != "DEPLOYED":
            raise ValueError("embeddings require an immutable deployed model version")
        dimensions = int(model.config_json.get("dimensions", 0))
        if (
            dimensions != provider.dimensions
            or model.model_name != provider.model
            or model.provider != "OPENAI"
            or model.gateway_adapter != "OPENAI_DIRECT"
            or model.config_hash != SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1
            or model.config_json.get("distance") != "COSINE"
        ):
            raise ValueError(
                "embedding provider does not match the model-version contract"
            )

        documents = await load_approved_catalog_documents(
            db,
            event_id=event_id,
            language=language,
        )
        existing = await _load_existing_embeddings(
            db,
            event_id=event_id,
            model_version_id=model_version_id,
            language=language,
            documents=documents,
        )
        missing = [
            document
            for document in documents
            if _embedding_key(document) not in existing
        ]

        # Close the read transaction before external provider calls so one backfill
        # does not occupy a pooled connection while waiting on network I/O.
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    embedded = 0
    for batch in _embedding_batches(
        missing,
        max_documents=min(batch_size, MAX_EMBEDDING_REQUEST_DOCUMENTS),
    ):
        vectors = await provider.embed_many([document.text for document in batch])
        if len(vectors) != len(batch):
            raise ValueError("embedding provider returned an incomplete batch")
        for vector in vectors:
            if len(vector) != dimensions:
                raise ValueError("embedding provider returned the wrong dimensions")
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding provider returned a non-finite vector")
            if not any(value != 0.0 for value in vector):
                raise ValueError("embedding provider returned a zero vector")

        # Persist validated vectors inactive after each provider batch. A retry can
        # reuse completed work, while the public pointer remains unchanged.
        try:
            await db.execute(_embedding_stage_lock_stmt(event_id, language))
            batch_existing = await _load_existing_embeddings(
                db,
                event_id=event_id,
                model_version_id=model_version_id,
                language=language,
                documents=batch,
            )
            staged = 0
            for document, vector in zip(batch, vectors, strict=True):
                if _embedding_key(document) in batch_existing:
                    continue
                db.add(
                    ObjectEmbedding(
                        tenant_id=document.tenant_id,
                        event_id=document.event_id,
                        recommendable_id=document.recommendable_id,
                        content_type=document.content_type,
                        content_hash=document.content_hash,
                        embedding=list(vector),
                        model_version_id=model_version_id,
                        language=document.language,
                        active=False,
                    )
                )
                staged += 1
            await db.flush()
            await db.commit()
            embedded += staged
        except Exception:
            await db.rollback()
            raise

    try:
        await db.execute(_catalog_source_lock_stmt())
        latest_documents = await load_approved_catalog_documents(
            db,
            event_id=event_id,
            language=language,
        )
        if set(latest_documents) != set(documents):
            raise ValueError(
                "approved catalog changed during embedding; retry the backfill"
            )

        # Re-read under the lock: another worker may have staged the same hash
        # while this worker was waiting on the provider.
        current_existing = await _load_existing_embeddings(
            db,
            event_id=event_id,
            model_version_id=model_version_id,
            language=language,
            documents=documents,
        )
        rows_by_document: dict[EmbeddingDocument, ObjectEmbedding] = {}
        for document in documents:
            row = current_existing.get(_embedding_key(document))
            if row is None:
                raise ValueError(
                    "staged embedding changed concurrently; retry the backfill"
                )
            rows_by_document[document] = row

        activated = 0
        if activate:
            # Treat all catalog vectors as one event-language snapshot. This retires
            # stale pointers, including content types absent from the new snapshot.
            await db.execute(
                update(ObjectEmbedding)
                .where(
                    ObjectEmbedding.event_id == event_id,
                    ObjectEmbedding.language == language,
                    ObjectEmbedding.active.is_(True),
                )
                .values(active=False)
            )
            await db.flush()
            for document in documents:
                rows_by_document[document].active = True
            await db.flush()
            activated = len(documents)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return EmbeddingBackfillResult(
        discovered=len(documents),
        embedded=embedded,
        reused=len(documents) - embedded,
        activated=activated,
    )

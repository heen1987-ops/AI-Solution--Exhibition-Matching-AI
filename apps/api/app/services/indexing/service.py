"""BACKEND-INDEXING orchestration - the only code path allowed to move content
from the extraction/approval pipeline into anything search/recommendation
visible (see track GOAL, restated in ``app/models/indexing.py``'s module
docstring).

Two responsibilities, kept in two halves of this file:

1. **Gather** (``gather_exhibitor_public_facts`` / ``gather_exhibitor_
   verified_buyer_facts``): read already-approved rows from ``exhibition.*``
   plus non-superseded, visibility-scoped rows from
   ``document.published_content_version`` (app/models/extraction.py, the
   BACKEND-EXTRACTION track's operator-approval snapshot table), and shape
   them into the pure dataclasses ``app/services/indexing/document_builder.py``
   defines. Every gather query below carries its own approval filter
   in-line (``master_approval_status == 'APPROVED'`` /
   ``approval_status == 'APPROVED'`` / ``review_status == 'APPROVED'`` /
   ``participation_status == 'APPROVED'``) - unapproved rows are excluded at
   the query, not filtered out afterwards, so "pre-approval content never
   appears" is enforced structurally, not by convention.
2. **Publish/orchestrate** (``regenerate_exhibitor_documents`` /
   ``unpublish_exhibitor_documents``): write the built documents into
   ``indexing.search_document``, record an ``indexing.indexing_job``, and
   append ``indexing.cache_invalidation_event`` rows for every cache scope
   the track GOAL names (exhibitor detail, search, recommendation,
   buyer-match).

Read path (``query_search_documents``) is the single function any future
search/recommendation/kiosk consumer should call - it always filters
``status == 'ACTIVE'`` and, for VERIFIED_BUYER content, only when the caller
asserts ``is_verified_buyer=True``. That flag MUST be computed server-side
from the caller's authenticated buyer-verification status (never taken from
a request query parameter) - this is the "filter happens server-side before
returning results, never client-side only" requirement from the track brief.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Event
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    ParticipationCategory,
    Product,
    ProductAttribute,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.extraction import PublishedContentVersion
from app.models.indexing import (
    CACHE_SCOPES,
    CacheInvalidationEvent,
    IndexingJob,
    SearchDocument,
)
from app.models.ontology_refs import concept, concept_revision
from app.services.indexing.document_builder import (
    ExhibitorPublicFacts,
    PublicProductFact,
    VerifiedBuyerFacts,
    build_public_document,
    build_public_search_text,
    build_verified_buyer_document,
    build_verified_buyer_search_text,
    content_hash,
)

#: PUBLIC tier only merges document.published_content_version rows that are
#: themselves visibility='PUBLIC'. VERIFIED_BUYER tier merges anything up to
#: and including VERIFIED_BUYER clearance (a verified buyer may see
#: everything a public visitor sees, plus more) - MEETING_ACCEPTED and
#: OPERATOR_ONLY are never merged into either search-index tier (per
#: document-structuring.md §5: those tiers are reserved for narrower
#: surfaces than "the search index").
_PUBLIC_VISIBILITY: tuple[str, ...] = ("PUBLIC",)
_VERIFIED_BUYER_VISIBILITY: tuple[str, ...] = ("PUBLIC", "REGISTERED_USER", "VERIFIED_BUYER")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Ontology concept-code resolution (shared by both gather functions)
# ---------------------------------------------------------------------------


async def _resolve_concept_codes(
    db: AsyncSession, pairs: set[tuple[uuid.UUID, uuid.UUID]]
) -> list[str]:
    """(taxonomy_version_id, concept_id) pairs -> concept_code strings.

    Mirrors ``app/services/catalog_search.py``'s ``_resolve_concept_pairs``
    in the opposite direction. Short-circuits on an empty ``pairs`` set so
    callers never issue a query for nothing (also keeps this path testable
    without a fake session that understands Core-table joins - see
    ``apps/api/tests/test_indexing.py``).
    """

    if not pairs:
        return []
    stmt = (
        select(concept.c.concept_code)
        .select_from(
            concept_revision.join(concept, concept.c.concept_id == concept_revision.c.concept_id)
        )
        .where(
            tuple_(concept_revision.c.taxonomy_version_id, concept_revision.c.concept_id).in_(
                list(pairs)
            )
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(dict.fromkeys(rows))


async def _gather_published_attributes(
    db: AsyncSession, *, exhibitor_id: uuid.UUID, allowed_visibility: tuple[str, ...]
) -> dict[str, object]:
    """Exhibitor-level published_content_version rows visible at
    ``allowed_visibility`` or looser, filtered to the current (non-superseded)
    version of each attribute.

    ``PublishedContentVersion`` rows only exist once an
    ``extracted_attribute`` has reached ``review_status='APPROVED_BY_OPERATOR'``
    (app/models/extraction.py's module docstring: "BACKEND-INDEXING 트랙이
    검색/추천 색인을 채울 때 읽어야 할 유일한 표면") - so this query needs no
    separate review_status filter, only the superseded_at/visibility gates.
    Product/trade-condition-scoped published attributes are a documented
    follow-up (entity_type == 'EXHIBITOR' only for now).
    """

    stmt = select(PublishedContentVersion).where(
        PublishedContentVersion.exhibitor_id == exhibitor_id,
        PublishedContentVersion.entity_type == "EXHIBITOR",
        PublishedContentVersion.superseded_at.is_(None),
        PublishedContentVersion.visibility.in_(allowed_visibility),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.attribute_code: row.value for row in rows}


# ---------------------------------------------------------------------------
# Gather: PUBLIC tier
# ---------------------------------------------------------------------------


async def gather_exhibitor_public_facts(
    db: AsyncSession, *, event_id: uuid.UUID, exhibitor_id: uuid.UUID
) -> ExhibitorPublicFacts | None:
    """Returns ``None`` when the exhibitor has no approved, active
    participation for ``event_id`` - i.e. there is nothing publication-
    eligible yet (pre-approval content never appears, by construction).

    The event itself must also be OPEN. ``app/services/catalog_search.py``
    already enforces ``Event.event_status == 'OPEN'`` on the live public
    query (see ``_candidate_pool_stmt``), so without the same gate here a
    PREPARING or CLOSED event's exhibitors would sit in the materialized
    PUBLIC index while the live catalog hides them - two public surfaces
    disagreeing about the same approval boundary.
    """

    event_stmt = select(Event).where(Event.event_id == event_id)
    event = (await db.execute(event_stmt)).scalars().first()
    if event is None or event.event_status != "OPEN":
        return None

    exhibitor_stmt = select(Exhibitor).where(Exhibitor.exhibitor_id == exhibitor_id)
    exhibitor = (await db.execute(exhibitor_stmt)).scalars().first()
    if exhibitor is None or exhibitor.deleted_at is not None:
        return None
    if exhibitor.master_approval_status != "APPROVED":
        return None

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.exhibitor_id == exhibitor_id,
        ExhibitorParticipation.event_id == event_id,
        ExhibitorParticipation.participation_status == "APPROVED",
    )
    participation = (await db.execute(participation_stmt)).scalars().first()
    if participation is None:
        return None

    booth_stmt = select(Booth).where(
        Booth.participation_id == participation.participation_id,
        Booth.event_id == event_id,
    )
    booth = (await db.execute(booth_stmt)).scalars().first()

    event_product_stmt = select(EventProduct).where(
        EventProduct.participation_id == participation.participation_id,
        EventProduct.event_id == event_id,
        EventProduct.approval_status == "APPROVED",
    )
    event_products = (await db.execute(event_product_stmt)).scalars().all()
    product_ids = [ep.product_id for ep in event_products]

    products: list[Product] = []
    if product_ids:
        product_stmt = select(Product).where(
            Product.product_id.in_(product_ids),
            Product.master_approval_status == "APPROVED",
            Product.deleted_at.is_(None),
        )
        products = list((await db.execute(product_stmt)).scalars().all())

    category_stmt = select(ParticipationCategory).where(
        ParticipationCategory.participation_id == participation.participation_id
    )
    category_rows = (await db.execute(category_stmt)).scalars().all()
    concept_pairs = {(row.taxonomy_version_id, row.concept_id) for row in category_rows}

    if products:
        attribute_stmt = select(ProductAttribute).where(
            ProductAttribute.product_id.in_([p.product_id for p in products]),
            ProductAttribute.review_status == "APPROVED",
        )
        attribute_rows = (await db.execute(attribute_stmt)).scalars().all()
        concept_pairs |= {(row.taxonomy_version_id, row.concept_id) for row in attribute_rows}

    concept_codes = await _resolve_concept_codes(db, concept_pairs)
    published_attributes = await _gather_published_attributes(
        db, exhibitor_id=exhibitor_id, allowed_visibility=_PUBLIC_VISIBILITY
    )

    return ExhibitorPublicFacts(
        exhibitor_id=exhibitor_id,
        company_name=exhibitor.company_name,
        public_intro=exhibitor.company_summary or participation.promotion_summary,
        homepage_url=exhibitor.website_url,
        booth_number=booth.booth_number if booth is not None else None,
        products=tuple(
            PublicProductFact(
                product_id=p.product_id,
                product_name=p.product_name,
                product_summary=p.product_summary,
            )
            for p in products
        ),
        interest_concept_codes=tuple(concept_codes),
        published_attributes=published_attributes,
    )


# ---------------------------------------------------------------------------
# Gather: VERIFIED_BUYER tier
# ---------------------------------------------------------------------------


def _pick_trade_status(values: list[str], *, priority: tuple[str, ...]) -> str:
    """Collapse several trade_condition rows' status columns (one per
    approved company/product-level condition) into a single display value.

    ``priority`` orders which single status "wins" when rows disagree -
    highest-opportunity value first (YES beats CONDITIONAL beats NEGOTIABLE
    beats NO beats UNKNOWN), matching this project's "unknown/no should
    never hide a real yes" bias, without ever inventing a status a row did
    not actually report (UNKNOWN only wins when every row is UNKNOWN/absent).
    """

    present = {v for v in values if v}
    for candidate in priority:
        if candidate in present:
            return candidate
    return "UNKNOWN"


_STATUS_PRIORITY: tuple[str, ...] = ("YES", "CONDITIONAL", "NEGOTIABLE", "NO", "UNKNOWN")


async def gather_exhibitor_verified_buyer_facts(
    db: AsyncSession, *, event_id: uuid.UUID, exhibitor_id: uuid.UUID
) -> VerifiedBuyerFacts | None:
    """Returns ``None`` when the exhibitor itself is not approved (or is
    soft-deleted), or has no approved trade condition for an approved
    participation in ``event_id`` - i.e. nothing VERIFIED_BUYER-eligible
    exists yet.

    The exhibitor-level gate mirrors ``gather_exhibitor_public_facts``'s -
    without it, an exhibitor whose master record is still PENDING_REVIEW but
    whose participation/trade-condition rows happen to already be APPROVED
    would leak a VERIFIED_BUYER document ("pre-approval content never
    appears in search" must hold for both tiers, not just PUBLIC).
    """

    exhibitor_stmt = select(Exhibitor).where(Exhibitor.exhibitor_id == exhibitor_id)
    exhibitor = (await db.execute(exhibitor_stmt)).scalars().first()
    if exhibitor is None or exhibitor.deleted_at is not None:
        return None
    if exhibitor.master_approval_status != "APPROVED":
        return None

    participation_stmt = select(ExhibitorParticipation).where(
        ExhibitorParticipation.exhibitor_id == exhibitor_id,
        ExhibitorParticipation.event_id == event_id,
        ExhibitorParticipation.participation_status == "APPROVED",
    )
    participations = (await db.execute(participation_stmt)).scalars().all()
    if not participations:
        return None
    participation_ids = [p.participation_id for p in participations]

    trade_stmt = select(TradeCondition).where(
        TradeCondition.participation_id.in_(participation_ids),
        TradeCondition.approval_status == "APPROVED",
    )
    trade_conditions = (await db.execute(trade_stmt)).scalars().all()
    if not trade_conditions:
        return None

    min_values = [tc.min_order_quantity for tc in trade_conditions if tc.min_order_quantity is not None]
    max_values = [tc.max_order_quantity for tc in trade_conditions if tc.max_order_quantity is not None]

    regions: list[str] = []
    channels: list[str] = []
    trade_condition_ids = [tc.trade_condition_id for tc in trade_conditions]
    if trade_condition_ids:
        term_stmt = select(TradeConditionTerm).where(
            TradeConditionTerm.trade_condition_id.in_(trade_condition_ids)
        )
        terms = (await db.execute(term_stmt)).scalars().all()
        region_pairs = {
            (t.taxonomy_version_id, t.concept_id) for t in terms if t.term_type == "REGION"
        }
        channel_pairs = {
            (t.taxonomy_version_id, t.concept_id) for t in terms if t.term_type == "CHANNEL"
        }
        regions = await _resolve_concept_codes(db, region_pairs)
        channels = await _resolve_concept_codes(db, channel_pairs)

    today = datetime.now(UTC).date()
    new_trade_available = any(
        tc.valid_until is None or tc.valid_until >= today for tc in trade_conditions
    )

    published_attributes = await _gather_published_attributes(
        db, exhibitor_id=exhibitor_id, allowed_visibility=_VERIFIED_BUYER_VISIBILITY
    )

    return VerifiedBuyerFacts(
        exhibitor_id=exhibitor_id,
        min_order_quantity=min(min_values) if min_values else None,
        max_order_quantity=max(max_values) if max_values else None,
        regions=tuple(regions),
        channels=tuple(channels),
        oem_status=_pick_trade_status(
            [tc.oem_status for tc in trade_conditions], priority=_STATUS_PRIORITY
        ),
        private_label_status=_pick_trade_status(
            [tc.private_label_status for tc in trade_conditions], priority=_STATUS_PRIORITY
        ),
        export_status=_pick_trade_status(
            [tc.export_status for tc in trade_conditions], priority=_STATUS_PRIORITY
        ),
        new_trade_available=new_trade_available,
        # meeting_available intentionally left at the dataclass default
        # (False) here - see document_builder.py's VerifiedBuyerFacts
        # docstring for why this pipeline does not compute it yet.
        published_attributes=published_attributes,
    )


# ---------------------------------------------------------------------------
# Upsert / remove search_document rows
# ---------------------------------------------------------------------------


async def _get_search_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    tier: str,
) -> SearchDocument | None:
    """Look a document up by its FULL grain.

    The grain is (tenant_id, event_id, exhibitor_id, tier) - matching
    ``uq_search_document_exhibitor_tier``. Looking a row up by
    (exhibitor_id, tier) alone would let a regeneration for event B pick up
    event A's row and overwrite its ``event_id``, silently removing the
    exhibitor from event A's search results.
    """

    stmt = select(SearchDocument).where(
        SearchDocument.tenant_id == tenant_id,
        SearchDocument.event_id == event_id,
        SearchDocument.exhibitor_id == exhibitor_id,
        SearchDocument.tier == tier,
    )
    return (await db.execute(stmt)).scalars().first()


async def _upsert_search_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    tier: str,
    content: dict,
    search_text: str,
) -> SearchDocument:
    existing = await _get_search_document(
        db, tenant_id=tenant_id, event_id=event_id, exhibitor_id=exhibitor_id, tier=tier
    )
    digest = content_hash(content)
    if existing is not None:
        existing.content_json = content
        existing.search_text = search_text
        existing.content_hash = digest
        existing.status = "ACTIVE"
        existing.updated_at = _utcnow()
        return existing

    document = SearchDocument(
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        tier=tier,
        status="ACTIVE",
        content_json=content,
        search_text=search_text,
        content_hash=digest,
    )
    db.add(document)
    return document


async def _remove_search_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    tier: str,
) -> None:
    """Marks a tier's document REMOVED so it stops matching
    ``query_search_documents`` (the "content must actually disappear from
    search" requirement) without destroying the row (audit trail /
    idempotent re-publish - see app/models/indexing.py module docstring).

    Scoped to the full grain so unpublishing an exhibitor from event B never
    removes that same exhibitor from event A."""

    existing = await _get_search_document(
        db, tenant_id=tenant_id, event_id=event_id, exhibitor_id=exhibitor_id, tier=tier
    )
    if existing is not None and existing.status != "REMOVED":
        existing.status = "REMOVED"
        existing.updated_at = _utcnow()


# ---------------------------------------------------------------------------
# Orchestration: regenerate / unpublish + indexing_job + cache invalidation
# ---------------------------------------------------------------------------


async def _record_cache_invalidations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID | None,
    exhibitor_id: uuid.UUID,
    trigger: str,
    indexing_job_id: uuid.UUID,
) -> None:
    for scope in CACHE_SCOPES:
        db.add(
            CacheInvalidationEvent(
                tenant_id=tenant_id,
                event_id=event_id,
                exhibitor_id=exhibitor_id,
                cache_scope=scope,
                reason=trigger,
                indexing_job_id=indexing_job_id,
            )
        )


async def regenerate_exhibitor_documents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    trigger: str,
    requested_by_user_id: uuid.UUID | None = None,
) -> IndexingJob:
    """Regenerate both tiers for one exhibitor and record the job + cache
    invalidations. Called on APPROVE/PUBLISH/VISIBILITY_CHANGE (any trigger
    that could widen or change what is visible).

    A tier whose gather function returns ``None`` (nothing eligible, e.g. an
    exhibitor with an approved profile but no approved trade condition yet)
    has its existing document (if any) marked REMOVED rather than left
    stale - "visibility-changed content re-filters correctly" applies to a
    tier losing eligibility too, not just gaining it.
    """

    job = IndexingJob(
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        trigger=trigger,
        status="RUNNING",
        requested_by_user_id=requested_by_user_id,
        started_at=_utcnow(),
    )
    db.add(job)
    await db.flush()

    try:
        public_facts = await gather_exhibitor_public_facts(
            db, event_id=event_id, exhibitor_id=exhibitor_id
        )
        if public_facts is not None:
            await _upsert_search_document(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                exhibitor_id=exhibitor_id,
                tier="PUBLIC",
                content=build_public_document(public_facts),
                search_text=build_public_search_text(public_facts),
            )
        else:
            await _remove_search_document(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                exhibitor_id=exhibitor_id,
                tier="PUBLIC",
            )

        buyer_facts = await gather_exhibitor_verified_buyer_facts(
            db, event_id=event_id, exhibitor_id=exhibitor_id
        )
        if buyer_facts is not None:
            await _upsert_search_document(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                exhibitor_id=exhibitor_id,
                tier="VERIFIED_BUYER",
                content=build_verified_buyer_document(buyer_facts),
                search_text=build_verified_buyer_search_text(buyer_facts),
            )
        else:
            await _remove_search_document(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                exhibitor_id=exhibitor_id,
                tier="VERIFIED_BUYER",
            )
    except Exception as exc:
        job.status = "FAILED"
        job.error_code = type(exc).__name__
        job.completed_at = _utcnow()
        raise
    else:
        job.status = "COMPLETED"
        job.completed_at = _utcnow()

    await _record_cache_invalidations(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        trigger=trigger,
        indexing_job_id=job.indexing_job_id,
    )
    return job


async def unpublish_exhibitor_documents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    trigger: str = "UNPUBLISH",
    requested_by_user_id: uuid.UUID | None = None,
) -> IndexingJob:
    """Remove both tiers for one exhibitor (UNPUBLISH/DOCUMENT_DELETE
    triggers). Content must actually disappear from
    ``query_search_documents`` after this returns - proven by
    ``test_publish_then_unpublish_removes_content_from_search`` in
    ``apps/api/tests/test_indexing.py``."""

    job = IndexingJob(
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        trigger=trigger,
        status="RUNNING",
        requested_by_user_id=requested_by_user_id,
        started_at=_utcnow(),
    )
    db.add(job)
    await db.flush()

    await _remove_search_document(
        db, tenant_id=tenant_id, event_id=event_id, exhibitor_id=exhibitor_id, tier="PUBLIC"
    )
    await _remove_search_document(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        tier="VERIFIED_BUYER",
    )

    job.status = "COMPLETED"
    job.completed_at = _utcnow()

    await _record_cache_invalidations(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        exhibitor_id=exhibitor_id,
        trigger=trigger,
        indexing_job_id=job.indexing_job_id,
    )
    return job


# ---------------------------------------------------------------------------
# Read path - the only function search/recommendation/kiosk should call
# ---------------------------------------------------------------------------


def allowed_tiers_for(*, is_verified_buyer: bool) -> tuple[str, ...]:
    """Which ``search_document.tier`` values a caller may see.

    ``is_verified_buyer`` MUST be derived server-side from the caller's
    authenticated session/profile (e.g. a verified buyer role check), never
    trusted from a request query parameter or client-supplied flag - this is
    what makes the VERIFIED_BUYER gate a server-side filter rather than a
    client-side one.
    """

    return ("PUBLIC", "VERIFIED_BUYER") if is_verified_buyer else ("PUBLIC",)


async def query_search_documents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    is_verified_buyer: bool,
    limit: int = 50,
) -> list[SearchDocument]:
    """Only ``status == 'ACTIVE'`` documents in the caller's allowed tiers
    are ever returned - this is the single enforcement point for both
    "unpublished/deleted content disappears" and "buyer-only content is
    invisible to public search".

    ``tenant_id`` is required and leads the filter: it is the tenant boundary,
    and ``ix_search_document_event_tier_status`` leads with it too, so an
    event-only predicate could not use the index."""

    tiers = allowed_tiers_for(is_verified_buyer=is_verified_buyer)
    stmt = (
        select(SearchDocument)
        .where(
            SearchDocument.tenant_id == tenant_id,
            SearchDocument.event_id == event_id,
            SearchDocument.status == "ACTIVE",
            SearchDocument.tier.in_(tiers),
        )
        .order_by(SearchDocument.updated_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_exhibitor_search_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    tier: str,
    is_verified_buyer: bool,
    event_id: uuid.UUID | None = None,
) -> SearchDocument | None:
    """Single-exhibitor lookup (e.g. for an exhibitor-detail page cache
    refill) with the same server-side tier gate as ``query_search_documents``.

    ``tenant_id`` is required (tenant boundary). ``event_id`` is optional
    because an exhibitor-detail page may be reached without an event context;
    when it is omitted and the exhibitor participates in several events the
    most recently updated document wins."""

    if tier not in allowed_tiers_for(is_verified_buyer=is_verified_buyer):
        return None
    stmt = select(SearchDocument).where(
        SearchDocument.tenant_id == tenant_id,
        SearchDocument.exhibitor_id == exhibitor_id,
        SearchDocument.tier == tier,
        SearchDocument.status == "ACTIVE",
    )
    if event_id is not None:
        stmt = stmt.where(SearchDocument.event_id == event_id)
    stmt = stmt.order_by(SearchDocument.updated_at.desc())
    return (await db.execute(stmt)).scalars().first()

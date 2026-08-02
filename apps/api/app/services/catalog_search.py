"""Approved public catalog queries and deterministic hybrid ranking.

Combines three independent recall signals per the frozen MVP search strategy:

1. Structured filter — ontology concept codes (explicit ``category_codes`` from
   the request, plus whatever :mod:`app.services.search_query_interpreter`
   extracts from the free-text ``query``) resolved against
   ``ontology.concept``/``ontology.concept_revision`` for the event's active
   taxonomy version, then matched against ``exhibition.participation_category``
   and ``exhibition.product_attribute`` (approved attributes only).
2. Keyword search — a dependency-free Python-side token match over company
   name, promotion summary, and product names. This is the mandatory
   fallback: if ontology resolution fails or returns nothing (unknown code,
   DB hiccup, catalog unavailable), results still surface for anything the
   keyword pass finds. Search must never hard-fail just because the
   structured half is unavailable.
3. Optional semantic recall — versioned pgvector SUMMARY hits hydrated through
   the same mandatory event, approval, deletion, and booth filters.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import and_, func, literal, literal_column, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Event, EventZone
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    ParticipationCategory,
    Product,
    ProductAttribute,
)
from app.models.ontology_refs import concept, concept_revision
from app.schemas.search import SearchResult
from app.services.matching.kiosk_search_score import (
    KioskSearchSignals,
    score_kiosk_search,
)
from app.services.matching.semantic_search import NullSemanticScorer, SemanticScorer

_TOKEN_PATTERN = re.compile(
    r"[^0-9A-Za-z가-힣\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+"
)
_SEMANTIC_HYDRATION_MAX_ROWS = 5_000


def _tokens(value: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.split(value.lower()) if token]


def _score_text(query_tokens: list[str], text: str) -> tuple[float, list[str]]:
    haystack = text.lower()
    matched = [token for token in query_tokens if token in haystack]
    if not query_tokens:
        return 0.0, []
    return len(matched) / len(query_tokens), matched


def _result_reason(
    matched: Iterable[str],
    *,
    structured_hit: bool,
    semantic_hit: bool,
    open_now: bool,
) -> str:
    words = list(dict.fromkeys(matched))[:3]
    if words:
        reason = f"검색하신 '{' · '.join(words)}'와 관련된 승인 업체예요."
    elif structured_hit:
        reason = "선택한 관심 분야와 일치하는 승인 업체예요."
    elif semantic_hit:
        reason = "검색 의도와 의미상 관련된 승인 업체예요."
    else:
        reason = "선택한 관심 분야와 관련된 승인 업체예요."
    return f"{reason} 지금 부스를 운영 중이에요." if open_now else reason


async def _resolve_concept_pairs(
    db: AsyncSession, taxonomy_version_id: uuid.UUID, codes: Iterable[str]
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Resolve ontology ``concept_code`` strings to (version, concept_id) pairs.

    Only codes that are actually published for ``taxonomy_version_id`` are
    returned — an unrecognized or stale code simply resolves to nothing
    rather than raising, so the caller degrades to keyword-only search.
    """

    unique_codes = [code for code in dict.fromkeys(codes) if code]
    if not unique_codes:
        return set()

    stmt = (
        select(concept_revision.c.concept_id)
        .select_from(
            concept_revision.join(
                concept, concept.c.concept_id == concept_revision.c.concept_id
            )
        )
        .where(
            concept_revision.c.taxonomy_version_id == taxonomy_version_id,
            concept.c.concept_code.in_(unique_codes),
        )
    )
    concept_ids = (await db.execute(stmt)).scalars().all()
    return {(taxonomy_version_id, concept_id) for concept_id in concept_ids}


async def _structured_matches(
    db: AsyncSession, concept_pairs: set[tuple[uuid.UUID, uuid.UUID]]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Return (matched participation_ids, matched product_ids) for the given
    resolved (taxonomy_version_id, concept_id) pairs.

    Product attributes only count once operator/AI review has approved them
    (08 문서 24절 "AI 추출 금지·제한사항" — unapproved AI-extracted attributes
    must not drive search ranking).
    """

    pairs = list(concept_pairs)
    if not pairs:
        return set(), set()

    participation_stmt = select(ParticipationCategory.participation_id).where(
        tuple_(
            ParticipationCategory.taxonomy_version_id,
            ParticipationCategory.concept_id,
        ).in_(pairs)
    )
    product_stmt = select(ProductAttribute.product_id).where(
        tuple_(ProductAttribute.taxonomy_version_id, ProductAttribute.concept_id).in_(
            pairs
        ),
        ProductAttribute.review_status == "APPROVED",
    )
    participation_ids = set((await db.execute(participation_stmt)).scalars().all())
    product_ids = set((await db.execute(product_stmt)).scalars().all())
    return participation_ids, product_ids


def _candidate_pool_stmt(
    event_id: uuid.UUID,
    query: str = "",
    semantic_participation_ids: Iterable[uuid.UUID] = (),
    *,
    semantic_only: bool = False,
):
    """Build (without executing) the approved exhibitor/booth/product candidate
    query for ``event_id``.

    Split out from :func:`search_approved_catalog` so the mandatory public
    exposure rules — approved exhibitor/participation/product, booth not
    CLOSED — are independently verifiable (e.g. by compiling this statement
    in a test) without requiring a live database connection.
    """

    fts_document = func.to_tsvector(
        literal_column("'simple'"),
        func.concat_ws(
            " ",
            func.coalesce(Exhibitor.company_name, ""),
            func.coalesce(Exhibitor.company_summary, ""),
            func.coalesce(ExhibitorParticipation.promotion_summary, ""),
            func.coalesce(Product.product_name, ""),
        ),
    )
    fts_rank = (
        func.ts_rank_cd(
            fts_document,
            func.plainto_tsquery(literal_column("'simple'"), query),
        )
        if query.strip()
        else literal(0.0)
    ).label("fts_rank")
    semantic_ids = list(dict.fromkeys(semantic_participation_ids))

    statement = (
        select(
            Exhibitor,
            ExhibitorParticipation,
            Booth,
            Product,
            EventZone,
            fts_rank,
        )
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.exhibitor_id == Exhibitor.exhibitor_id,
        )
        .join(
            Event,
            and_(
                Event.tenant_id == ExhibitorParticipation.tenant_id,
                Event.event_id == ExhibitorParticipation.event_id,
            ),
        )
        .join(
            Booth,
            and_(
                Booth.participation_id == ExhibitorParticipation.participation_id,
                Booth.event_id == ExhibitorParticipation.event_id,
            ),
        )
        .join(
            EventProduct,
            and_(
                EventProduct.participation_id
                == ExhibitorParticipation.participation_id,
                EventProduct.event_id == ExhibitorParticipation.event_id,
                EventProduct.approval_status == "APPROVED",
            ),
        )
        .join(
            Product,
            and_(
                Product.product_id == EventProduct.product_id,
                Product.exhibitor_id == Exhibitor.exhibitor_id,
                Product.master_approval_status == "APPROVED",
                Product.deleted_at.is_(None),
            ),
        )
        .outerjoin(EventZone, EventZone.event_zone_id == Booth.zone_id)
        .where(
            ExhibitorParticipation.event_id == event_id,
            Event.event_status == "OPEN",
            ExhibitorParticipation.participation_status == "APPROVED",
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
            Booth.operating_status.in_(("OPEN", "PAUSED")),
        )
    )
    if semantic_only:
        round_robin_rank = func.row_number().over(
            partition_by=ExhibitorParticipation.participation_id,
            order_by=(fts_rank.desc(), Booth.booth_id, Product.product_id),
        )
        return (
            statement.where(ExhibitorParticipation.participation_id.in_(semantic_ids))
            # Fair fan-out sampling: every eligible semantic participation gets
            # one row before any participation gets its second row.
            .order_by(
                round_robin_rank,
                ExhibitorParticipation.participation_id,
                Booth.booth_id,
                Product.product_id,
            )
            .limit(_SEMANTIC_HYDRATION_MAX_ROWS)
        )
    return statement.order_by(
        fts_rank.desc(), ExhibitorParticipation.participation_id
    ).limit(300)


async def search_approved_catalog(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    query: str,
    category_codes: list[str],
    limit: int,
    language: str = "ko",
    semantic_scorer: SemanticScorer | None = None,
) -> list[SearchResult]:
    """Search only approved exhibitor, participation, and product records for
    an *active* (``event_status == "OPEN"``) event.

    Keyword/structured recall remains the mandatory fallback. Optional vector
    recall may add candidates, but it cannot weaken approval or event filters.
    """

    event = await db.get(Event, event_id)
    if event is None or event.event_status != "OPEN":
        # Unknown or inactive (PREPARING/CLOSED) event: no public results,
        # not an error — search must degrade gracefully, never hard-fail.
        await db.commit()
        return []
    tenant_id = event.tenant_id
    taxonomy_version_id = event.current_taxonomy_version_id

    # Finish the inexpensive event check before external provider I/O. This
    # prevents invalid event IDs from incurring embedding cost and releases the
    # pooled connection while the provider is in flight.
    await db.commit()
    scorer = semantic_scorer or NullSemanticScorer()
    prepared_semantic = await scorer.prepare(query=query)

    # --- structured filter: best-effort, never fatal to the whole search ---
    resolved_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if category_codes and taxonomy_version_id is not None:
        try:
            async with db.begin_nested():
                resolved_pairs = await _resolve_concept_pairs(
                    db, taxonomy_version_id, category_codes
                )
        except SQLAlchemyError:
            resolved_pairs = set()

    matched_participation_ids: set[uuid.UUID] = set()
    matched_product_ids: set[uuid.UUID] = set()
    if resolved_pairs:
        try:
            async with db.begin_nested():
                (
                    matched_participation_ids,
                    matched_product_ids,
                ) = await _structured_matches(db, resolved_pairs)
        except SQLAlchemyError:
            matched_participation_ids, matched_product_ids = set(), set()

    # --- vector recall: optional, fail-soft inside the scorer ---
    semantic_batch = await scorer.score(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        language=language,
        prepared=prepared_semantic,
    )
    semantic_scores = semantic_batch.participation_scores

    # --- candidate pool: approved exhibitor/participation/booth/product chain ---
    # Hydrate vector top-K independently from the capped keyword pool. A high-fanout
    # exhibitor (many products/booths) therefore cannot push another semantic-only
    # participation out of the existing 300-row keyword recall window.
    semantic_rows = []
    if semantic_scores:
        try:
            async with db.begin_nested():
                semantic_rows = (
                    await db.execute(
                        _candidate_pool_stmt(
                            event_id,
                            query,
                            semantic_scores.keys(),
                            semantic_only=True,
                        )
                    )
                ).all()
            hydrated_ids = {row[1].participation_id for row in semantic_rows}
            semantic_scores = {
                participation_id: score
                for participation_id, score in semantic_scores.items()
                if participation_id in hydrated_ids
            }
        except SQLAlchemyError:
            # Optional semantic hydration must not turn a provider/vector outage
            # into a failure of the keyword/structured fallback.
            semantic_rows = []
            semantic_scores = {}
    # Keep the normal FTS window independent as a second recall channel. Duplicate
    # rows merge below, while this can restore keyword/product evidence omitted by
    # the bounded semantic fan-out hydration.
    keyword_rows = (await db.execute(_candidate_pool_stmt(event_id, query))).all()
    rows = [*semantic_rows, *keyword_rows]

    grouped: dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]] = {}
    for row in rows:
        exhibitor, participation, booth, product, zone = row[:5]
        try:
            fts_rank = float(row[5] or 0.0)
        except (IndexError, TypeError, ValueError):
            # Unit-test fakes and non-Postgres compatibility paths may return the
            # original five-column row. Python keyword matching remains the fallback.
            fts_rank = 0.0
        key = (exhibitor.exhibitor_id, booth.booth_id)
        item = grouped.setdefault(
            key,
            {
                "exhibitor": exhibitor,
                "participation": participation,
                "booth": booth,
                "zone": zone,
                "products": [],
                "product_ids": set(),
                "fts_rank": fts_rank,
            },
        )
        item["fts_rank"] = max(float(item["fts_rank"]), fts_rank)
        products = item["products"]
        product_ids = item["product_ids"]
        if isinstance(products, list) and product.product_name not in products:
            products.append(product.product_name)
        if isinstance(product_ids, set):
            product_ids.add(product.product_id)

    query_tokens = _tokens(query)
    has_free_text = bool(query.strip())
    has_structured_filter = bool(resolved_pairs)
    ranked: list[tuple[float, SearchResult]] = []
    for item in grouped.values():
        exhibitor = item["exhibitor"]
        participation = item["participation"]
        booth = item["booth"]
        zone = item["zone"]
        products = item["products"]
        product_ids = item["product_ids"]

        searchable = " ".join(
            filter(
                None,
                [
                    exhibitor.company_name,
                    exhibitor.company_summary,
                    participation.promotion_summary,
                    *products,
                ],
            )
        )
        fallback_keyword_score, matched = _score_text(query_tokens, searchable)
        postgres_fts_score = min(max(float(item["fts_rank"]), 0.0), 1.0)
        keyword_score = max(fallback_keyword_score, postgres_fts_score)
        structured_hit = bool(
            has_structured_filter
            and (
                participation.participation_id in matched_participation_ids
                or (isinstance(product_ids, set) and product_ids & matched_product_ids)
            )
        )
        structured_score = 1.0 if structured_hit else 0.0
        semantic_score = semantic_scores.get(participation.participation_id, 0.0)

        if has_free_text:
            # Free-text search: keep anything any independent signal recognizes.
            if max(keyword_score, structured_score, semantic_score) <= 0:
                continue
        elif not structured_hit:
            # Pure category browse (no free text): structured match required.
            continue

        data_quality = min(max(float(exhibitor.data_completeness_percent) / 100, 0), 1)
        availability = 1.0 if booth.operating_status == "OPEN" else 0.35
        final_score = score_kiosk_search(
            KioskSearchSignals(
                semantic=semantic_score,
                keyword=keyword_score,
                category=structured_score,
                data_quality=data_quality,
                booth_availability=availability,
            )
        )
        ranked.append(
            (
                final_score,
                SearchResult(
                    result_id=f"exhibitor:{exhibitor.exhibitor_id}:booth:{booth.booth_id}",
                    rank=1,
                    exhibitor_id=exhibitor.exhibitor_id,
                    booth_id=booth.booth_id,
                    name=exhibitor.company_name,
                    booth_number=booth.booth_number,
                    zone_name=getattr(zone, "zone_name", None) if zone else None,
                    summary=exhibitor.company_summary
                    or participation.promotion_summary,
                    product_names=products[:4],
                    reason=_result_reason(
                        matched,
                        structured_hit=structured_hit,
                        semantic_hit=semantic_score > 0,
                        open_now=booth.operating_status == "OPEN",
                    ),
                    concepts=list(category_codes),
                    operating_status=booth.operating_status,
                    estimated_wait_minutes=booth.estimated_wait_minutes,
                    map_x=float(booth.map_x) if booth.map_x is not None else None,
                    map_y=float(booth.map_y) if booth.map_y is not None else None,
                ),
            )
        )

    ranked.sort(key=lambda pair: (-pair[0], pair[1].booth_number, pair[1].name))
    results: list[SearchResult] = []
    seen_exhibitors: set[uuid.UUID] = set()
    for _, result in ranked:
        if result.exhibitor_id in seen_exhibitors:
            continue
        seen_exhibitors.add(result.exhibitor_id)
        result.rank = len(results) + 1
        results.append(result)
        if len(results) >= limit:
            break
    return results

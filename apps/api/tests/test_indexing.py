"""Tests for BACKEND-INDEXING (WAVE 2D): the approval-gated search-index pipeline.

Covers the five scenarios the track brief demands:
  1. pre-approval content never appears in search,
  2. post-approval content appears,
  3. publish -> appears -> unpublish -> actually gone from search (not just flagged),
  4. visibility-changed content re-filters correctly (both gaining and losing a tier),
  5. VERIFIED_BUYER-only content invisible to public search (server-side tier gate).

No live Postgres is reachable in this environment. Following the project's established
convention (tests/test_extraction_api.py, tests/test_search_api.py,
tests/test_exhibition_public_api.py):
  - DDL-level guarantees (CHECK constraints, unique (exhibitor, tier), FK boundary,
    absence of any column that could carry forbidden data) are proven by compiling the
    SQLAlchemy table definitions to PostgreSQL DDL text.
  - The service layer (app/services/indexing/service.py) is exercised end-to-end against a
    small in-memory fake AsyncSession that interprets exactly the select() shapes the
    service issues (equality / in_ / is_(None) / AND, plus limit) by walking the ORM
    expression tree - intentionally narrow, not a general SQL engine.
  - Document construction (app/services/indexing/document_builder.py) is pure and tested
    without any session at all.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql import operators as sqlops
from sqlalchemy.sql.elements import Grouping, Null

from app.models.common import new_uuid7
from app.models.core import Event
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
    TradeCondition,
)
from app.models.extraction import PublishedContentVersion
from app.models.indexing import (
    CACHE_SCOPES,
    CacheInvalidationEvent,
    IndexingJob,
    SearchDocument,
)
from app.services.indexing.document_builder import (
    ExhibitorPublicFacts,
    ForbiddenPublicAttributeError,
    PublicProductFact,
    VerifiedBuyerFacts,
    build_public_document,
    build_public_search_text,
    build_verified_buyer_document,
    content_hash,
)
from app.services.indexing.service import (
    allowed_tiers_for,
    get_exhibitor_search_document,
    query_search_documents,
    regenerate_exhibitor_documents,
    unpublish_exhibitor_documents,
)

# ---------------------------------------------------------------------------
# Minimal in-memory fake AsyncSession
# ---------------------------------------------------------------------------


def _row_matches(row: Any, clause: Any) -> bool:
    if clause is None:
        return True
    if isinstance(clause, Grouping):
        return _row_matches(row, clause.element)
    if hasattr(clause, "clauses"):
        combiner = all if clause.operator is sqlops.and_ else any
        return combiner(_row_matches(row, c) for c in clause.clauses)
    op_fn = clause.operator
    col_name = clause.left.key
    actual = getattr(row, col_name, None)
    right = clause.right
    right_value = None if isinstance(right, Null) else getattr(right, "value", right)
    if op_fn is sqlops.eq:
        return actual == right_value
    if op_fn is sqlops.in_op:
        return actual in right_value
    if op_fn is sqlops.is_:
        return actual == right_value
    raise NotImplementedError(f"unsupported operator in fake session: {op_fn!r}")


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


def _pk_name(model: type) -> str:
    return next(iter(model.__table__.primary_key.columns)).key


class FakeIndexingSession:
    """Fakes just enough of AsyncSession for app/services/indexing/service.py -
    not a general SQL engine (see module docstring)."""

    def __init__(self) -> None:
        self.tables: dict[type, list[Any]] = defaultdict(list)

    def seed(self, *objs: Any) -> None:
        for obj in objs:
            self.add(obj)

    def add(self, obj: Any) -> None:
        pk = _pk_name(type(obj))
        if getattr(obj, pk, None) is None:
            setattr(obj, pk, new_uuid7())
        self.tables[type(obj)].append(obj)

    async def flush(self) -> None:  # pks assigned eagerly in add()
        return None

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = stmt.column_descriptions[0]["entity"]
        rows = [r for r in self.tables.get(entity, []) if _row_matches(r, stmt.whereclause)]
        return _FakeResult(rows)


# ---------------------------------------------------------------------------
# Fixture builders (ids + fully-approved default topology)
# ---------------------------------------------------------------------------

TENANT_ID = new_uuid7()
EVENT_ID = new_uuid7()


def _seed_event(
    db: FakeIndexingSession, event_id: uuid.UUID, *, event_status: str = "OPEN"
) -> None:
    """The public gather path requires an OPEN event (see
    ``gather_exhibitor_public_facts``), so every scenario needs a real event row."""

    db.seed(
        Event(
            event_id=event_id,
            tenant_id=TENANT_ID,
            event_code=f"BACKJU-{str(event_id)[:8]}",
            event_name="백주대간 박람회",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            event_status=event_status,
        )
    )


def _approved_world(
    db: FakeIndexingSession,
    *,
    exhibitor_status: str = "APPROVED",
    participation_status: str = "APPROVED",
    product_status: str = "APPROVED",
    event_product_status: str = "APPROVED",
    trade_status: str = "APPROVED",
    event_status: str = "OPEN",
) -> uuid.UUID:
    """Seed one exhibitor with one product, booth, and trade condition. Every
    approval knob defaults to APPROVED (and the event to OPEN); tests flip
    individual knobs to prove the corresponding gate."""

    exhibitor_id = new_uuid7()
    participation_id = new_uuid7()
    product_id = new_uuid7()
    _seed_event(db, EVENT_ID, event_status=event_status)
    db.seed(
        Exhibitor(
            exhibitor_id=exhibitor_id,
            tenant_id=TENANT_ID,
            company_name="백주양조장",
            company_summary="전통 백주 전문 양조장",
            website_url="https://baekju.example",
            master_approval_status=exhibitor_status,
            deleted_at=None,
        ),
        ExhibitorParticipation(
            participation_id=participation_id,
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            exhibitor_id=exhibitor_id,
            participation_status=participation_status,
            promotion_summary="시음 부스 운영",
        ),
        Booth(
            booth_id=new_uuid7(),
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            participation_id=participation_id,
            booth_number="A-01",
        ),
        Product(
            product_id=product_id,
            exhibitor_id=exhibitor_id,
            product_name="백주 프리미엄",
            product_summary="쌀과 누룩으로 빚은 백주",
            master_approval_status=product_status,
            deleted_at=None,
        ),
        EventProduct(
            event_product_id=new_uuid7(),
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            participation_id=participation_id,
            product_id=product_id,
            approval_status=event_product_status,
        ),
        TradeCondition(
            trade_condition_id=new_uuid7(),
            participation_id=participation_id,
            min_order_quantity=100,
            max_order_quantity=5000,
            oem_status="YES",
            private_label_status="UNKNOWN",
            export_status="CONDITIONAL",
            valid_until=None,
            approval_status=trade_status,
        ),
    )
    return exhibitor_id


async def _regenerate(db: FakeIndexingSession, exhibitor_id: uuid.UUID, trigger: str = "APPROVE"):
    return await regenerate_exhibitor_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, exhibitor_id=exhibitor_id, trigger=trigger
    )


# ---------------------------------------------------------------------------
# 1. Pre-approval content never appears
# ---------------------------------------------------------------------------


async def test_unapproved_exhibitor_never_appears_in_search() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db, exhibitor_status="PENDING_REVIEW")
    await _regenerate(db, exhibitor_id)
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False) == []
    # Not even a verified buyer may see pre-approval content.
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True) == []


async def test_unapproved_participation_never_appears_in_search() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db, participation_status="REQUESTED")
    await _regenerate(db, exhibitor_id)
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True) == []


async def test_soft_deleted_exhibitor_never_appears_in_search() -> None:
    from datetime import UTC, datetime

    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    exhibitor = db.tables[Exhibitor][0]
    exhibitor.deleted_at = datetime.now(UTC)
    await _regenerate(db, exhibitor_id)
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False) == []


async def test_unapproved_product_excluded_from_public_document() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    participation_id = db.tables[ExhibitorParticipation][0].participation_id
    draft_product_id = new_uuid7()
    db.seed(
        Product(
            product_id=draft_product_id,
            exhibitor_id=exhibitor_id,
            product_name="미승인 신제품",
            master_approval_status="DRAFT",
            deleted_at=None,
        ),
        EventProduct(
            event_product_id=new_uuid7(),
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            participation_id=participation_id,
            product_id=draft_product_id,
            approval_status="APPROVED",
        ),
    )
    await _regenerate(db, exhibitor_id)
    [doc] = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False)
    names = [p["product_name"] for p in doc.content_json["public_products"]]
    assert names == ["백주 프리미엄"]
    assert "미승인 신제품" not in doc.search_text


# ---------------------------------------------------------------------------
# 2. Post-approval content appears
# ---------------------------------------------------------------------------


async def test_approved_content_appears_in_public_search() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    job = await _regenerate(db, exhibitor_id, trigger="APPROVE")

    assert job.status == "COMPLETED"
    assert job.trigger == "APPROVE"
    [doc] = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False)
    assert doc.tier == "PUBLIC"
    assert doc.status == "ACTIVE"
    assert doc.content_json["name"] == "백주양조장"
    assert doc.content_json["booth_number"] == "A-01"
    assert doc.content_json["public_homepage"] == "https://baekju.example"
    assert doc.content_json["public_products"][0]["product_name"] == "백주 프리미엄"
    assert "백주양조장" in doc.search_text
    assert doc.content_hash.startswith("sha256:")


# ---------------------------------------------------------------------------
# 3. Publish -> appears -> unpublish -> actually gone
# ---------------------------------------------------------------------------


async def test_publish_then_unpublish_removes_content_from_search() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)

    await _regenerate(db, exhibitor_id, trigger="PUBLISH")
    assert len(await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True)) == 2

    await unpublish_exhibitor_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, exhibitor_id=exhibitor_id, trigger="UNPUBLISH"
    )
    # Gone from search for everyone - not just flagged somewhere.
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False) == []
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True) == []
    assert (
        await get_exhibitor_search_document(
            db, tenant_id=TENANT_ID, exhibitor_id=exhibitor_id, tier="PUBLIC", is_verified_buyer=False
        )
        is None
    )
    # Audit trail remains: the rows still exist, but only as REMOVED.
    assert {d.status for d in db.tables[SearchDocument]} == {"REMOVED"}


async def test_document_delete_trigger_also_removes_content() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    await unpublish_exhibitor_documents(
        db,
        tenant_id=TENANT_ID,
        event_id=EVENT_ID,
        exhibitor_id=exhibitor_id,
        trigger="DOCUMENT_DELETE",
    )
    assert await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True) == []


async def test_republish_after_unpublish_reactivates_same_row() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    await unpublish_exhibitor_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, exhibitor_id=exhibitor_id
    )
    await _regenerate(db, exhibitor_id, trigger="PUBLISH")
    docs = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True)
    assert {d.tier for d in docs} == {"PUBLIC", "VERIFIED_BUYER"}
    # One row per (exhibitor, tier) - reactivated, not duplicated.
    assert len(db.tables[SearchDocument]) == 2


# ---------------------------------------------------------------------------
# 4. Visibility change re-filters correctly
# ---------------------------------------------------------------------------


async def test_losing_trade_condition_approval_removes_buyer_tier_only() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    assert len(await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True)) == 2

    # Operator revokes the trade condition's approval.
    db.tables[TradeCondition][0].approval_status = "REJECTED"
    await _regenerate(db, exhibitor_id, trigger="VISIBILITY_CHANGE")

    docs = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True)
    assert [d.tier for d in docs] == ["PUBLIC"]


async def test_published_attribute_visibility_tiers_refilter() -> None:
    """PublishedContentVersion rows re-filter by visibility per tier:
    PUBLIC-visibility attributes reach both tiers, VERIFIED_BUYER-visibility
    attributes reach only the buyer tier, OPERATOR_ONLY and superseded rows
    reach neither."""

    from datetime import UTC, datetime

    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)

    def _pcv(code: str, value: str, visibility: str, superseded: bool = False):
        return PublishedContentVersion(
            version_id=new_uuid7(),
            extraction_id=new_uuid7(),
            tenant_id=TENANT_ID,
            exhibitor_id=exhibitor_id,
            entity_type="EXHIBITOR",
            attribute_code=code,
            value=value,
            visibility=visibility,
            version_no=1,
            superseded_at=datetime.now(UTC) if superseded else None,
        )

    db.seed(
        _pcv("brand_story", "3대째 이어온 양조", "PUBLIC"),
        _pcv("haccp_certified", "YES", "VERIFIED_BUYER"),
        _pcv("internal_note", "운영자 메모", "OPERATOR_ONLY"),
        _pcv("brand_story", "옛 버전", "PUBLIC", superseded=True),
    )
    await _regenerate(db, exhibitor_id, trigger="VISIBILITY_CHANGE")

    public_doc = await get_exhibitor_search_document(
        db, tenant_id=TENANT_ID, exhibitor_id=exhibitor_id, tier="PUBLIC", is_verified_buyer=False
    )
    buyer_doc = await get_exhibitor_search_document(
        db, tenant_id=TENANT_ID, exhibitor_id=exhibitor_id, tier="VERIFIED_BUYER", is_verified_buyer=True
    )
    assert public_doc is not None and buyer_doc is not None

    assert public_doc.content_json["published_attributes"] == {"brand_story": "3대째 이어온 양조"}
    assert buyer_doc.content_json["published_attributes"] == {
        "brand_story": "3대째 이어온 양조",
        "haccp_certified": "YES",
    }
    # OPERATOR_ONLY and superseded values reach no tier at all.
    for doc in (public_doc, buyer_doc):
        assert "internal_note" not in doc.content_json["published_attributes"]
        assert "옛 버전" not in str(doc.content_json)


# ---------------------------------------------------------------------------
# 5. Buyer-only content invisible to public search (server-side gate)
# ---------------------------------------------------------------------------


async def test_buyer_only_content_invisible_to_public_search() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)

    public_docs = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False)
    assert [d.tier for d in public_docs] == ["PUBLIC"]
    # No MOQ / OEM / trade detail anywhere in what a public caller receives.
    for doc in public_docs:
        flattened = str(doc.content_json) + doc.search_text
        assert "min_order_quantity" not in flattened
        assert "oem" not in flattened.lower()
        assert "100" not in doc.search_text

    buyer_docs = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True)
    buyer_tiers = {d.tier: d for d in buyer_docs}
    assert set(buyer_tiers) == {"PUBLIC", "VERIFIED_BUYER"}
    assert buyer_tiers["VERIFIED_BUYER"].content_json["min_order_quantity"] == 100
    assert buyer_tiers["VERIFIED_BUYER"].content_json["oem_status"] == "YES"


async def test_single_document_lookup_enforces_tier_gate() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    # A non-verified caller asking for the VERIFIED_BUYER tier gets None even
    # though the row is ACTIVE - the gate is server-side, per-call.
    assert (
        await get_exhibitor_search_document(
            db, tenant_id=TENANT_ID, exhibitor_id=exhibitor_id, tier="VERIFIED_BUYER", is_verified_buyer=False
        )
        is None
    )


async def test_regenerating_for_another_event_keeps_the_first_events_document() -> None:
    """search_document's grain is (tenant, event, exhibitor, tier).

    The same exhibitor can participate in several events. When the unique key
    and the upsert lookup were (exhibitor_id, tier) alone, regenerating for
    event B found event A's row, rewrote its ``event_id``, and the exhibitor
    silently vanished from event A's search results.
    """

    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    other_event_id = new_uuid7()
    other_participation_id = new_uuid7()
    _seed_event(db, other_event_id)
    db.seed(
        ExhibitorParticipation(
            participation_id=other_participation_id,
            tenant_id=TENANT_ID,
            event_id=other_event_id,
            exhibitor_id=exhibitor_id,
            participation_status="APPROVED",
            promotion_summary="두 번째 행사 부스",
        ),
    )

    await _regenerate(db, exhibitor_id)
    await regenerate_exhibitor_documents(
        db,
        tenant_id=TENANT_ID,
        event_id=other_event_id,
        exhibitor_id=exhibitor_id,
        trigger="APPROVE",
    )

    first = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False
    )
    second = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=other_event_id, is_verified_buyer=False
    )
    assert [d.exhibitor_id for d in first] == [exhibitor_id]
    assert [d.exhibitor_id for d in second] == [exhibitor_id]
    assert first[0] is not second[0]


async def test_unpublishing_one_event_leaves_the_other_events_document_active() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    other_event_id = new_uuid7()
    _seed_event(db, other_event_id)
    db.seed(
        ExhibitorParticipation(
            participation_id=new_uuid7(),
            tenant_id=TENANT_ID,
            event_id=other_event_id,
            exhibitor_id=exhibitor_id,
            participation_status="APPROVED",
            promotion_summary="두 번째 행사 부스",
        ),
    )
    await _regenerate(db, exhibitor_id)
    await regenerate_exhibitor_documents(
        db,
        tenant_id=TENANT_ID,
        event_id=other_event_id,
        exhibitor_id=exhibitor_id,
        trigger="APPROVE",
    )

    await unpublish_exhibitor_documents(
        db,
        tenant_id=TENANT_ID,
        event_id=other_event_id,
        exhibitor_id=exhibitor_id,
        trigger="UNPUBLISH",
    )

    assert (
        await query_search_documents(
            db, tenant_id=TENANT_ID, event_id=other_event_id, is_verified_buyer=True
        )
        == []
    )
    still_live = await query_search_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=True
    )
    assert {d.tier for d in still_live} == {"PUBLIC", "VERIFIED_BUYER"}


async def test_query_search_documents_is_scoped_to_the_calling_tenant() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    assert (
        await query_search_documents(
            db, tenant_id=new_uuid7(), event_id=EVENT_ID, is_verified_buyer=True
        )
        == []
    )


def test_allowed_tiers_is_pure_server_side_mapping() -> None:
    assert allowed_tiers_for(is_verified_buyer=False) == ("PUBLIC",)
    assert allowed_tiers_for(is_verified_buyer=True) == ("PUBLIC", "VERIFIED_BUYER")


# ---------------------------------------------------------------------------
# Indexing jobs + cache invalidation records
# ---------------------------------------------------------------------------


async def test_regenerate_records_job_and_all_cache_scopes() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    job = await _regenerate(db, exhibitor_id, trigger="APPROVE")

    jobs = db.tables[IndexingJob]
    assert len(jobs) == 1
    assert jobs[0] is job
    assert job.status == "COMPLETED"
    assert job.started_at is not None and job.completed_at is not None

    events = db.tables[CacheInvalidationEvent]
    assert {e.cache_scope for e in events} == set(CACHE_SCOPES)
    assert all(e.reason == "APPROVE" for e in events)
    assert all(e.indexing_job_id == job.indexing_job_id for e in events)


async def test_unpublish_records_job_and_all_cache_scopes() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    await unpublish_exhibitor_documents(
        db, tenant_id=TENANT_ID, event_id=EVENT_ID, exhibitor_id=exhibitor_id, trigger="UNPUBLISH"
    )
    unpublish_events = [
        e for e in db.tables[CacheInvalidationEvent] if e.reason == "UNPUBLISH"
    ]
    assert {e.cache_scope for e in unpublish_events} == set(CACHE_SCOPES)


# ---------------------------------------------------------------------------
# Pure document construction: forbidden fields structurally absent
# ---------------------------------------------------------------------------

_FORBIDDEN_FRAGMENTS = ("contact", "phone", "email", "price", "memo", "buyer_id")


def test_public_document_shape_and_forbidden_fields() -> None:
    facts = ExhibitorPublicFacts(
        exhibitor_id=new_uuid7(),
        company_name="양조장",
        public_intro="소개",
        homepage_url="https://ex.example",
        booth_number="B-02",
        products=(PublicProductFact(product_id=new_uuid7(), product_name="약주"),),
        interest_concept_codes=("STYLE.YAKJU", "STYLE.YAKJU"),
    )
    doc = build_public_document(facts)
    assert set(doc) == {
        "tier",
        "exhibitor_id",
        "name",
        "brand",
        "public_intro",
        "public_homepage",
        "booth_number",
        "public_products",
        "public_interest_codes",
        "published_attributes",
    }
    assert doc["public_interest_codes"] == ["STYLE.YAKJU"]  # deduped
    for key in doc:
        assert not any(fragment in key for fragment in _FORBIDDEN_FRAGMENTS)
    assert "약주" in build_public_search_text(facts)


def test_verified_buyer_document_shape_and_unknown_preserved() -> None:
    facts = VerifiedBuyerFacts(
        exhibitor_id=new_uuid7(),
        min_order_quantity=50,
        oem_status="UNKNOWN",
        private_label_status="UNKNOWN",
        export_status="YES",
    )
    doc = build_verified_buyer_document(facts)
    # UNKNOWN stays UNKNOWN - never coerced to YES/NO (AGENTS.md invariant).
    assert doc["oem_status"] == "UNKNOWN"
    assert doc["private_label_status"] == "UNKNOWN"
    for key in doc:
        assert not any(fragment in key for fragment in _FORBIDDEN_FRAGMENTS)


def test_content_hash_is_deterministic_and_change_sensitive() -> None:
    a = {"name": "가", "products": ["b"]}
    assert content_hash(a) == content_hash({"products": ["b"], "name": "가"})
    assert content_hash(a) != content_hash({"name": "나", "products": ["b"]})
    assert content_hash(a).startswith("sha256:")


# ---------------------------------------------------------------------------
# DDL-level guarantees (compiled to PostgreSQL, no live DB)
# ---------------------------------------------------------------------------


def _ddl(model: type) -> str:
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))


def test_search_document_ddl_constraints() -> None:
    ddl = _ddl(SearchDocument)
    assert "indexing.search_document" in ddl
    assert "tier IN ('PUBLIC', 'VERIFIED_BUYER')" in ddl
    assert "status IN ('ACTIVE', 'REMOVED')" in ddl
    assert "UNIQUE (tenant_id, event_id, exhibitor_id, tier)" in ddl
    assert "REFERENCES exhibition.exhibitor" in ddl
    # No column exists that could carry the forbidden field classes.
    for column in SearchDocument.__table__.columns:
        assert not any(fragment in column.name for fragment in _FORBIDDEN_FRAGMENTS)


def test_indexing_job_ddl_constraints() -> None:
    ddl = _ddl(IndexingJob)
    for trigger in ("APPROVE", "PUBLISH", "UNPUBLISH", "VISIBILITY_CHANGE", "DOCUMENT_DELETE"):
        assert trigger in ddl
    assert "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')" in ddl


def test_cache_invalidation_event_ddl_constraints() -> None:
    ddl = _ddl(CacheInvalidationEvent)
    assert (
        "cache_scope IN ('EXHIBITOR_DETAIL', 'SEARCH', 'RECOMMENDATION', 'BUYER_MATCH', "
        "'SEMANTIC_INDEX')" in ddl
    )
    assert "REFERENCES indexing.indexing_job" in ddl


# ---------------------------------------------------------------------------
# 6. PUBLIC-tier leak fixes (unified merge STEP 16)
# ---------------------------------------------------------------------------


def test_build_public_document_raises_on_a_trade_condition_attribute() -> None:
    """published_attributes is an untyped map, so it is the one channel through
    which a trade term could reach the anonymous PUBLIC tier. It must fail loud,
    not silently drop - matching build_embedding_input's convention."""

    facts = ExhibitorPublicFacts(
        exhibitor_id=new_uuid7(),
        company_name="양조장",
        public_intro=None,
        homepage_url=None,
        booth_number=None,
        published_attributes={"trade.payment_terms": "NET 30"},
    )
    try:
        build_public_document(facts)
    except ForbiddenPublicAttributeError as exc:
        assert exc.attribute_code == "trade.payment_terms"
    else:  # pragma: no cover - the assertion below reports the failure
        raise AssertionError("build_public_document must reject trade.payment_terms")


def test_build_public_document_raises_on_product_price() -> None:
    facts = ExhibitorPublicFacts(
        exhibitor_id=new_uuid7(),
        company_name="양조장",
        public_intro=None,
        homepage_url=None,
        booth_number=None,
        published_attributes={"product.price_krw": 18000},
    )
    try:
        build_public_document(facts)
    except ForbiddenPublicAttributeError as exc:
        assert exc.attribute_code == "product.price_krw"
    else:  # pragma: no cover
        raise AssertionError("build_public_document must reject product.price_krw")


def test_build_public_document_accepts_a_non_restricted_attribute() -> None:
    facts = ExhibitorPublicFacts(
        exhibitor_id=new_uuid7(),
        company_name="양조장",
        public_intro=None,
        homepage_url=None,
        booth_number=None,
        published_attributes={"company.description": "3대째 이어온 양조"},
    )
    doc = build_public_document(facts)
    assert doc["published_attributes"] == {"company.description": "3대째 이어온 양조"}


async def test_closed_event_removes_the_public_document() -> None:
    """catalog_search.py already requires Event.event_status == 'OPEN' on the
    live public query; the materialized index must agree, otherwise a CLOSED
    event's exhibitors stay searchable through the index."""

    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db)
    await _regenerate(db, exhibitor_id)
    assert [
        d.exhibitor_id
        for d in await query_search_documents(
            db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False
        )
    ] == [exhibitor_id]

    event = db.tables[Event][0]
    event.event_status = "CLOSED"
    await _regenerate(db, exhibitor_id, trigger="VISIBILITY_CHANGE")

    assert (
        await query_search_documents(
            db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False
        )
        == []
    )
    removed = await get_exhibitor_search_document(
        db, tenant_id=TENANT_ID, exhibitor_id=exhibitor_id, tier="PUBLIC", is_verified_buyer=False
    )
    assert removed is None


async def test_preparing_event_never_publishes_a_public_document() -> None:
    db = FakeIndexingSession()
    exhibitor_id = _approved_world(db, event_status="PREPARING")
    await _regenerate(db, exhibitor_id)
    assert (
        await query_search_documents(
            db, tenant_id=TENANT_ID, event_id=EVENT_ID, is_verified_buyer=False
        )
        == []
    )

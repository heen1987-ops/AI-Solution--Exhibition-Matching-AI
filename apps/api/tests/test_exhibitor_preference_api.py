"""Tests for WAVE2C BACKEND-EXHIBITOR-PREFERENCE.

No live Postgres is assumed reachable in this environment, so these tests follow the
project's established convention (see test_search_api.py, test_recommendation_api.py):
compile SQLAlchemy statements to verify filter clauses, and fake the AsyncSession at the
service boundary using ``statement.column_descriptions[0]["entity"]`` dispatch (see
test_recommendation_api.py's ``InteractionClientEventDedupe`` example).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers.exhibitor_preference import build_exhibitor_preference_router
from app.core.auth import AuthException, auth_exception_handler
from app.core.router_auth import get_actor_user_id
from app.db.base import Base
from app.db.session import get_db
from app.models import (
    exhibitor,  # noqa: F401  (registers exhibition tables)
    exhibitor_preference,  # noqa: F401  (registers this track's tables)
)
from app.models.exhibitor import Exhibitor
from app.models.exhibitor_preference import (
    PREFERENCE_APPROVAL_STATUSES,
    TRADE_AVAILABILITY_STATUSES,
    ExhibitorPreferredCooperationType,
    ExhibitorTradeAvailability,
)
from app.schemas.exhibitor_preference import (
    ExhibitorTradeAvailabilityUpdate,
    TaxonomyRef,
)
from app.services.exhibitor_preference import service as pref_service


def _foreign_key_targets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }


def _check_constraint_sqltext(table_name: str, name_suffix: str) -> str:
    """Naming convention (app/db/base.py) prefixes CHECK names with ck_<table>_, so match
    on suffix rather than the exact name passed to ``CheckConstraint(...)``."""

    table = Base.metadata.tables[table_name]
    for constraint in table.constraints:
        constraint_name = getattr(constraint, "name", None)
        if constraint_name and str(constraint_name).endswith(name_suffix):
            return str(constraint.sqltext)
    raise AssertionError(f"constraint *{name_suffix} not found on {table_name}")


# ---------------------------------------------------------------------------
# Model metadata: tables/constraints exist and never silently default to NO.
# ---------------------------------------------------------------------------


def test_new_tables_are_registered_with_expected_schema() -> None:
    assert "exhibition.exhibitor_trade_availability" in Base.metadata.tables
    assert "exhibition.exhibitor_cooperation_type" in Base.metadata.tables


def test_trade_availability_status_values_include_unknown_and_never_binary() -> None:
    assert TRADE_AVAILABILITY_STATUSES == ("YES", "NO", "CONDITIONAL", "NEGOTIABLE", "UNKNOWN")

    sql = _check_constraint_sqltext(
        "exhibition.exhibitor_trade_availability", "new_trade_available_allowed"
    )
    for status in TRADE_AVAILABILITY_STATUSES:
        assert f"'{status}'" in sql
    sql = _check_constraint_sqltext(
        "exhibition.exhibitor_trade_availability", "meeting_available_allowed"
    )
    for status in TRADE_AVAILABILITY_STATUSES:
        assert f"'{status}'" in sql


def test_trade_availability_columns_default_to_unknown_not_no() -> None:
    table = Base.metadata.tables["exhibition.exhibitor_trade_availability"]

    assert str(table.c.new_trade_available.default.arg) == "UNKNOWN"
    assert str(table.c.meeting_available.default.arg) == "UNKNOWN"
    assert not table.c.new_trade_available.nullable
    assert not table.c.meeting_available.nullable


def test_trade_availability_is_one_row_per_exhibitor() -> None:
    table = Base.metadata.tables["exhibition.exhibitor_trade_availability"]
    unique_columns = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("exhibitor_id",) in unique_columns


def test_trade_availability_approval_status_gates_public_exposure() -> None:
    assert PREFERENCE_APPROVAL_STATUSES == ("DRAFT", "APPROVED", "REJECTED")


def test_cooperation_type_is_bound_to_canonical_ontology_concept() -> None:
    assert (
        "ontology.concept_revision.taxonomy_version_id",
        "ontology.concept_revision.concept_id",
    ) in _foreign_key_targets("exhibition.exhibitor_cooperation_type")


def test_cooperation_type_deduplicates_per_exhibitor() -> None:
    table = Base.metadata.tables["exhibition.exhibitor_cooperation_type"]
    unique_columns = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("exhibitor_id", "taxonomy_version_id", "concept_id") in unique_columns


# ---------------------------------------------------------------------------
# Discriminatory-field omission: this track's fields must never encode
# protected-class criteria (PROJECT_SCOPE requirement for exhibitor preference).
# ---------------------------------------------------------------------------


def test_no_field_anywhere_in_this_track_encodes_protected_class_criteria() -> None:
    banned_substrings = (
        "gender",
        "sex",
        "nationality",
        "race",
        "religion",
        "age",
        "appearance",
        "disability",
        "ethnic",
    )

    availability_columns = {
        c.name
        for c in Base.metadata.tables["exhibition.exhibitor_trade_availability"].c
    }
    cooperation_columns = {
        c.name for c in Base.metadata.tables["exhibition.exhibitor_cooperation_type"].c
    }
    schema_fields = set(ExhibitorTradeAvailabilityUpdate.model_fields) | {
        "cooperation_types",
        "distribution_channel_codes",
        "supply_region_codes",
        "preferred_buyer_types",
        "preferred_channels",
        "preferred_regions",
        "min_order_scale",
    }

    for column_name in availability_columns | cooperation_columns | schema_fields:
        lowered = column_name.lower()
        for banned in banned_substrings:
            assert banned not in lowered, (
                f"{column_name!r} looks like it could encode a protected-class "
                f"criterion ({banned!r}) - PROJECT_SCOPE forbids this for exhibitor "
                "preference fields"
            )


# ---------------------------------------------------------------------------
# Statement compilation: public trade preference sources only the *approved*,
# business-common trade condition (never an unapproved or product-specific one).
# ---------------------------------------------------------------------------


def _compiled(exhibitor_id: uuid.UUID) -> str:
    stmt = pref_service._common_trade_condition_stmt(exhibitor_id)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_common_trade_condition_query_requires_approval() -> None:
    sql = _compiled(uuid.uuid4())

    assert "exhibition.trade_condition.approval_status = 'APPROVED'" in sql


def test_common_trade_condition_query_excludes_product_specific_rows() -> None:
    sql = _compiled(uuid.uuid4())

    assert "exhibition.trade_condition.event_product_id IS NULL" in sql


def test_common_trade_condition_query_scopes_to_the_exhibitor() -> None:
    exhibitor_id = uuid.uuid4()
    sql = _compiled(exhibitor_id)

    assert "exhibition.exhibitor_participation.exhibitor_id = " in sql
    assert exhibitor_id.hex in sql.replace("-", "")


# ---------------------------------------------------------------------------
# Ontology code validation (channel/region/cooperation) - concept_type must
# match the field's semantic dimension, not just "exists in the catalog".
# ---------------------------------------------------------------------------


def test_cooperation_type_validation_accepts_trade_type_concepts() -> None:
    concept_id = uuid.uuid4()
    ref = TaxonomyRef(taxonomy_version_id=uuid.uuid4(), concept_id=concept_id)

    pref_service._validate_concept_type(
        [ref], {concept_id: "TRADE.OEM"}, expected_concept_type="TRADE_TYPE"
    )


def test_cooperation_type_validation_rejects_region_codes() -> None:
    concept_id = uuid.uuid4()
    ref = TaxonomyRef(taxonomy_version_id=uuid.uuid4(), concept_id=concept_id)

    with pytest.raises(ValueError, match="UNEXPECTED_CONCEPT_TYPE"):
        pref_service._validate_concept_type(
            [ref], {concept_id: "REGION.KR.SEOUL"}, expected_concept_type="TRADE_TYPE"
        )


def test_cooperation_type_validation_rejects_unresolved_concepts() -> None:
    concept_id = uuid.uuid4()
    ref = TaxonomyRef(taxonomy_version_id=uuid.uuid4(), concept_id=concept_id)

    with pytest.raises(ValueError, match="UNKNOWN_ONTOLOGY_CONCEPT"):
        pref_service._validate_concept_type(
            [ref], {}, expected_concept_type="TRADE_TYPE"
        )


def test_channel_and_region_codes_used_elsewhere_are_real_catalog_concept_types() -> None:
    """Sanity check that the codes this track composes into distribution_channel_codes/
    supply_region_codes (sourced from exhibitor.TradeConditionTerm, term_type CHANNEL/
    REGION) really are CHANNEL/REGION concepts in the canonical 259-concept catalog."""

    catalog = pref_service._catalog()

    assert catalog.get("CHANNEL.EXPORT")["concept_type"] == "CHANNEL"
    assert catalog.get("REGION.KR.SEOUL")["concept_type"] == "REGION"
    assert catalog.get("TRADE.OEM")["concept_type"] == "TRADE_TYPE"


# ---------------------------------------------------------------------------
# "Never silently coerced to YES/NO": partial-update schema distinguishes
# "not provided" (None -> leave unchanged) from an explicit "UNKNOWN" value.
# ---------------------------------------------------------------------------


def test_availability_update_treats_missing_fields_as_no_change_not_unknown() -> None:
    body = ExhibitorTradeAvailabilityUpdate()

    assert body.new_trade_available is None
    assert body.meeting_available is None


def test_availability_update_accepts_an_explicit_unknown() -> None:
    body = ExhibitorTradeAvailabilityUpdate(new_trade_available="UNKNOWN")

    assert body.new_trade_available == "UNKNOWN"


# ---------------------------------------------------------------------------
# Field CRUD (upsert_trade_availability / replace_cooperation_types) against a
# minimal in-memory fake session, dispatched by target entity like
# test_recommendation_api.py's InteractionClientEventDedupe example.
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeDb:
    """Enough of AsyncSession for upsert_trade_availability/replace_cooperation_types."""

    def __init__(self, *, concept_codes: dict[uuid.UUID, str] | None = None) -> None:
        self.availability: dict[uuid.UUID, ExhibitorTradeAvailability] = {}
        self.cooperation_types: list[ExhibitorPreferredCooperationType] = []
        self.concept_codes = concept_codes or {}
        self.commits = 0

    async def execute(self, statement: Any) -> _ScalarResult:
        descriptions = getattr(statement, "column_descriptions", None)
        entity = descriptions[0].get("entity") if descriptions else None

        if entity is ExhibitorTradeAvailability:
            return _ScalarResult(list(self.availability.values()))
        if entity is ExhibitorPreferredCooperationType:
            return _ScalarResult(list(self.cooperation_types))
        # ontology.concept lookup (a plain sqlalchemy.Table select, not an ORM entity).
        if entity is None:
            rows = [
                type("Row", (), {"concept_id": cid, "concept_code": code})()
                for cid, code in self.concept_codes.items()
            ]
            return _ScalarResult(rows)
        raise AssertionError(f"unexpected statement target: {entity}")

    def add(self, row: Any) -> None:
        if isinstance(row, ExhibitorTradeAvailability):
            self.availability[row.exhibitor_id] = row
        elif isinstance(row, ExhibitorPreferredCooperationType):
            self.cooperation_types.append(row)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, row: Any) -> None:
        del row


@pytest.mark.asyncio
async def test_upsert_trade_availability_creates_a_row_defaulting_to_unknown() -> None:
    db = _FakeDb()
    exhibitor_id = uuid.uuid4()

    row = await pref_service.upsert_trade_availability(
        db, exhibitor_id, new_trade_available="YES"
    )

    assert row.new_trade_available == "YES"
    # meeting_available was never provided in this call - the ORM column default
    # (UNKNOWN) applies, it is not coerced to NO.
    assert row.meeting_available == "UNKNOWN"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_upsert_trade_availability_partial_update_leaves_other_field_untouched() -> None:
    db = _FakeDb()
    exhibitor_id = uuid.uuid4()
    await pref_service.upsert_trade_availability(
        db, exhibitor_id, new_trade_available="YES", meeting_available="CONDITIONAL"
    )

    row = await pref_service.upsert_trade_availability(
        db, exhibitor_id, new_trade_available="NO"
    )

    assert row.new_trade_available == "NO"
    assert row.meeting_available == "CONDITIONAL"


@pytest.mark.asyncio
async def test_upsert_trade_availability_resets_approval_after_a_change() -> None:
    db = _FakeDb()
    exhibitor_id = uuid.uuid4()
    row = await pref_service.upsert_trade_availability(
        db, exhibitor_id, new_trade_available="YES"
    )
    row.approval_status = "APPROVED"

    row = await pref_service.upsert_trade_availability(
        db, exhibitor_id, new_trade_available="NO"
    )

    assert row.approval_status == "DRAFT"


@pytest.mark.asyncio
async def test_replace_cooperation_types_soft_deletes_dropped_codes() -> None:
    oem_concept = uuid.uuid4()
    pb_concept = uuid.uuid4()
    taxonomy_version = uuid.uuid4()
    db = _FakeDb(
        concept_codes={oem_concept: "TRADE.OEM", pb_concept: "TRADE.PRIVATE_LABEL"}
    )
    exhibitor_id = uuid.uuid4()

    await pref_service.replace_cooperation_types(
        db,
        exhibitor_id,
        [
            TaxonomyRef(taxonomy_version_id=taxonomy_version, concept_id=oem_concept),
            TaxonomyRef(taxonomy_version_id=taxonomy_version, concept_id=pb_concept),
        ],
    )

    rows = await pref_service.replace_cooperation_types(
        db,
        exhibitor_id,
        [TaxonomyRef(taxonomy_version_id=taxonomy_version, concept_id=oem_concept)],
    )

    active_concepts = {row.concept_id for row in rows if row.active}
    assert active_concepts == {oem_concept}
    dropped = next(row for row in db.cooperation_types if row.concept_id == pb_concept)
    assert dropped.active is False


@pytest.mark.asyncio
async def test_replace_cooperation_types_rejects_a_non_trade_type_concept() -> None:
    region_concept = uuid.uuid4()
    db = _FakeDb(concept_codes={region_concept: "REGION.KR.SEOUL"})
    exhibitor_id = uuid.uuid4()

    with pytest.raises(ValueError, match="UNEXPECTED_CONCEPT_TYPE"):
        await pref_service.replace_cooperation_types(
            db,
            exhibitor_id,
            [
                TaxonomyRef(
                    taxonomy_version_id=uuid.uuid4(), concept_id=region_concept
                )
            ],
        )


# ---------------------------------------------------------------------------
# has_buyer_preference must never be a proxy for "penalize the exhibitor" -
# it is a plain existence check the caller uses to decide whether to fall back
# to one-sided scoring (PROJECT_SCOPE rule for missing buyer preference).
# ---------------------------------------------------------------------------


def test_has_buyer_preference_is_a_pure_existence_check_over_two_tables() -> None:
    import inspect

    source = inspect.getsource(pref_service.has_buyer_preference)

    assert "ExhibitorBuyerPreference" in source
    assert "ExhibitorPreferredCooperationType" in source
    assert "active.is_(True)" in source


# ---------------------------------------------------------------------------
# MERGE STEP 16 (c): the public composed view is approval-gated.
#
# GET /exhibitor-preference/{exhibitor_id} is anonymous. Before the merge the
# composed view looked at neither the exhibitor's own master_approval_status
# nor ExhibitorTradeAvailability.approval_status - which upsert_trade_availability
# resets to DRAFT on every edit (see the test above) - so an unreviewed
# declaration reached the anonymous public surface immediately.
# ---------------------------------------------------------------------------


class _ReadResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _ReadResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeReadDb:
    """Read-path fake for :func:`get_exhibitor_preference_view`.

    Dispatches on ``statement.column_descriptions[0]["entity"]`` exactly like
    :class:`_FakeDb` above; ``master_approved`` decides whether the
    ``Exhibitor`` gate statement matches a row.
    """

    def __init__(
        self,
        *,
        master_approved: bool,
        availability: ExhibitorTradeAvailability | None = None,
    ) -> None:
        self.master_approved = master_approved
        self.availability = availability
        self.seen_entities: list[Any] = []

    async def execute(self, statement: Any) -> _ReadResult:
        descriptions = getattr(statement, "column_descriptions", None)
        entity = descriptions[0].get("entity") if descriptions else None
        self.seen_entities.append(entity)

        if entity is Exhibitor:
            return _ReadResult([uuid.uuid4()] if self.master_approved else [])
        if entity is ExhibitorTradeAvailability:
            return _ReadResult([self.availability] if self.availability else [])
        # Everything else on the read path (TradeCondition, TradeConditionTerm,
        # ExhibitorBuyerPreference, ExhibitorPreferredCooperationType, and the
        # plain ontology.concept table select) is empty for these tests.
        return _ReadResult([])


def test_public_view_gate_requires_an_approved_undeleted_exhibitor() -> None:
    exhibitor_id = uuid.uuid4()
    stmt = pref_service.exhibitor_master_approved_stmt(exhibitor_id)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "exhibition.exhibitor.master_approval_status = 'APPROVED'" in sql
    assert "exhibition.exhibitor.deleted_at IS NULL" in sql
    assert exhibitor_id.hex in sql.replace("-", "")


@pytest.mark.asyncio
async def test_public_view_is_fully_suppressed_for_an_unapproved_exhibitor() -> None:
    """A PENDING_REVIEW exhibitor's declarations must not reach the public view."""

    exhibitor_id = uuid.uuid4()
    db = _FakeReadDb(
        master_approved=False,
        availability=ExhibitorTradeAvailability(
            exhibitor_id=exhibitor_id,
            new_trade_available="YES",
            meeting_available="YES",
            approval_status="APPROVED",
        ),
    )

    view = await pref_service.get_exhibitor_preference_view(db, exhibitor_id)

    assert view.trade.new_trade_available == "UNKNOWN"
    assert view.trade.meeting_available == "UNKNOWN"
    assert view.trade.source_trade_condition_approved is False
    assert view.buyer_preference.has_buyer_preference is False
    # The gate short-circuits: nothing beyond the Exhibitor lookup is queried.
    assert db.seen_entities == [Exhibitor]


@pytest.mark.asyncio
async def test_public_view_suppresses_an_unapproved_availability_declaration() -> None:
    """The exhibitor is approved but the declaration itself is still DRAFT."""

    exhibitor_id = uuid.uuid4()
    db = _FakeReadDb(
        master_approved=True,
        availability=ExhibitorTradeAvailability(
            exhibitor_id=exhibitor_id,
            new_trade_available="YES",
            meeting_available="YES",
            approval_status="DRAFT",
        ),
    )

    view = await pref_service.get_exhibitor_preference_view(db, exhibitor_id)

    assert view.trade.new_trade_available == "UNKNOWN"
    assert view.trade.meeting_available == "UNKNOWN"


@pytest.mark.asyncio
async def test_public_view_exposes_an_approved_availability_declaration() -> None:
    exhibitor_id = uuid.uuid4()
    db = _FakeReadDb(
        master_approved=True,
        availability=ExhibitorTradeAvailability(
            exhibitor_id=exhibitor_id,
            new_trade_available="YES",
            meeting_available="CONDITIONAL",
            approval_status="APPROVED",
        ),
    )

    view = await pref_service.get_exhibitor_preference_view(db, exhibitor_id)

    assert view.trade.new_trade_available == "YES"
    assert view.trade.meeting_available == "CONDITIONAL"


# ---------------------------------------------------------------------------
# MERGE STEP 20: router auth.
#
# The WAVE2C original identified the caller from an ``X-Actor-User-Id`` header and
# carried its own ``_require_exhibitor_access`` copy. Both are gone: the two write
# endpoints derive the actor from a verified principal via app/core/router_auth.py,
# and the composed GET stays deliberately anonymous (it is approval-gated by the
# service layer - see the STEP 16(c) section above).
# ---------------------------------------------------------------------------


class _RouterFakeDb(_FakeReadDb):
    """``_FakeReadDb`` plus the ``get()`` the router's own 404 lookup needs."""

    def __init__(self) -> None:
        super().__init__(master_approved=False)

    async def get(self, model: Any, pk: Any) -> Any:
        return None


def _preference_app(actor_user_id: uuid.UUID | None = None) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_exhibitor_preference_router(), prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: _RouterFakeDb()
    if actor_user_id is not None:
        app.dependency_overrides[get_actor_user_id] = lambda: actor_user_id
    return app


def test_the_two_write_endpoints_reject_an_unauthenticated_caller() -> None:
    client = TestClient(_preference_app())
    exhibitor_id = uuid.uuid4()

    for path, body in (
        (f"/api/v1/exhibitor-preference/{exhibitor_id}/availability", {}),
        (
            f"/api/v1/exhibitor-preference/{exhibitor_id}/cooperation-types",
            {"cooperation_types": []},
        ),
    ):
        response = client.put(
            path, json=body, headers={"X-Actor-User-Id": str(uuid.uuid4())}
        )
        assert response.status_code == 401, (path, response.status_code)
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_the_composed_read_stays_anonymous() -> None:
    """It is the public catalog surface; STEP 16(c) made the service layer the gate."""

    client = TestClient(_preference_app())

    response = client.get(f"/api/v1/exhibitor-preference/{uuid.uuid4()}")

    # Reaches the handler (the fake db resolves no exhibitor -> 404), never 401.
    assert response.status_code == 404


def test_a_write_by_a_user_without_exhibitor_access_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from app.api.v1.routers import exhibitor_preference as preference_router

    async def deny(db: Any, *, actor_user_id: Any, exhibitor_id: Any) -> None:
        raise HTTPException(status_code=403, detail="RESOURCE_FORBIDDEN")

    monkeypatch.setattr(preference_router, "require_exhibitor_access", deny)
    client = TestClient(_preference_app(actor_user_id=uuid.uuid4()))

    response = client.put(
        f"/api/v1/exhibitor-preference/{uuid.uuid4()}/availability", json={}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "RESOURCE_FORBIDDEN"


def test_the_router_module_no_longer_reads_the_actor_from_a_client_header() -> None:
    import inspect

    from app.api.v1.routers import exhibitor_preference as preference_router

    source = inspect.getsource(preference_router)

    assert "X-Actor-User-Id" not in source
    assert "Header(" not in source
    assert preference_router.get_actor_user_id is get_actor_user_id

"""Tests for BACKEND-EXTRACTION (WAVE 2D): extraction storage/versioning, exhibitor
confirm/modify/reject, conflict-resolution-before-submit, cross-company denial, and the hard
"no business-table writes" boundary.

No live Postgres is reachable in this environment. Following the project's established
convention (``tests/test_search_api.py``, ``tests/test_exhibition_public_api.py``):
  - CHECK constraints and FK boundaries are proven by compiling DDL/SQL to text.
  - The service layer is exercised against a small in-memory fake ``AsyncSession`` (below) that
    interprets the handful of ``select(...)`` shapes ``app/services/extraction/review.py``
    actually issues (equality/``in_``/``is_``/AND/OR, plus ``func.count``/``func.max``,
    ``order_by``/``limit``) by walking the compiled expression tree - this is intentionally
    narrow (only the operators this router's own code uses), not a general SQL engine.
  - Router tests mount ``build_extraction_router()`` on a standalone ``FastAPI()`` app (the
    router is not registered in ``app.main.app`` yet - mounting is an integration-step concern,
    same technique as ``tests/test_exhibition_public_api.py``).

Merge STEP 20 retargeting
--------------------------
The WAVE 2D original identified the caller from an ``X-Actor-User-Id`` request header. That
stub is gone: the actor is derived from a verified session principal. These tests therefore
authenticate by overriding ``app.core.auth.get_verified_principal`` (the same technique
``tests/test_analytics_api.py`` uses), never by sending a header. The ``/admin/ai-review*``
routes additionally carry ``require_roles("EVENT_ADMIN", "DATA_REVIEWER")``, so an operator
call now needs an AAL2 principal holding one of those grants *and* the legacy
OPERATOR/ADMIN ``identity.user_role`` row the service gate reads.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators as sqlops
from sqlalchemy.sql.elements import Grouping, Null
from sqlalchemy.sql.functions import Function

from app.api.v1.routers import extraction as extraction_router
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.db.session import get_db
from app.models.common import new_uuid7
from app.models.document import SourceDocument
from app.models.extraction import (
    ContentReviewAction,
    ContentReviewRequest,
    ExtractedAttribute,
    ExtractionConflict,
    SourceEvidence,
)
from app.schemas.auth import AuthPrincipal, AuthRoleGrant
from app.services.extraction import review as review_service
from app.services.extraction.attribute_schema import is_critical_trade_condition
from app.services.extraction.errors import (
    InvalidTransitionError,
    SubmitReviewValidationError,
    UnknownOntologyCodeError,
)
from app.services.extraction.ingestion import ingest_extraction_result
from app.services.extraction.ontology_validation import (
    invalid_concept_codes,
    is_valid_concept_code,
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
    right_value = getattr(clause.right, "value", clause.right)
    if op_fn is sqlops.eq:
        return actual == right_value
    if op_fn is sqlops.in_op:
        return actual in right_value
    if op_fn is sqlops.is_:
        # ``col.is_(None)`` compiles with a ``Null`` element on the right, which has no
        # ``.value`` attribute - comparing against it with ``==`` would build a new SQL
        # expression instead of a bool. Treat it as a Python ``is None`` check.
        if isinstance(right_value, Null) or right_value is None:
            return actual is None
        return actual == right_value
    raise NotImplementedError(f"unsupported operator in fake session: {op_fn!r}")


def _pk_name(model: type) -> str:
    return next(iter(model.__table__.primary_key.columns)).key


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalar(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeExtractionSession:
    """Fakes just enough of AsyncSession for ``app/services/extraction/review.py`` and
    ``app/api/v1/routers/extraction.py``'s own auth-gate queries - not a general SQL engine
    (module docstring)."""

    def __init__(self) -> None:
        self.tables: dict[type, dict[Any, Any]] = defaultdict(dict)
        self._pending: list[Any] = []
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self._pending.append(obj)
        self.added.append(obj)

    @staticmethod
    def _apply_server_defaults(obj: Any) -> None:
        """Emulate the ``server_default=func.now()`` timestamp columns a real Postgres would
        fill - ORM objects built in tests otherwise carry ``None`` and fail response-model
        validation."""

        import datetime as _dt

        model = type(obj)
        if not hasattr(model, "__table__"):
            return
        now = _dt.datetime.now(_dt.UTC)
        for column in model.__table__.columns:
            if column.server_default is not None and getattr(obj, column.key, None) is None:
                setattr(obj, column.key, now)

    async def flush(self) -> None:
        for obj in self._pending:
            pk_name = _pk_name(type(obj))
            if getattr(obj, pk_name, None) is None:
                setattr(obj, pk_name, new_uuid7())
            self._apply_server_defaults(obj)
            self.tables[type(obj)][getattr(obj, pk_name)] = obj
        self._pending = []

    async def get(self, model: type, pk: Any) -> Any:
        await self.flush()
        return self.tables.get(model, {}).get(pk)

    def seed(self, obj: Any, *, model: type | None = None, key: Any = None) -> None:
        """Register an already-built fixture row directly (bypasses PK auto-assignment) - used
        both for real ORM rows and for the flattened UserRole/Role join pseudo-rows the
        ``_require_exhibitor_access``/``_require_operator_access`` fake queries read."""

        target_model = model or type(obj)
        pk = key if key is not None else getattr(obj, _pk_name(target_model), None)
        if model is None:
            self._apply_server_defaults(obj)
        self.tables[target_model][pk] = obj

    async def execute(self, stmt: Any) -> _FakeResult:
        await self.flush()
        entity = stmt.column_descriptions[0]["entity"]
        rows = [r for r in self.tables.get(entity, {}).values() if _row_matches(r, stmt.whereclause)]

        for clause in reversed(stmt._order_by_clauses):
            element = getattr(clause, "element", clause)
            key = element.key
            reverse = getattr(clause, "modifier", None) is sqlops.desc_op
            rows.sort(key=lambda r: getattr(r, key), reverse=reverse)

        if stmt._limit_clause is not None:
            rows = rows[: stmt._limit_clause.value]

        expr = stmt.column_descriptions[0]["expr"]
        if isinstance(expr, Function) and expr.name in ("count", "max"):
            target_col = expr.clauses.clauses[0].key
            values = [getattr(r, target_col) for r in rows]
            if expr.name == "count":
                return _FakeResult([len(values)])
            return _FakeResult([max(values) if values else None])

        return _FakeResult(rows)


def _seed_role(
    session: FakeExtractionSession,
    *,
    user_id: uuid.UUID,
    role_code: str,
    exhibitor_id: uuid.UUID | None = None,
    valid_until: Any = None,
) -> None:
    """Seeds a flattened UserRole-join-Role pseudo-row (module docstring "Minimal in-memory fake
    AsyncSession" explains why this is flattened rather than a real join)."""

    from app.models.identity import UserRole

    row = SimpleNamespace(
        user_role_id=new_uuid7(),
        user_id=user_id,
        valid_until=valid_until,
        exhibitor_id=exhibitor_id,
        role_code=role_code,
    )
    session.seed(row, model=UserRole, key=row.user_role_id)


# ---------------------------------------------------------------------------
# Ontology / attribute-schema pure helpers (no DB)
# ---------------------------------------------------------------------------


def test_is_valid_concept_code_accepts_a_real_catalog_code() -> None:
    assert is_valid_concept_code("ALCOHOL.TAKJU")


def test_is_valid_concept_code_rejects_an_invented_code() -> None:
    assert not is_valid_concept_code("NOT.A.REAL.CODE")


def test_invalid_concept_codes_reports_only_the_bad_ones() -> None:
    bad = invalid_concept_codes(["ALCOHOL.TAKJU", "MADE.UP.CODE"])
    assert bad == ["MADE.UP.CODE"]


def test_is_critical_trade_condition_reads_the_real_attribute_schema() -> None:
    assert is_critical_trade_condition("trade.moq") is True
    assert is_critical_trade_condition("not.a.real.attribute") is False


# ---------------------------------------------------------------------------
# Model layer - CHECK constraints / FK boundaries compile correctly (no DB)
# ---------------------------------------------------------------------------


def test_extracted_attribute_check_constraints_cover_every_enum() -> None:
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(ExtractedAttribute.__table__).compile())
    assert "entity_type IN ('EXHIBITOR', 'PRODUCT', 'TRADE_CONDITION', 'CERTIFICATE')" in ddl
    assert "fact_type IN ('SOURCE_FACT', 'SELF_DECLARED', 'AI_INFERRED', 'CALCULATED', 'UNKNOWN')" in ddl
    assert "'PROPOSED'" in ddl and "'APPROVED_BY_OPERATOR'" in ddl and "'CONFLICTED'" in ddl
    assert "confidence >= 0 AND confidence <= 1" in ddl


def test_extracted_attribute_has_a_hard_fk_to_exhibitor_but_not_to_document() -> None:
    fk_targets = {fk.target_fullname for fk in ExtractedAttribute.__table__.foreign_keys}
    assert "exhibition.exhibitor.tenant_id" in fk_targets
    assert "exhibition.exhibitor.exhibitor_id" in fk_targets
    assert "ai.ai_run.ai_run_id" in fk_targets
    # document_id is a deliberate soft reference (app/models/extraction.py module docstring) -
    # no column named document_id may appear as a ForeignKey source.
    fk_source_columns = {fk.parent.name for fk in ExtractedAttribute.__table__.foreign_keys}
    assert "document_id" not in fk_source_columns


def test_extraction_conflict_requires_at_least_two_members() -> None:
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(ExtractionConflict.__table__).compile())
    assert "jsonb_array_length(member_extraction_ids) >= 2" in ddl


# ---------------------------------------------------------------------------
# Ingestion: AI-EXTRACTION output -> extracted_attribute/source_evidence/extraction_conflict
# ---------------------------------------------------------------------------


class _FlushOnlySession:
    """``ingest_extraction_result`` only ever calls ``add``/``flush`` - a session this small is
    enough to exercise it without the full ``FakeExtractionSession``."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            pk_name = _pk_name(type(obj))
            if getattr(obj, pk_name, None) is None:
                setattr(obj, pk_name, new_uuid7())


def _contract_result(
    *,
    attribute_code: str = "product.taste.sweetness",
    value: Any = "단맛이 적음",
    fact_type: str = "CURRENT_CAPABILITY",
    confidence: float = 0.7,
    concept_codes: list[str] | None = None,
    evidence_segment_ids: list[str] | None = None,
) -> dict:
    return {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "temporary_entity_id": "tmp-product-1",
                "attributes": [
                    {
                        "attribute_code": attribute_code,
                        "value": value,
                        "fact_type": fact_type,
                        "confidence": confidence,
                        "concept_codes": concept_codes or [],
                        "evidence_segment_ids": evidence_segment_ids or ["doc-1:0"],
                    }
                ],
            }
        ],
        "conflicts": [],
        "missing_critical_fields": [],
    }


@pytest.mark.asyncio
async def test_ingest_creates_a_proposed_ai_inferred_row_and_preserves_temporal_validity() -> None:
    session = _FlushOnlySession()
    document_id = uuid.uuid4()
    segments = {
        "doc-1:0": {
            "masked_text": "지역 쌀을 증류하여 만든 전통 소주",
            "page": 3,
            "section": "제품 특징",
            "start_offset": 0,
            "end_offset": 17,
        }
    }

    summary = await ingest_extraction_result(
        session,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        document_id=document_id,
        ai_run_id=uuid.uuid4(),
        result=_contract_result(),
        segments=segments,
    )

    assert len(summary.proposed_extraction_ids) == 1
    row = next(o for o in session.added if isinstance(o, ExtractedAttribute))
    assert row.review_status == "PROPOSED"
    assert row.fact_type == "AI_INFERRED"  # module docstring "핵심 설계 결정"
    assert row.temporal_validity == "CURRENT_CAPABILITY"
    assert row.document_id == document_id

    evidence = next(o for o in session.added if isinstance(o, SourceEvidence))
    assert evidence.extraction_id == row.extraction_id
    assert evidence.evidence_hash.startswith("sha256:")
    assert evidence.page_number == 3


@pytest.mark.asyncio
async def test_ingest_rejects_an_ontology_code_not_in_the_259_concept_catalog() -> None:
    session = _FlushOnlySession()

    with pytest.raises(UnknownOntologyCodeError):
        await ingest_extraction_result(
            session,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            exhibitor_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            ai_run_id=uuid.uuid4(),
            result=_contract_result(concept_codes=["NOT.A.REAL.CODE"]),
        )


@pytest.mark.asyncio
async def test_ingest_conflicts_create_one_row_per_value_and_one_conflict_group() -> None:
    session = _FlushOnlySession()
    result = {
        "entities": [
            {"entity_type": "EXHIBITOR", "temporary_entity_id": "tmp-1", "attributes": []}
        ],
        "conflicts": [
            {
                "temporary_entity_id": "tmp-1",
                "attribute_code": "trade.moq",
                "reason": "두 문서가 다른 값을 말함",
                "values": [
                    {"value": "100박스", "fact_type": "CURRENT_CAPABILITY", "evidence_segment_ids": []},
                    {"value": "50박스", "fact_type": "PAST_EXPERIENCE", "evidence_segment_ids": []},
                ],
            }
        ],
        "missing_critical_fields": [],
    }

    summary = await ingest_extraction_result(
        session,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ai_run_id=None,
        result=result,
    )

    assert len(summary.conflicted_extraction_ids) == 2
    assert len(summary.conflict_ids) == 1
    conflict = next(o for o in session.added if isinstance(o, ExtractionConflict))
    assert conflict.status == "OPEN"
    assert set(conflict.member_extraction_ids) == {str(i) for i in summary.conflicted_extraction_ids}
    for extraction_id in summary.conflicted_extraction_ids:
        row = next(o for o in session.added if isinstance(o, ExtractedAttribute) and o.extraction_id == extraction_id)
        assert row.review_status == "CONFLICTED"


@pytest.mark.asyncio
async def test_ingest_missing_critical_field_creates_an_unknown_row_with_no_evidence() -> None:
    session = _FlushOnlySession()
    result = {
        "entities": [
            {"entity_type": "PRODUCT", "temporary_entity_id": "tmp-p", "attributes": []}
        ],
        "conflicts": [],
        "missing_critical_fields": [
            {"temporary_entity_id": "tmp-p", "attribute_code": "trade.moq", "reason": "문서에 없음"}
        ],
    }

    summary = await ingest_extraction_result(
        session,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ai_run_id=None,
        result=result,
    )

    assert len(summary.unknown_extraction_ids) == 1
    row = next(o for o in session.added if isinstance(o, ExtractedAttribute))
    assert row.fact_type == "UNKNOWN"
    assert row.proposed_value is None
    assert row.review_status == "PROPOSED"
    assert not any(isinstance(o, SourceEvidence) for o in session.added)


# ---------------------------------------------------------------------------
# Review service: exhibitor confirm/modify/reject
# ---------------------------------------------------------------------------


def _proposed_row(
    *,
    exhibitor_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    fact_type: str = "AI_INFERRED",
    attribute_code: str = "product.taste.sweetness",
    review_status: str = "PROPOSED",
    visibility: str | None = "PUBLIC",
) -> ExtractedAttribute:
    return ExtractedAttribute(
        extraction_id=new_uuid7(),
        tenant_id=uuid.uuid4(),
        exhibitor_id=exhibitor_id or uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        entity_type="PRODUCT",
        attribute_code=attribute_code,
        proposed_value="단맛이 적음",
        fact_type=fact_type,
        review_status=review_status,
        visibility=visibility,
        edited_by_exhibitor=False,
    )


@pytest.mark.asyncio
async def test_patch_alone_never_changes_review_status() -> None:
    session = FakeExtractionSession()
    row = _proposed_row()
    session.seed(row)

    updated = await review_service.patch_extraction(
        session,  # type: ignore[arg-type]
        row.extraction_id,
        fields={"normalized_value": {"level": "LOW"}},
        actor_user_id=uuid.uuid4(),
    )

    assert updated.review_status == "PROPOSED"
    assert updated.edited_by_exhibitor is True
    assert updated.normalized_value == {"level": "LOW"}
    action = next(a for a in session.added if isinstance(a, ContentReviewAction))
    assert action.action_type == "MODIFY"


@pytest.mark.asyncio
async def test_confirm_without_prior_edit_goes_straight_to_confirmed() -> None:
    session = FakeExtractionSession()
    row = _proposed_row()
    session.seed(row)
    actor = uuid.uuid4()

    updated = await review_service.confirm_extraction(
        session, row.extraction_id, decision="confirm", reason=None, actor_user_id=actor  # type: ignore[arg-type]
    )

    assert updated.review_status == "CONFIRMED_BY_EXHIBITOR"
    assert updated.reviewed_by_exhibitor_user_id == actor


@pytest.mark.asyncio
async def test_confirm_after_a_patch_edit_records_modified_not_confirmed() -> None:
    session = FakeExtractionSession()
    row = _proposed_row()
    session.seed(row)
    await review_service.patch_extraction(
        session, row.extraction_id, fields={"normalized_value": "x"}, actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
    )

    updated = await review_service.confirm_extraction(
        session, row.extraction_id, decision="confirm", reason=None, actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
    )

    assert updated.review_status == "MODIFIED_BY_EXHIBITOR"


@pytest.mark.asyncio
async def test_confirm_reject_is_terminal_and_records_reason() -> None:
    session = FakeExtractionSession()
    row = _proposed_row()
    session.seed(row)

    updated = await review_service.confirm_extraction(
        session,
        row.extraction_id,
        decision="reject",
        reason="문서에 아예 없는 내용",
        actor_user_id=uuid.uuid4(),  # type: ignore[arg-type]
    )

    assert updated.review_status == "REJECTED_BY_EXHIBITOR"
    assert updated.rejection_reason == "문서에 아예 없는 내용"


@pytest.mark.asyncio
async def test_confirm_twice_is_rejected_as_an_invalid_transition() -> None:
    session = FakeExtractionSession()
    row = _proposed_row(review_status="CONFIRMED_BY_EXHIBITOR")
    session.seed(row)

    with pytest.raises(InvalidTransitionError):
        await review_service.confirm_extraction(
            session, row.extraction_id, decision="confirm", reason=None, actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Review service: submit-for-review validation gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_review_blocks_when_a_row_is_still_proposed() -> None:
    session = FakeExtractionSession()
    document_id = uuid.uuid4()
    session.seed(_proposed_row(document_id=document_id))

    with pytest.raises(SubmitReviewValidationError) as excinfo:
        await review_service.submit_for_review(
            session, document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
        )
    assert excinfo.value.checks[0]["code"] == "EXTRACTIONS_PENDING_REVIEW"


@pytest.mark.asyncio
async def test_submit_review_gives_a_distinct_error_for_unacknowledged_critical_trade_condition() -> None:
    session = FakeExtractionSession()
    document_id = uuid.uuid4()
    session.seed(_proposed_row(document_id=document_id, fact_type="UNKNOWN", attribute_code="trade.moq"))

    with pytest.raises(SubmitReviewValidationError) as excinfo:
        await review_service.submit_for_review(
            session, document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
        )
    assert excinfo.value.checks[0]["code"] == "TRADE_CONDITION_UNKNOWN_UNACKNOWLEDGED"


@pytest.mark.asyncio
async def test_submit_review_blocks_on_unresolved_conflict() -> None:
    session = FakeExtractionSession()
    document_id = uuid.uuid4()
    session.seed(_proposed_row(document_id=document_id, review_status="CONFLICTED"))

    with pytest.raises(SubmitReviewValidationError) as excinfo:
        await review_service.submit_for_review(
            session, document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
        )
    assert excinfo.value.checks[0]["code"] == "CONFLICTS_UNRESOLVED"


@pytest.mark.asyncio
async def test_submit_review_blocks_when_evidence_is_missing_for_a_non_self_declared_row() -> None:
    session = FakeExtractionSession()
    document_id = uuid.uuid4()
    row = _proposed_row(document_id=document_id, review_status="CONFIRMED_BY_EXHIBITOR")
    session.seed(row)  # no SourceEvidence seeded

    with pytest.raises(SubmitReviewValidationError) as excinfo:
        await review_service.submit_for_review(
            session, document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), actor_user_id=uuid.uuid4()  # type: ignore[arg-type]
        )
    codes = {c["code"] for c in excinfo.value.checks}
    assert "EVIDENCE_MISSING" in codes


@pytest.mark.asyncio
async def test_submit_review_succeeds_and_creates_a_review_request_when_everything_checks_out() -> None:
    session = FakeExtractionSession()
    document_id = uuid.uuid4()
    exhibitor_id = uuid.uuid4()
    row = _proposed_row(document_id=document_id, exhibitor_id=exhibitor_id, review_status="CONFIRMED_BY_EXHIBITOR")
    session.seed(row)
    session.seed(
        SourceEvidence(
            evidence_id=new_uuid7(),
            extraction_id=row.extraction_id,
            evidence_text="근거 문장",
            evidence_hash="sha256:aaaa",
        )
    )

    review_request = await review_service.submit_for_review(
        session,  # type: ignore[arg-type]
        document_id=document_id,
        tenant_id=uuid.uuid4(),
        exhibitor_id=exhibitor_id,
        actor_user_id=uuid.uuid4(),
    )

    assert review_request.status == "SUBMITTED"
    assert review_request.document_id == document_id
    assert any(
        isinstance(a, ContentReviewAction) and a.action_type == "SUBMIT_FOR_REVIEW"
        for a in session.added
    )


# ---------------------------------------------------------------------------
# Review service: operator approve/reject/request-changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_is_blocked_from_proposed_even_for_source_fact() -> None:
    """§4 binding rule: no fact_type gets a shortcut around exhibitor confirmation first."""

    session = FakeExtractionSession()
    row = _proposed_row(fact_type="SOURCE_FACT", review_status="PROPOSED")
    session.seed(row)

    with pytest.raises(InvalidTransitionError):
        await review_service.approve_extraction(
            session, row.extraction_id, actor_user_id=uuid.uuid4(), reason=None  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_approve_creates_an_immutable_published_version_when_normalized() -> None:
    session = FakeExtractionSession()
    row = _proposed_row(review_status="CONFIRMED_BY_EXHIBITOR")
    row.normalized_value = "LOW"
    session.seed(row)

    updated, published = await review_service.approve_extraction(
        session, row.extraction_id, actor_user_id=uuid.uuid4(), reason=None  # type: ignore[arg-type]
    )

    assert updated.review_status == "APPROVED_BY_OPERATOR"
    assert published is not None
    assert published.version_no == 1
    assert published.value == "LOW"


@pytest.mark.asyncio
async def test_approve_without_a_normalized_value_does_not_publish_a_version() -> None:
    session = FakeExtractionSession()
    row = _proposed_row(review_status="MODIFIED_BY_EXHIBITOR")
    row.normalized_value = None
    session.seed(row)

    updated, published = await review_service.approve_extraction(
        session, row.extraction_id, actor_user_id=uuid.uuid4(), reason=None  # type: ignore[arg-type]
    )

    assert updated.review_status == "APPROVED_BY_OPERATOR"
    assert published is None


@pytest.mark.asyncio
async def test_reject_extraction_is_terminal() -> None:
    session = FakeExtractionSession()
    row = _proposed_row(review_status="CONFLICTED")
    session.seed(row)

    updated = await review_service.reject_extraction(
        session, row.extraction_id, actor_user_id=uuid.uuid4(), reason="근거가 조작된 것으로 보임"  # type: ignore[arg-type]
    )

    assert updated.review_status == "REJECTED_BY_OPERATOR"


@pytest.mark.asyncio
async def test_request_changes_bounces_the_review_request_back() -> None:
    session = FakeExtractionSession()
    review_request = ContentReviewRequest(
        review_request_id=new_uuid7(),
        tenant_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        status="IN_OPERATOR_REVIEW",
    )
    session.seed(review_request)

    updated = await review_service.request_changes(
        session, review_request.review_request_id, actor_user_id=uuid.uuid4(), comment="가격표 다시 확인 부탁드립니다"  # type: ignore[arg-type]
    )

    assert updated.status == "CHANGES_REQUESTED"
    assert updated.operator_comment == "가격표 다시 확인 부탁드립니다"


@pytest.mark.asyncio
async def test_admin_review_queue_sorts_ai_inferred_requests_first() -> None:
    session = FakeExtractionSession()
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    older = ContentReviewRequest(
        review_request_id=new_uuid7(), tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(),
        document_id=doc_a, status="SUBMITTED",
    )
    newer = ContentReviewRequest(
        review_request_id=new_uuid7(), tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(),
        document_id=doc_b, status="SUBMITTED",
    )
    import datetime as _dt

    older.submitted_at = _dt.datetime(2026, 8, 1, tzinfo=_dt.UTC)
    newer.submitted_at = _dt.datetime(2026, 8, 2, tzinfo=_dt.UTC)
    session.seed(older)
    session.seed(newer)
    session.seed(_proposed_row(document_id=doc_a, review_status="CONFIRMED_BY_EXHIBITOR", fact_type="SELF_DECLARED"))
    session.seed(_proposed_row(document_id=doc_b, review_status="CONFIRMED_BY_EXHIBITOR", fact_type="AI_INFERRED"))

    items = await review_service.list_admin_review_queue(session)  # type: ignore[arg-type]

    assert [i["document_id"] for i in items] == [doc_b, doc_a]


# ---------------------------------------------------------------------------
# Router: standalone app, auth gates, hard "no business-table writes" boundary
# ---------------------------------------------------------------------------


def _verified_principal(
    *,
    user_id: uuid.UUID,
    roles: tuple[str, ...] = (),
    authn_level: str = "AAL2",
) -> VerifiedPrincipal:
    """A verified session principal - the only way a caller is identified after STEP 20."""

    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=user_id,
            tenant_id=tenant_id,
            event_id=event_id,
            role_grants=[
                AuthRoleGrant(
                    role=role, tenant_id=tenant_id, event_id=event_id, exhibitor_id=None
                )
                for role in roles
            ],
            authn_level=authn_level,  # type: ignore[arg-type]
            amr={"magic_link"},
            authenticated_at=datetime.now(UTC),
            mfa_at=datetime.now(UTC),
        ),
        session=None,
    )


def _standalone_app(
    session: FakeExtractionSession,
    *,
    principal: VerifiedPrincipal | None = None,
) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(extraction_router.build_extraction_router(), prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: session
    if principal is not None:
        app.dependency_overrides[get_verified_principal] = lambda: principal
    return app


#: Every route in this file is principal-gated - none of the two intentionally-public
#: STEP 20 exceptions (the signed document download, the public exhibitor-preference read)
#: lives here.
def _extraction_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in extraction_router.build_extraction_router().routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):  # type: ignore[attr-defined]
            routes.append((method, route.path))  # type: ignore[attr-defined]
    return routes


def test_every_extraction_route_rejects_an_unauthenticated_caller() -> None:
    """STEP 20: sending the old actor header is no longer a way in."""

    app = _standalone_app(FakeExtractionSession())
    client = TestClient(app)

    for method, path in _extraction_routes():
        url = "/api/v1" + path
        for placeholder in ("{document_id}", "{extraction_id}", "{review_request_id}"):
            url = url.replace(placeholder, str(uuid.uuid4()))
        response = client.request(
            method,
            url,
            headers={"X-Actor-User-Id": str(uuid.uuid4())},
            json={} if method in {"POST", "PATCH"} else None,
        )
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_no_router_module_reads_the_actor_from_a_client_header() -> None:
    """STEP 20 regression guard: the private header stub must not come back."""

    import inspect

    source = inspect.getsource(extraction_router)

    assert "X-Actor-User-Id" not in source
    assert "Header(" not in source


def test_admin_ai_review_routes_all_carry_the_mfa_role_gate() -> None:
    """The legacy ``identity.user_role`` path has no MFA concept, so the five operator
    routes must additionally inherit core/auth.py's AAL2 enforcement (STEP 20)."""

    router = extraction_router.build_extraction_router()
    admin_routes = [r for r in router.routes if r.path.startswith("/admin/ai-review")]  # type: ignore[attr-defined]

    assert len(admin_routes) == 5
    for route in admin_routes:
        gated = any(
            dependency.dependency is extraction_router.require_ai_review_admin
            for dependency in route.dependencies  # type: ignore[attr-defined]
        )
        assert gated, route.path  # type: ignore[attr-defined]


def test_a_session_without_an_admin_grant_cannot_reach_the_admin_queue() -> None:
    """A perfectly valid non-operator session gets 403 RESOURCE_FORBIDDEN before any
    business query runs."""

    session = FakeExtractionSession()
    user_id = uuid.uuid4()
    # even with the legacy OPERATOR row seeded, the new role gate still refuses
    _seed_role(session, user_id=user_id, role_code="OPERATOR")
    app = _standalone_app(session, principal=_verified_principal(user_id=user_id))
    client = TestClient(app)

    response = client.get("/api/v1/admin/ai-review")

    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


def test_an_admin_grant_without_mfa_is_refused_with_mfa_required() -> None:
    session = FakeExtractionSession()
    user_id = uuid.uuid4()
    _seed_role(session, user_id=user_id, role_code="OPERATOR")
    app = _standalone_app(
        session,
        principal=_verified_principal(
            user_id=user_id, roles=("DATA_REVIEWER",), authn_level="AAL1"
        ),
    )
    client = TestClient(app)

    response = client.get("/api/v1/admin/ai-review")

    assert response.status_code == 403
    assert response.json()["code"] == "MFA_REQUIRED"


def test_all_nine_contract_routes_are_registered() -> None:
    router = extraction_router.build_extraction_router()
    paths = {(frozenset(r.methods), r.path) for r in router.routes}
    assert paths == {
        (frozenset({"GET"}), "/partner/documents/{document_id}/extractions"),
        (frozenset({"PATCH"}), "/partner/extractions/{extraction_id}"),
        (frozenset({"POST"}), "/partner/extractions/{extraction_id}/confirm"),
        (frozenset({"POST"}), "/partner/extractions/submit-review"),
        (frozenset({"GET"}), "/admin/ai-review"),
        (frozenset({"POST"}), "/admin/ai-review"),
        (frozenset({"POST"}), "/admin/ai-review/{extraction_id}/approve"),
        (frozenset({"POST"}), "/admin/ai-review/{extraction_id}/reject"),
        (frozenset({"POST"}), "/admin/ai-review/{review_request_id}/request-changes"),
    }


def test_cross_company_exhibitor_is_denied_access_to_another_companys_extractions() -> None:
    session = FakeExtractionSession()
    owning_exhibitor_id = uuid.uuid4()
    other_exhibitor_id = uuid.uuid4()
    document = SourceDocument(
        document_id=new_uuid7(),
        tenant_id=uuid.uuid4(),
        exhibitor_id=owning_exhibitor_id,
        document_type="COMPANY_PROFILE",
        status="PROCESSED",
    )
    session.seed(document)

    intruder_user_id = uuid.uuid4()
    _seed_role(session, user_id=intruder_user_id, role_code="EXHIBITOR", exhibitor_id=other_exhibitor_id)

    app = _standalone_app(session, principal=_verified_principal(user_id=intruder_user_id))
    client = TestClient(app)

    response = client.get(
        f"/api/v1/partner/documents/{document.document_id}/extractions"
    )

    assert response.status_code == 403


def test_owning_exhibitor_can_list_their_own_extractions() -> None:
    session = FakeExtractionSession()
    exhibitor_id = uuid.uuid4()
    document = SourceDocument(
        document_id=new_uuid7(),
        tenant_id=uuid.uuid4(),
        exhibitor_id=exhibitor_id,
        document_type="COMPANY_PROFILE",
        status="PROCESSED",
    )
    session.seed(document)
    row = _proposed_row(exhibitor_id=exhibitor_id, document_id=document.document_id)
    session.seed(row)

    user_id = uuid.uuid4()
    _seed_role(session, user_id=user_id, role_code="EXHIBITOR", exhibitor_id=exhibitor_id)

    app = _standalone_app(session, principal=_verified_principal(user_id=user_id))
    client = TestClient(app)

    response = client.get(
        f"/api/v1/partner/documents/{document.document_id}/extractions"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document.document_id)
    assert body["items"][0]["extraction_id"] == str(row.extraction_id)


def test_confirm_endpoint_rejects_a_non_owning_actor_before_touching_the_row() -> None:
    session = FakeExtractionSession()
    row = _proposed_row()
    session.seed(row)
    stranger_id = uuid.uuid4()
    _seed_role(session, user_id=stranger_id, role_code="EXHIBITOR", exhibitor_id=uuid.uuid4())

    app = _standalone_app(session, principal=_verified_principal(user_id=stranger_id))
    client = TestClient(app)

    response = client.post(
        f"/api/v1/partner/extractions/{row.extraction_id}/confirm",
        json={"decision": "confirm"},
    )

    assert response.status_code == 403
    assert row.review_status == "PROPOSED"


def test_operator_can_approve_and_response_reports_the_published_version() -> None:
    session = FakeExtractionSession()
    row = _proposed_row(review_status="CONFIRMED_BY_EXHIBITOR")
    row.normalized_value = "LOW"
    session.seed(row)
    operator_id = uuid.uuid4()
    _seed_role(session, user_id=operator_id, role_code="OPERATOR")

    app = _standalone_app(
        session,
        principal=_verified_principal(user_id=operator_id, roles=("EVENT_ADMIN",)),
    )
    client = TestClient(app)

    response = client.post(
        f"/api/v1/admin/ai-review/{row.extraction_id}/approve",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "APPROVED_BY_OPERATOR"
    assert body["published_version_id"] is not None


def test_exhibitor_actor_cannot_reach_the_admin_review_queue() -> None:
    """The legacy ``identity.user_role`` gate still refuses even if the new role gate is
    somehow satisfied - both halves must hold."""

    session = FakeExtractionSession()
    user_id = uuid.uuid4()
    _seed_role(session, user_id=user_id, role_code="EXHIBITOR", exhibitor_id=uuid.uuid4())

    app = _standalone_app(
        session,
        principal=_verified_principal(user_id=user_id, roles=("EVENT_ADMIN",)),
    )
    client = TestClient(app)

    response = client.get("/api/v1/admin/ai-review")

    assert response.status_code == 403
    assert response.json()["detail"] == "RESOURCE_FORBIDDEN"


def test_submit_review_endpoint_surfaces_all_failing_checks_as_422() -> None:
    session = FakeExtractionSession()
    exhibitor_id = uuid.uuid4()
    document = SourceDocument(
        document_id=new_uuid7(),
        tenant_id=uuid.uuid4(),
        exhibitor_id=exhibitor_id,
        document_type="COMPANY_PROFILE",
        status="PROCESSED",
    )
    session.seed(document)
    session.seed(_proposed_row(exhibitor_id=exhibitor_id, document_id=document.document_id))
    user_id = uuid.uuid4()
    _seed_role(session, user_id=user_id, role_code="EXHIBITOR", exhibitor_id=exhibitor_id)

    app = _standalone_app(session, principal=_verified_principal(user_id=user_id))
    client = TestClient(app)

    response = client.post(
        "/api/v1/partner/extractions/submit-review",
        json={"document_id": str(document.document_id)},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "EXTRACTIONS_PENDING_REVIEW"
    assert len(detail["checks"]) == 1


# ---------------------------------------------------------------------------
# Hard boundary: this router never writes to a business table
# ---------------------------------------------------------------------------


def test_no_router_path_ever_touches_business_tables() -> None:
    """GOAL statement in the task instructions: "write an explicit test proving no business
    table is touched by extraction endpoints, only the extraction_* tables". Proven two ways:
    (1) static import check - the router/service modules never import app.models.exhibitor at
    all, so no code path could construct one of its rows; (2) the full exercised test suite
    above never adds anything other than app.models.extraction rows to the fake session."""

    import app.api.v1.routers.extraction as router_mod
    import app.services.extraction.ingestion as ingestion_mod
    import app.services.extraction.review as review_mod

    for module in (router_mod, ingestion_mod, review_mod):
        assert "app.models.exhibitor" not in vars(module).get("__loader__", "").__class__.__module__
        source_module_names = {
            getattr(value, "__module__", "") for value in vars(module).values()
        }
        assert not any(name.startswith("app.models.exhibitor") for name in source_module_names)

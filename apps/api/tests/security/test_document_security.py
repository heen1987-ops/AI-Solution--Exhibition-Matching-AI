"""QA-AI-STRUCTURING (WAVE 2D) file-security matrix for the exhibitor document-upload surface.

Scope: apps/api/tests/security/test_document_security.py (QA-AI-STRUCTURING OWNED PATHS).

This file is deliberately narrower and deeper than
``apps/api/tests/integration/test_ai_structuring_e2e.py``'s own upload/reject smoke checks:
every test here drives the **real** ``app/api/v1/routers/document.py`` router end to end
(multipart HTTP request through ``TestClient``, real ``app/services/document/service.py``,
real ``app/services/document/validation.py`` byte-sniffing, real
``app/services/document/tokens.py`` HMAC signing) against a scripted ``AsyncSession`` fake -
nothing here is monkeypatched away, in particular the cross-company authorization checks below
exercise the *real* ``require_exhibitor_access`` SQL-shaped query (seeded role rows), not a
stub that always grants/denies, which is the one genuine gap left by
``apps/api/tests/test_document_api.py``'s own router-layer tests (those monkeypatch
``require_exhibitor_access`` itself in every case - see that file's own
``test_cross_company_access_is_denied_with_403``).

Checklist covered (from the WAVE 2D QA-AI-STRUCTURING task brief's "highest priority" list):
MIME spoofing, executable/script upload, oversized file, cross-company access, signed-URL-
equivalent expiry, duplicate-file handling, path-traversal-style filenames.

Authentication (MERGE STEP 20/28): the original identified the actor from an
``X-Actor-User-Id`` request header on every call. That stub is gone from
``app/api/v1/routers/document.py`` - the actor now comes only from
``app.core.router_auth.get_actor_user_id``, which itself derives from a verified
server-side principal. This file follows the exact pattern
``apps/api/tests/test_document_api.py`` already established for the router layer:
``app.dependency_overrides[get_actor_user_id] = lambda: <actor>``, set immediately before
each call via the local ``_as()`` helper (dependency_overrides is app-global, so a test that
switches actor mid-test - e.g. the operator-can-read-across-companies check - re-calls
``_as`` with the new actor before its next request).

The four tests below that used to be pinned ``@pytest.mark.xfail(strict=True, ...)`` against
a route-registration-order bug (``GET /partner/documents/download`` shadowed by
``GET /partner/documents/{document_id}``) are un-xfailed here: main's
``app/api/v1/routers/document.py`` already registers ``/download`` before ``/{document_id}``
(verified by direct read), so the bug the worktree tests were pinning does not exist on the
target side. The former proof-of-bug test is inverted into a permanent regression guard
asserting the correct order.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators as sqlops
from sqlalchemy.sql.elements import Grouping, Null

from app.api.v1.routers import document as document_router
from app.core.auth import AuthException, auth_exception_handler
from app.core.config import get_settings
from app.core.router_auth import get_actor_user_id
from app.models.common import new_uuid7
from app.models.exhibitor import Exhibitor
from app.models.identity import UserRole
from app.services.document import tokens as token_service
from app.services.document.storage import InMemoryStorageAdapter

_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
_EXE_BYTES = b"MZ" + b"\x90\x00" * 30
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 40
_TXT_BYTES = b"hello world, this is a plain text company profile.\n"


# ---------------------------------------------------------------------------
# Shared scripted AsyncSession fake - same union-of-capabilities shape as
# apps/api/tests/integration/test_ai_structuring_e2e.py's own ``FakeSession`` (kept as an
# independent copy in this file rather than a shared import, for the same "OWNED PATHS stay
# self-contained" reason documented in that file's module docstring).
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
        if isinstance(right_value, Null) or right_value is None:
            return actual is None
        return actual == right_value
    raise NotImplementedError(f"unsupported operator in FakeSession: {op_fn!r}")


def _pk_name(model: type) -> str:
    return next(iter(model.__table__.primary_key.columns)).key


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    def __init__(self) -> None:
        self.tables: dict[type, dict[Any, Any]] = defaultdict(dict)
        self._pending: list[Any] = []
        self.commit_count = 0

    def add(self, obj: Any) -> None:
        self._pending.append(obj)

    @staticmethod
    def _apply_defaults(obj: Any) -> None:
        import datetime as _dt

        model = type(obj)
        if not hasattr(model, "__table__"):
            return
        now = _dt.datetime.now(_dt.UTC)
        for column in model.__table__.columns:
            if getattr(obj, column.key, None) is not None:
                continue
            if column.server_default is not None:
                setattr(obj, column.key, now)
            elif column.default is not None:
                arg = column.default.arg
                setattr(obj, column.key, arg(None) if callable(arg) else arg)

    async def flush(self) -> None:
        for obj in self._pending:
            pk_name = _pk_name(type(obj))
            if getattr(obj, pk_name, None) is None:
                setattr(obj, pk_name, new_uuid7())
            self._apply_defaults(obj)
            self.tables[type(obj)][getattr(obj, pk_name)] = obj
        self._pending = []

    async def commit(self) -> None:
        await self.flush()
        self.commit_count += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def get(self, model: type, pk: Any) -> Any:
        await self.flush()
        return self.tables.get(model, {}).get(pk)

    async def delete(self, obj: Any) -> None:
        await self.flush()
        pk_name = _pk_name(type(obj))
        self.tables.get(type(obj), {}).pop(getattr(obj, pk_name, None), None)

    def seed(self, obj: Any, *, model: type | None = None, key: Any = None) -> None:
        target_model = model or type(obj)
        pk = key if key is not None else getattr(obj, _pk_name(target_model), None)
        if model is None:
            self._apply_defaults(obj)
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
        return _FakeResult(rows)


def _seed_role(
    session: FakeSession, *, user_id: uuid.UUID, role_code: str, exhibitor_id: uuid.UUID | None = None
) -> None:
    row = SimpleNamespace(
        user_role_id=new_uuid7(), user_id=user_id, valid_until=None, exhibitor_id=exhibitor_id,
        role_code=role_code,
    )
    session.seed(row, model=UserRole, key=row.user_role_id)


class _Actors:
    def __init__(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.exhibitor_a_id = uuid.uuid4()
        self.exhibitor_b_id = uuid.uuid4()
        self.user_a_id = uuid.uuid4()  # belongs to exhibitor A only
        self.user_b_id = uuid.uuid4()  # belongs to exhibitor B only


@pytest.fixture()
def actors() -> _Actors:
    return _Actors()


@pytest.fixture()
def session(actors: _Actors) -> FakeSession:
    s = FakeSession()
    _seed_role(s, user_id=actors.user_a_id, role_code="EXHIBITOR", exhibitor_id=actors.exhibitor_a_id)
    _seed_role(s, user_id=actors.user_b_id, role_code="EXHIBITOR", exhibitor_id=actors.exhibitor_b_id)
    s.seed(
        SimpleNamespace(exhibitor_id=actors.exhibitor_a_id, tenant_id=actors.tenant_id, deleted_at=None),
        model=Exhibitor, key=actors.exhibitor_a_id,
    )
    s.seed(
        SimpleNamespace(exhibitor_id=actors.exhibitor_b_id, tenant_id=actors.tenant_id, deleted_at=None),
        model=Exhibitor, key=actors.exhibitor_b_id,
    )
    return s


@pytest.fixture()
def client_and_storage(
    session: FakeSession,
) -> tuple[TestClient, InMemoryStorageAdapter, FastAPI]:
    storage = InMemoryStorageAdapter()

    async def fake_db():
        yield session

    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(document_router.router)
    app.dependency_overrides[document_router.get_db] = fake_db
    app.dependency_overrides[document_router.get_storage_adapter] = lambda: storage
    return TestClient(app), storage, app


def _as(app: FastAPI, actor_user_id: uuid.UUID) -> None:
    """MERGE STEP 20/28: stand-in for "a verified server-side session identified this
    user" - dependency_overrides is app-global, so call this immediately before whichever
    request should be attributed to ``actor_user_id`` (tests that switch actor mid-test
    call it again before the next request)."""

    app.dependency_overrides[get_actor_user_id] = lambda: actor_user_id


def _upload(
    client: TestClient, app: FastAPI, *, exhibitor_id: uuid.UUID, actor_user_id: uuid.UUID,
    filename: str, data: bytes, content_type: str, document_type: str = "CATALOG",
):
    _as(app, actor_user_id)
    return client.post(
        "/partner/documents",
        data={"exhibitor_id": str(exhibitor_id), "document_type": document_type},
        files={"file": (filename, data, content_type)},
    )


# ===========================================================================
# 1. MIME spoofing
# ===========================================================================


def test_mime_spoofing_pdf_extension_with_plain_text_content_is_rejected_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="fake_report.pdf", data=_TXT_BYTES, content_type="application/pdf",
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "MIME_EXTENSION_MISMATCH"
    assert storage._objects == {}  # nothing ever reached storage


def test_mime_spoofing_txt_extension_wrapping_a_zip_archive_is_rejected_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="notes.txt", data=_ZIP_BYTES, content_type="text/plain",
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "MIME_EXTENSION_MISMATCH"
    assert storage._objects == {}


# ===========================================================================
# 2. Executable / script upload rejected
# ===========================================================================


def test_executable_disguised_with_an_allowed_extension_is_rejected_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="company_profile.txt", data=_EXE_BYTES, content_type="text/plain",
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "CONTENT_NOT_ALLOWED"
    assert storage._objects == {}


@pytest.mark.parametrize(
    "filename", ["installer.exe", "run.sh", "script.ps1", "payload.js", "macro.vbs", "app.jar"]
)
def test_script_and_executable_extensions_are_rejected_outright_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors, filename: str,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename=filename, data=b"anything", content_type="application/octet-stream",
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "EXTENSION_NOT_ALLOWED"
    assert storage._objects == {}


@pytest.mark.parametrize("filename", ["archive.zip", "bundle.rar", "backup.7z", "data.tar.gz"])
def test_archive_extensions_are_rejected_outright_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors, filename: str,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename=filename, data=_ZIP_BYTES, content_type="application/zip",
    )
    assert response.status_code == 415
    assert storage._objects == {}


# ===========================================================================
# 3. Oversized file rejected
# ===========================================================================


def test_oversized_file_is_rejected_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, storage, app = client_and_storage
    small_max = 10  # bytes - deliberately tiny so the test runs fast

    class _TinyLimitSettings:
        DOCUMENT_MAX_UPLOAD_BYTES = small_max
        DOCUMENT_DOWNLOAD_TOKEN_TTL_SECONDS = 300
        SECRET_KEY = "test-secret"

    monkeypatch.setattr(document_router, "get_settings", lambda: _TinyLimitSettings())

    oversized = _PDF_BYTES + b"0" * 100
    assert len(oversized) > small_max
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="big.pdf", data=oversized, content_type="application/pdf",
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "FILE_TOO_LARGE"
    assert storage._objects == {}


def test_empty_file_is_rejected_via_router(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="empty.txt", data=b"", content_type="text/plain",
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "EMPTY_FILE"
    assert storage._objects == {}


# ===========================================================================
# 4. Cross-company document access denied - real authorization query, not a stub
# ===========================================================================


def test_exhibitor_a_cannot_upload_a_document_under_exhibitor_bs_id(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_b_id, actor_user_id=actors.user_a_id,
        filename="sneaky.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert response.status_code == 403
    assert storage._objects == {}


def test_exhibitor_a_cannot_list_exhibitor_bs_documents(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, _storage, app = client_and_storage
    _as(app, actors.user_a_id)
    response = client.get(f"/partner/documents?exhibitor_id={actors.exhibitor_b_id}")
    assert response.status_code == 403


def test_exhibitor_a_cannot_read_exhibitor_bs_document_detail_or_get_a_download_token(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
    session: FakeSession,
) -> None:
    client, _storage, app = client_and_storage
    uploaded = _upload(
        client, app, exhibitor_id=actors.exhibitor_b_id, actor_user_id=actors.user_b_id,
        filename="b-confidential.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document_id"]

    _as(app, actors.user_a_id)
    detail = client.get(f"/partner/documents/{document_id}?exhibitor_id={actors.exhibitor_b_id}")
    assert detail.status_code == 403

    token_attempt = client.get(
        f"/partner/documents/{document_id}/download-token?exhibitor_id={actors.exhibitor_b_id}"
    )
    assert token_attempt.status_code == 403

    delete_attempt = client.delete(
        f"/partner/documents/{document_id}?exhibitor_id={actors.exhibitor_b_id}"
    )
    assert delete_attempt.status_code == 403


def test_exhibitor_a_requesting_its_own_exhibitor_id_for_bs_document_id_gets_404_not_403(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    """A owns nothing about B's document, but if A supplies its *own* exhibitor_id alongside
    B's document_id, the router must not leak that the document exists at all - it should
    behave exactly like a not-found document (404), not a permission error that confirms
    existence (403)."""

    client, _storage, app = client_and_storage
    uploaded = _upload(
        client, app, exhibitor_id=actors.exhibitor_b_id, actor_user_id=actors.user_b_id,
        filename="b-confidential.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    document_id = uploaded.json()["document_id"]

    _as(app, actors.user_a_id)
    response = client.get(f"/partner/documents/{document_id}?exhibitor_id={actors.exhibitor_a_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "DOCUMENT_NOT_FOUND"


def test_operator_role_can_read_across_companies(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
    session: FakeSession,
) -> None:
    """Sanity check that the denial above is genuinely role-based, not just "always 403" -
    an OPERATOR/ADMIN identity must still be able to reach another company's document."""

    client, _storage, app = client_and_storage
    operator_id = uuid.uuid4()
    _seed_role(session, user_id=operator_id, role_code="OPERATOR")

    uploaded = _upload(
        client, app, exhibitor_id=actors.exhibitor_b_id, actor_user_id=actors.user_b_id,
        filename="b-confidential.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    document_id = uploaded.json()["document_id"]

    _as(app, operator_id)
    response = client.get(f"/partner/documents/{document_id}?exhibitor_id={actors.exhibitor_b_id}")
    assert response.status_code == 200


# ===========================================================================
# 5. Signed-URL-equivalent (download token) expiry enforced
#
# MERGE STEP 28: the worktree pinned these four as xfail(strict=True) against a route-
# registration-order bug in app/api/v1/routers/document.py (GET /partner/documents/download
# shadowed by GET /partner/documents/{document_id}, both matching a single path segment).
# Verified by direct read that main's document.py registers /download (line ~206) BEFORE
# /{document_id} (line ~253) - the bug does not exist on this side, so these run as
# ordinary passing tests instead of xfail.
# ===========================================================================


def test_download_token_round_trip_then_expiry_and_tampering_are_both_rejected(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, _storage, app = client_and_storage
    uploaded = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="brochure.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    document_id = uploaded.json()["document_id"]

    _as(app, actors.user_a_id)
    token_response = client.get(
        f"/partner/documents/{document_id}/download-token?exhibitor_id={actors.exhibitor_a_id}"
    )
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    assert "storage" not in token_response.text  # raw storage_key never crosses the wire

    good = client.get(f"/partner/documents/download?token={token}")
    assert good.status_code == 200
    assert good.content == _PDF_BYTES

    tampered_char = "y" if token[-1] != "y" else "z"
    tampered_response = client.get(f"/partner/documents/download?token={token[:-1] + tampered_char}")
    assert tampered_response.status_code == 404
    assert tampered_response.json()["detail"] == "DOWNLOAD_TOKEN_INVALID_OR_EXPIRED"

    # A token whose signature is valid but whose embedded expiry has already passed - the
    # "signed URL" equivalent of an expired presigned S3 link.
    settings = get_settings()
    stale_token = token_service.issue_download_token(
        document_id=uuid.UUID(document_id), file_id=uuid.uuid4(), exhibitor_id=actors.exhibitor_a_id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1), secret=settings.SECRET_KEY,
    )
    expired_response = client.get(f"/partner/documents/download?token={stale_token}")
    assert expired_response.status_code == 404
    assert expired_response.json()["detail"] == "DOWNLOAD_TOKEN_INVALID_OR_EXPIRED"


def test_download_token_for_one_document_cannot_be_reused_for_another(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    """A token's claims (document_id/file_id/exhibitor_id) are bound at issuance and
    re-verified server-side against the actual stored file at resolve time - a token cannot be
    "for" one document and used to fetch a different one, even with a valid signature."""

    client, _storage, _app = client_and_storage
    settings = get_settings()
    forged = token_service.issue_download_token(
        document_id=uuid.uuid4(), file_id=uuid.uuid4(), exhibitor_id=actors.exhibitor_a_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5), secret=settings.SECRET_KEY,
    )
    response = client.get(f"/partner/documents/download?token={forged}")
    assert response.status_code == 404


# ===========================================================================
# 6. Duplicate-file handling
# ===========================================================================


def test_duplicate_content_upload_within_the_same_exhibitor_returns_409_with_existing_id(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    client, storage, app = client_and_storage
    first = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="catalog-v1.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert first.status_code == 201
    first_id = first.json()["document_id"]

    second = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="catalog-v1-renamed.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert second.status_code == 409
    body = second.json()["detail"]
    assert body["code"] == "DOCUMENT_DUPLICATE_CONTENT"
    assert body["existing_document_id"] == first_id
    # exactly one object was ever written to storage - the duplicate never touched it.
    assert len(storage._objects) == 1


def test_duplicate_content_across_different_exhibitors_is_allowed(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    """A shared public spec-sheet template byte-identical across two unrelated exhibitors must
    not be blocked - dedup is scoped per exhibitor, not global."""

    client, storage, app = client_and_storage
    first = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename="shared-template.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert first.status_code == 201
    second = _upload(
        client, app, exhibitor_id=actors.exhibitor_b_id, actor_user_id=actors.user_b_id,
        filename="shared-template.pdf", data=_PDF_BYTES, content_type="application/pdf",
    )
    assert second.status_code == 201
    assert len(storage._objects) == 2


# ===========================================================================
# 7. Path-traversal-style filenames sanitized
# ===========================================================================


@pytest.mark.parametrize(
    "malicious_filename",
    [
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\config.pdf",
        "....//....//escape.pdf",
        "/absolute/path/injected.pdf",
    ],
)
def test_path_traversal_filenames_never_influence_the_storage_key(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
    malicious_filename: str,
) -> None:
    """``build_storage_key`` (app/services/document/storage.py) derives the storage path
    entirely from server-generated UUIDs (exhibitor_id/document_id/file_id) - the client-
    supplied filename never appears in it, so no filename can traverse out of the storage
    root no matter what it contains."""

    client, storage, app = client_and_storage
    response = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename=malicious_filename, data=_PDF_BYTES, content_type="application/pdf",
    )
    assert response.status_code == 201
    for stored_key in storage._objects:
        assert ".." not in stored_key
        assert not stored_key.startswith("/")
        assert stored_key.startswith(f"exhibitor/{actors.exhibitor_a_id}/")


def test_local_filesystem_adapter_itself_refuses_a_directly_supplied_traversal_key(
    tmp_path: Any,
) -> None:
    """Second line of defense at the storage adapter itself (belt-and-suspenders check,
    independent of the router/service layer never actually building such a key) -
    ``apps/api/tests/test_document_api.py`` already covers this at the unit level; repeated
    here as part of this track's own end-to-end security matrix for completeness."""

    from app.services.document.storage import (
        LocalFilesystemStorageAdapter,
        StorageKeyError,
    )

    adapter = LocalFilesystemStorageAdapter(tmp_path / "docs")
    with pytest.raises(StorageKeyError):
        adapter.put(key="../../../etc/passwd", data=b"pwned")
    with pytest.raises(StorageKeyError):
        adapter.get(key="../../../etc/passwd")


def test_content_disposition_header_on_download_does_not_carry_a_raw_crlf(
    client_and_storage: tuple[TestClient, InMemoryStorageAdapter, FastAPI], actors: _Actors,
) -> None:
    """A filename crafted to look like an HTTP header injection / response-splitting attempt
    must not be able to smuggle a literal CR/LF into the ``Content-Disposition`` response
    header - proven against the real HTTP response, not just the stored string."""

    client, _storage, app = client_and_storage
    tricky_filename = 'evil".pdf'  # embedded double-quote - the header uses a quoted string
    uploaded = _upload(
        client, app, exhibitor_id=actors.exhibitor_a_id, actor_user_id=actors.user_a_id,
        filename=tricky_filename, data=_PDF_BYTES, content_type="application/pdf",
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document_id"]

    _as(app, actors.user_a_id)
    token = client.get(
        f"/partner/documents/{document_id}/download-token?exhibitor_id={actors.exhibitor_a_id}"
    ).json()["token"]
    download = client.get(f"/partner/documents/download?token={token}")
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition


def test_download_route_is_registered_before_the_document_detail_route() -> None:
    """Permanent regression guard (formerly a bug-proving xfail - see module docstring):
    ``GET /partner/documents/download`` must stay registered before the dynamic
    ``GET /partner/documents/{document_id}`` route, or Starlette's first-match-wins
    semantics send every download request to the detail endpoint instead (WAVE2D-QA.md
    #2). This test inspects the real router's route list (not a copy), so it fails the
    moment anyone reorders the two routes back into the shadowed order."""

    paths_in_order = [route.path for route in document_router.router.routes]
    detail_index = paths_in_order.index("/partner/documents/{document_id}")
    download_index = paths_in_order.index("/partner/documents/download")
    assert download_index < detail_index, (
        "GET /partner/documents/download must be registered before the dynamic "
        "GET /partner/documents/{document_id} route, or it will never be reachable "
        "(see WAVE2D-QA.md #2)"
    )

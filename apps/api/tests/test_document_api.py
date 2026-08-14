"""BACKEND-DOCUMENT (WAVE 2D) 커버리지.

세 계층으로 나눠 테스트한다:

1. 순수함수 계층(app/services/document/validation.py, hashing.py, storage.py, tokens.py) -
   실제 DB/Postgres 없이 바로 검증할 수 있는 핵심 규칙들(허용 확장자, MIME/확장자 불일치,
   exe/스크립트/압축파일 즉시거부, 크기 상한, 저장소 경로 탈출 방지, 토큰 위변조/만료 거부).
2. 서비스 계층(app/services/document/service.py) - 실제 Postgres 대신 이 파일 하단의
   _FakeAsyncSession(테스트 전용 인메모리 세션 - AsyncSession이 이 모듈에서 실제로 쓰이는
   부분집합만 구현)과 InMemoryStorageAdapter로 업로드/중복탐지/삭제차단/다운로드 왕복/감사
   로그 기록까지 실제 코드 경로로 실행해 검증한다. 이 저장소의 다른 라우터 테스트들이
   TestClient에 대해 하는 것("실제 DB가 없을 때는 fake로 대체")과 같은 원칙을 서비스 계층에
   적용한 것이다.
3. 라우터 계층(app/api/v1/routers/document.py) - document.router는 아직 app/api/v1/api.py에
   등록되지 않았으므로(통합 단계 몫 - 이 작업 지시의 절대금지 사항) 여기서는 그 router만 담은
   전용 FastAPI 앱을 만들어 HTTP 계약(응답 모양, 상태코드, storage_key 미노출, 접근거부)만
   확인한다. 이 계층에서는 document_service.*와 접근검사 헬퍼를 monkeypatch해 라우터 자체의
   책임(파라미터 파싱, 오류 매핑, 응답 조립)만 분리해서 본다 - test_recommendation_api.py의
   monkeypatch 패턴과 동일하다.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers import document as document_router
from app.core.auth import AuthException, auth_exception_handler
from app.core.router_auth import get_actor_user_id
from app.models.document import (
    DocumentAccessLog,
    DocumentFile,
    DocumentProcessingJob,
    SourceDocument,
)
from app.schemas.document import DocumentRead, DocumentUploadResponse
from app.services.document import service as document_service
from app.services.document import tokens as token_service
from app.services.document.hashing import sha256_hex
from app.services.document.storage import (
    InMemoryStorageAdapter,
    LocalFilesystemStorageAdapter,
    StorageKeyError,
    build_storage_key,
)
from app.services.document.validation import (
    DocumentValidationError,
    check_extension_allowed,
    sniff_content_kind,
    validate_upload,
)

_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
_TXT_BYTES = b"hello world, this is a plain text document.\n"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 40  # OOXML(docx/xlsx) container prefix
_EXE_BYTES = b"MZ" + b"\x90\x00" * 30
_MAX_BYTES = 25 * 1024 * 1024


# ===========================================================================
# 1. 순수함수 계층
# ===========================================================================


def test_allowed_extensions_are_exactly_the_five_documented_formats() -> None:
    for ext, data in (("pdf", _PDF_BYTES), ("docx", _ZIP_BYTES), ("xlsx", _ZIP_BYTES),
                       ("csv", _TXT_BYTES), ("txt", _TXT_BYTES)):
        validated = validate_upload(
            filename=f"sample.{ext}", size_bytes=len(data), data=data,
            declared_content_type=None, max_bytes=_MAX_BYTES,
        )
        assert validated.extension == ext


@pytest.mark.parametrize("filename", ["virus.exe", "script.sh", "archive.zip", "installer.msi"])
def test_disallowed_extensions_are_rejected_outright(filename: str) -> None:
    with pytest.raises(DocumentValidationError) as excinfo:
        check_extension_allowed(filename)
    assert excinfo.value.code == "EXTENSION_NOT_ALLOWED"


def test_extension_not_in_allowlist_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="notes.md", size_bytes=len(_TXT_BYTES), data=_TXT_BYTES,
            declared_content_type=None, max_bytes=_MAX_BYTES,
        )
    assert excinfo.value.code == "EXTENSION_NOT_ALLOWED"


def test_mime_spoofing_extension_claims_pdf_but_content_is_plain_text() -> None:
    """확장자는 .pdf인데 실제 바이트는 PDF 매직바이트가 없는 일반 텍스트인 경우."""

    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="report.pdf", size_bytes=len(_TXT_BYTES), data=_TXT_BYTES,
            declared_content_type="application/pdf", max_bytes=_MAX_BYTES,
        )
    assert excinfo.value.code == "MIME_EXTENSION_MISMATCH"


def test_mime_spoofing_renamed_executable_is_rejected_even_with_allowed_extension() -> None:
    """확장자를 .txt로 위장한 실행파일(MZ 매직바이트)은 확장자 허용목록을 통과해도 걸러진다."""

    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="totally_a_document.txt", size_bytes=len(_EXE_BYTES), data=_EXE_BYTES,
            declared_content_type="text/plain", max_bytes=_MAX_BYTES,
        )
    assert excinfo.value.code == "CONTENT_NOT_ALLOWED"
    assert sniff_content_kind(_EXE_BYTES) == "exe"


def test_csv_disguised_as_zip_archive_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="data.csv", size_bytes=len(_ZIP_BYTES), data=_ZIP_BYTES,
            declared_content_type="text/csv", max_bytes=_MAX_BYTES,
        )
    assert excinfo.value.code == "MIME_EXTENSION_MISMATCH"


def test_oversized_file_is_rejected() -> None:
    data = _PDF_BYTES + b"A" * 1000
    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="huge.pdf", size_bytes=len(data), data=data,
            declared_content_type="application/pdf", max_bytes=100,
        )
    assert excinfo.value.code == "FILE_TOO_LARGE"


def test_empty_file_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as excinfo:
        validate_upload(
            filename="empty.pdf", size_bytes=0, data=b"",
            declared_content_type="application/pdf", max_bytes=_MAX_BYTES,
        )
    assert excinfo.value.code == "EMPTY_FILE"


def test_sha256_hex_is_deterministic_and_content_sensitive() -> None:
    assert sha256_hex(b"same content") == sha256_hex(b"same content")
    assert sha256_hex(b"same content") != sha256_hex(b"different content")


def test_local_filesystem_storage_round_trip(tmp_path: Any) -> None:
    adapter = LocalFilesystemStorageAdapter(tmp_path / "docs")
    key = "exhibitor/abc/doc1/file1.pdf"
    adapter.put(key=key, data=_PDF_BYTES)

    assert adapter.exists(key=key) is True
    assert adapter.get(key=key) == _PDF_BYTES

    adapter.delete(key=key)
    assert adapter.exists(key=key) is False
    with pytest.raises(StorageKeyError):
        adapter.get(key=key)


def test_local_filesystem_storage_rejects_path_traversal(tmp_path: Any) -> None:
    adapter = LocalFilesystemStorageAdapter(tmp_path / "docs")
    with pytest.raises(StorageKeyError):
        adapter.put(key="../../etc/passwd", data=b"pwned")


def test_in_memory_storage_round_trip() -> None:
    adapter = InMemoryStorageAdapter()
    adapter.put(key="k", data=b"bytes")
    assert adapter.get(key="k") == b"bytes"
    adapter.delete(key="k")
    with pytest.raises(StorageKeyError):
        adapter.get(key="k")


def test_build_storage_key_namespaces_by_exhibitor() -> None:
    exhibitor_id = uuid.uuid4()
    document_id = uuid.uuid4()
    file_id = uuid.uuid4()
    key = build_storage_key(
        exhibitor_id=exhibitor_id, document_id=document_id, file_id=file_id, extension="pdf"
    )
    assert key == f"exhibitor/{exhibitor_id}/{document_id}/{file_id}.pdf"


def test_download_token_round_trip_and_rejects_tampering_and_wrong_secret() -> None:
    document_id, file_id, exhibitor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    token = token_service.issue_download_token(
        document_id=document_id, file_id=file_id, exhibitor_id=exhibitor_id,
        expires_at=expires_at, secret="secret-a",
    )

    claims = token_service.verify_download_token(token, secret="secret-a")
    assert claims is not None
    assert claims.document_id == document_id
    assert claims.file_id == file_id

    assert token_service.verify_download_token(token, secret="wrong-secret") is None
    tampered_last_char = "y" if token[-1] != "y" else "z"
    assert token_service.verify_download_token(token[:-1] + tampered_last_char, secret="secret-a") is None
    assert token_service.verify_download_token("not-a-valid-token", secret="secret-a") is None


def test_download_token_rejects_expiry() -> None:
    document_id, file_id, exhibitor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(seconds=1)
    token = token_service.issue_download_token(
        document_id=document_id, file_id=file_id, exhibitor_id=exhibitor_id,
        expires_at=expires_at, secret="secret-a",
    )
    future = (datetime.now(UTC) + timedelta(minutes=10)).timestamp()
    assert token_service.verify_download_token(token, secret="secret-a", now=future) is None


def test_response_schemas_never_expose_a_storage_path_field() -> None:
    forbidden = {"storage_key", "storage_path", "path", "url"}
    assert forbidden.isdisjoint(set(DocumentUploadResponse.model_fields))
    assert forbidden.isdisjoint(set(DocumentRead.model_fields))


# ===========================================================================
# 2. 서비스 계층 - _FakeAsyncSession (아래 정의) + InMemoryStorageAdapter
# ===========================================================================


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class _FakeAsyncSession:
    """document/service.py가 실제로 쓰는 AsyncSession API의 부분집합만 구현한 인메모리 세션.

    execute()는 이 서비스 계층이 실제로 만드는 WHERE절 형태(단순 등가비교의 AND 조합)만
    이해하는 얕은 해석기로 필터링한다 - 완전한 SQL 엔진이 아니라, find_duplicate/
    get_document_versions가 쓰는 패턴만 지원하면 충분하다.
    """

    def __init__(self) -> None:
        self.store: dict[type, dict[Any, Any]] = {}
        self.deleted: list[Any] = []
        self.commits = 0

    def _bucket(self, model: type) -> dict[Any, Any]:
        return self.store.setdefault(model, {})

    @staticmethod
    def _pk_name(obj_or_cls: Any) -> str:
        cls = obj_or_cls if isinstance(obj_or_cls, type) else type(obj_or_cls)
        return cls.__mapper__.primary_key[0].name

    def add(self, obj: Any) -> None:
        pk_name = self._pk_name(obj)
        if getattr(obj, pk_name, None) is None:
            setattr(obj, pk_name, uuid.uuid4())
        self._bucket(type(obj))[getattr(obj, pk_name)] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def get(self, model: type, pk: Any) -> Any | None:
        return self._bucket(model).get(pk)

    async def delete(self, obj: Any) -> None:
        pk_name = self._pk_name(obj)
        self._bucket(type(obj)).pop(getattr(obj, pk_name), None)
        self.deleted.append(obj)

    @staticmethod
    def _matches(item: Any, whereclause: Any) -> bool:
        if whereclause is None:
            return True
        clauses = list(getattr(whereclause, "clauses", None) or [whereclause])
        for clause in clauses:
            col_name = getattr(getattr(clause, "left", None), "key", None)
            bind = getattr(clause, "right", None)
            if col_name is None or bind is None or not hasattr(bind, "value"):
                # 이 얕은 해석기가 모르는 형태의 절은 안전한 쪽(불일치)으로 처리한다 -
                # 조용히 과도하게 매칭시키는 것보다 테스트가 시끄럽게 실패하는 편이 낫다.
                return False
            if getattr(item, col_name, object()) != bind.value:
                return False
        return True

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = stmt.column_descriptions[0]["entity"]
        items = [
            item for item in self._bucket(entity).values()
            if self._matches(item, stmt.whereclause)
        ]
        if entity is DocumentFile:
            items.sort(key=lambda o: o.version_no, reverse=True)
        return _FakeResult(items)


def _actor_logs(session: _FakeAsyncSession) -> list[DocumentAccessLog]:
    return list(session.store.get(DocumentAccessLog, {}).values())


@pytest.mark.asyncio
async def test_upload_document_creates_first_version_and_pending_processing_job() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    actor_user_id = uuid.uuid4()

    result = await document_service.upload_document(
        session, storage,
        tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id, event_id=None,
        document_type="CATALOG", filename="brochure.pdf", data=_PDF_BYTES,
        declared_content_type="application/pdf", actor_user_id=actor_user_id,
        max_bytes=_MAX_BYTES,
    )

    assert result.file.version_no == 1
    assert result.document.status == "PROCESSING"
    assert result.processing_job.status == "PENDING"
    assert storage.exists(key=result.file.storage_key) is True
    assert storage.get(key=result.file.storage_key) == _PDF_BYTES

    upload_logs = [log for log in _actor_logs(session) if log.action == "UPLOAD"]
    assert len(upload_logs) == 1
    assert upload_logs[0].exhibitor_id == exhibitor_id
    assert upload_logs[0].actor_user_id == actor_user_id


@pytest.mark.asyncio
async def test_upload_document_rejects_disallowed_extension_before_touching_storage() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()

    with pytest.raises(DocumentValidationError) as excinfo:
        await document_service.upload_document(
            session, storage,
            tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), event_id=None,
            document_type="CATALOG", filename="payload.exe", data=_EXE_BYTES,
            declared_content_type=None, actor_user_id=uuid.uuid4(), max_bytes=_MAX_BYTES,
        )

    assert excinfo.value.code == "EXTENSION_NOT_ALLOWED"
    assert session.store == {}
    assert session.commits == 0


@pytest.mark.asyncio
async def test_upload_document_detects_duplicate_content_within_same_exhibitor() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    content_hash = sha256_hex(_PDF_BYTES)

    existing = SourceDocument(
        document_id=uuid.uuid4(), tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id,
        document_type="CATALOG", status="PROCESSED", content_hash=content_hash,
    )
    session.add(existing)

    with pytest.raises(document_service.DocumentDuplicateError) as excinfo:
        await document_service.upload_document(
            session, storage,
            tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id, event_id=None,
            document_type="CATALOG", filename="brochure-again.pdf", data=_PDF_BYTES,
            declared_content_type="application/pdf", actor_user_id=uuid.uuid4(),
            max_bytes=_MAX_BYTES,
        )

    assert excinfo.value.existing_document_id == existing.document_id
    # 중복이 감지되면 새 문서는 만들어지지 않는다 (기존 하나만 남아 있어야 한다).
    assert len(session.store[SourceDocument]) == 1


@pytest.mark.asyncio
async def test_upload_document_allows_same_content_for_different_exhibitors() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    content_hash = sha256_hex(_PDF_BYTES)

    other_exhibitor_document = SourceDocument(
        document_id=uuid.uuid4(), tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(),
        document_type="CATALOG", status="PROCESSED", content_hash=content_hash,
    )
    session.add(other_exhibitor_document)

    result = await document_service.upload_document(
        session, storage,
        tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(), event_id=None,
        document_type="CATALOG", filename="brochure.pdf", data=_PDF_BYTES,
        declared_content_type="application/pdf", actor_user_id=uuid.uuid4(),
        max_bytes=_MAX_BYTES,
    )
    assert result.document.document_id != other_exhibitor_document.document_id


async def _seed_uploaded_document(
    session: _FakeAsyncSession, storage: InMemoryStorageAdapter, *, exhibitor_id: uuid.UUID,
) -> document_service.UploadResult:
    return await document_service.upload_document(
        session, storage,
        tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id, event_id=None,
        document_type="CATALOG", filename="brochure.pdf", data=_PDF_BYTES,
        declared_content_type="application/pdf", actor_user_id=uuid.uuid4(),
        max_bytes=_MAX_BYTES,
    )


@pytest.mark.asyncio
async def test_delete_document_hard_deletes_when_not_published_and_logs_delete() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    seeded = await _seed_uploaded_document(session, storage, exhibitor_id=exhibitor_id)
    storage_key = seeded.file.storage_key

    await document_service.delete_document(
        session, storage, document=seeded.document, actor_user_id=uuid.uuid4()
    )

    assert seeded.document.document_id not in session.store[SourceDocument]
    assert seeded.file.file_id not in session.store[DocumentFile]
    assert storage.exists(key=storage_key) is False

    delete_logs = [log for log in _actor_logs(session) if log.action == "DELETE"]
    assert len(delete_logs) == 1


@pytest.mark.asyncio
async def test_delete_document_is_blocked_when_referenced_by_published_content() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    seeded = await _seed_uploaded_document(session, storage, exhibitor_id=exhibitor_id)

    await document_service.mark_current_version_published(session, document=seeded.document)
    assert seeded.document.published_file_id == seeded.file.file_id

    with pytest.raises(document_service.DocumentDeleteBlockedError) as excinfo:
        await document_service.delete_document(
            session, storage, document=seeded.document, actor_user_id=uuid.uuid4()
        )

    assert excinfo.value.published_file_id == seeded.file.file_id
    # 차단됐으므로 문서/파일/스토리지 오브젝트가 모두 그대로 남아 있어야 한다.
    assert seeded.document.document_id in session.store[SourceDocument]
    assert seeded.file.file_id in session.store[DocumentFile]
    assert storage.exists(key=seeded.file.storage_key) is True

    blocked_logs = [log for log in _actor_logs(session) if log.action == "DELETE_BLOCKED"]
    assert len(blocked_logs) == 1


@pytest.mark.asyncio
async def test_unpublish_then_delete_succeeds() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    seeded = await _seed_uploaded_document(session, storage, exhibitor_id=exhibitor_id)
    await document_service.mark_current_version_published(session, document=seeded.document)

    await document_service.unpublish_document(session, document=seeded.document)
    assert seeded.document.published_file_id is None

    await document_service.delete_document(
        session, storage, document=seeded.document, actor_user_id=uuid.uuid4()
    )
    assert seeded.document.document_id not in session.store[SourceDocument]


@pytest.mark.asyncio
async def test_download_round_trip_issues_token_resolves_bytes_and_logs_both_actions() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    exhibitor_id = uuid.uuid4()
    seeded = await _seed_uploaded_document(session, storage, exhibitor_id=exhibitor_id)

    token, expires_at = await document_service.issue_download_token(
        session, document=seeded.document, file=seeded.file, actor_user_id=uuid.uuid4(),
        secret="test-secret", ttl_seconds=300,
    )
    assert expires_at > datetime.now(UTC)

    document, file, data = await document_service.resolve_download(
        session, storage, token=token, secret="test-secret"
    )
    assert data == _PDF_BYTES
    assert document.document_id == seeded.document.document_id
    assert file.file_id == seeded.file.file_id

    actions = {log.action for log in _actor_logs(session)}
    assert {"DOWNLOAD_TOKEN_ISSUED", "DOWNLOAD"} <= actions


@pytest.mark.asyncio
async def test_resolve_download_rejects_invalid_token() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    with pytest.raises(document_service.DownloadTokenInvalidError):
        await document_service.resolve_download(
            session, storage, token="garbage-token", secret="test-secret"
        )


@pytest.mark.asyncio
async def test_create_processing_job_requires_an_uploaded_version() -> None:
    session = _FakeAsyncSession()
    document = SourceDocument(
        document_id=uuid.uuid4(), tenant_id=uuid.uuid4(), exhibitor_id=uuid.uuid4(),
        document_type="CATALOG", status="UPLOADED", current_file_id=None,
    )
    with pytest.raises(document_service.DocumentNotFoundError):
        await document_service.create_processing_job(
            session, document=document, actor_user_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_create_processing_job_logs_process_requested() -> None:
    session = _FakeAsyncSession()
    storage = InMemoryStorageAdapter()
    seeded = await _seed_uploaded_document(session, storage, exhibitor_id=uuid.uuid4())

    job = await document_service.create_processing_job(
        session, document=seeded.document, actor_user_id=uuid.uuid4()
    )
    assert job.status == "PENDING"
    assert seeded.document.status == "PROCESSING"
    process_logs = [log for log in _actor_logs(session) if log.action == "PROCESS_REQUESTED"]
    assert len(process_logs) == 1


# ===========================================================================
# 3. 라우터 계층 - document_router.router만 담은 전용 앱 (api.py에는 등록하지 않는다)
#
# 통합 STEP 20: 행위자는 더 이상 클라이언트가 보내는 헤더에서 오지 않는다. 테스트는
# app.core.router_auth.get_actor_user_id를 dependency_overrides로 대체해 "검증된 세션이
# 이 사용자를 내놓았다"를 표현한다 - override를 걸지 않으면 실제 세션 검증이 돌아
# 401 AUTH_REQUIRED가 난다(아래 인증 계약 테스트가 그것을 고정한다).
# ===========================================================================


def _build_test_app(actor_user_id: uuid.UUID | None = None) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(document_router.router)
    if actor_user_id is not None:
        app.dependency_overrides[get_actor_user_id] = lambda: actor_user_id
    return app


#: STEP 20 검증 대상: 서명 토큰이 인가 증거인 download 경로만 principal을 요구하지 않는다.
_PUBLIC_DOCUMENT_ROUTES = {("GET", "/partner/documents/download")}


def _document_routes() -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for route in document_router.router.routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):  # type: ignore[attr-defined]
            routes.append((method, route.path))  # type: ignore[attr-defined]
    return routes


def test_every_document_route_except_the_signed_download_requires_a_session() -> None:
    """STEP 20: 헤더만 보내는 호출은 더 이상 통하지 않는다 - 세션 없으면 401."""

    app = _build_test_app()

    async def fake_db():
        yield object()

    app.dependency_overrides[document_router.get_db] = fake_db
    client = TestClient(app)

    checked = 0
    for method, path in _document_routes():
        if (method, path) in _PUBLIC_DOCUMENT_ROUTES:
            continue
        url = path.replace("{document_id}", str(uuid.uuid4()))
        url = f"{url}?exhibitor_id={uuid.uuid4()}"
        response = client.request(
            method,
            url,
            headers={"X-Actor-User-Id": str(uuid.uuid4())},
        )
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["code"] == "AUTH_REQUIRED"
        checked += 1

    assert checked == 6


def test_the_signed_download_route_has_no_principal_dependency() -> None:
    """서명 토큰 자체가 인가 증거다(모듈 docstring) - principal을 요구하면 서명 URL 모델이 깨진다."""

    app = _build_test_app()

    async def fake_db():
        yield object()

    app.dependency_overrides[document_router.get_db] = fake_db
    client = TestClient(app)

    response = client.get("/partner/documents/download?token=garbage")

    # 401이 아니라 "토큰이 틀렸다"까지 실제로 도달해야 한다.
    assert response.status_code == 404
    assert response.json()["detail"] == "DOWNLOAD_TOKEN_INVALID_OR_EXPIRED"


def test_no_router_module_reads_the_actor_from_a_client_header() -> None:
    """STEP 20 회귀 방지: 사설 헤더 스텁이 다시 기어들어오면 실패한다."""

    source = inspect.getsource(document_router)

    assert "X-Actor-User-Id" not in source
    assert "Header(" not in source
    assert document_router.get_actor_user_id is get_actor_user_id


def test_cross_company_access_is_denied_with_403(monkeypatch: pytest.MonkeyPatch) -> None:
    async def deny(db: Any, *, actor_user_id: Any, exhibitor_id: Any) -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="RESOURCE_FORBIDDEN")

    monkeypatch.setattr(document_router, "require_exhibitor_access", deny)

    app = _build_test_app(actor_user_id=uuid.uuid4())

    async def fake_db():
        yield object()

    app.dependency_overrides[document_router.get_db] = fake_db
    client = TestClient(app)

    response = client.get(f"/partner/documents?exhibitor_id={uuid.uuid4()}")
    assert response.status_code == 403
    assert response.json()["detail"] == "RESOURCE_FORBIDDEN"


def test_upload_endpoint_returns_documented_fields_and_no_storage_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exhibitor_id = uuid.uuid4()
    document_id = uuid.uuid4()
    file_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async def grant(db: Any, *, actor_user_id: Any, exhibitor_id: Any) -> None:
        return None

    async def fake_exhibitor_or_404(db: Any, exhibitor_id_arg: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id_arg)

    async def fake_upload(db: Any, storage: Any, **kwargs: Any) -> document_service.UploadResult:
        document = SourceDocument(
            document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id,
            document_type="CATALOG", status="PROCESSING", current_file_id=file_id,
        )
        file = DocumentFile(
            file_id=file_id, document_id=document_id, version_no=1,
            storage_key="exhibitor/should/never/appear/in/response.pdf",
            original_filename="brochure.pdf", declared_extension="pdf",
            mime_type="application/pdf", size_bytes=len(_PDF_BYTES),
            content_hash=sha256_hex(_PDF_BYTES),
        )
        job = DocumentProcessingJob(
            processing_job_id=job_id, document_id=document_id, file_id=file_id, status="PENDING"
        )
        return document_service.UploadResult(document=document, file=file, processing_job=job)

    monkeypatch.setattr(document_router, "require_exhibitor_access", grant)
    monkeypatch.setattr(document_router, "_get_exhibitor_or_404", fake_exhibitor_or_404)
    monkeypatch.setattr(document_service, "upload_document", fake_upload)

    app = _build_test_app(actor_user_id=uuid.uuid4())

    async def fake_db():
        yield object()

    app.dependency_overrides[document_router.get_db] = fake_db
    client = TestClient(app)

    response = client.post(
        "/partner/documents",
        data={"exhibitor_id": str(exhibitor_id), "document_type": "CATALOG"},
        files={"file": ("brochure.pdf", _PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "document_id": str(document_id),
        "status": "PROCESSING",
        "filename": "brochure.pdf",
        "document_type": "CATALOG",
        "size_bytes": len(_PDF_BYTES),
        "processing_job_id": str(job_id),
        "version_no": 1,
    }
    assert "storage_key" not in response.text
    assert "should/never/appear" not in response.text


def test_delete_endpoint_returns_409_when_blocked_by_published_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exhibitor_id = uuid.uuid4()
    document_id = uuid.uuid4()
    published_file_id = uuid.uuid4()

    async def grant(db: Any, *, actor_user_id: Any, exhibitor_id: Any) -> None:
        return None

    async def fake_get_document(db: Any, *, document_id: Any) -> Any:
        return SourceDocument(
            document_id=document_id, tenant_id=uuid.uuid4(), exhibitor_id=exhibitor_id,
            document_type="CATALOG", status="PROCESSED", published_file_id=published_file_id,
        )

    async def fake_delete(db: Any, storage: Any, *, document: Any, actor_user_id: Any) -> None:
        raise document_service.DocumentDeleteBlockedError(
            document_id=document.document_id, published_file_id=published_file_id
        )

    monkeypatch.setattr(document_router, "require_exhibitor_access", grant)
    monkeypatch.setattr(document_service, "get_document", fake_get_document)
    monkeypatch.setattr(document_service, "delete_document", fake_delete)

    app = _build_test_app(actor_user_id=uuid.uuid4())

    async def fake_db():
        yield object()

    app.dependency_overrides[document_router.get_db] = fake_db
    client = TestClient(app)

    response = client.delete(
        f"/partner/documents/{document_id}?exhibitor_id={exhibitor_id}"
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "DOCUMENT_DELETE_BLOCKED_PUBLISHED"
    assert body["detail"]["published_file_id"] == str(published_file_id)


def test_build_document_router_returns_the_same_router_instance() -> None:
    assert document_router.build_document_router() is document_router.router

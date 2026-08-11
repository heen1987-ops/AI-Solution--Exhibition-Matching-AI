"""문서 업로드/조회/삭제/처리요청/다운로드의 DB 연계 비즈니스 로직.

이 모듈은 라우터(app/api/v1/routers/document.py)가 얇게 위임하는 대상이다. 검증(확장자/
크기/매직바이트)은 app/services/document/validation.py의 순수함수가 담당하고, 여기서는
그 결과를 DB 행/스토리지 바이트에 연결하는 책임만 진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common import new_uuid7
from app.models.document import (
    DocumentAccessLog,
    DocumentFile,
    DocumentProcessingJob,
    SourceDocument,
)
from app.services.document import tokens as token_service
from app.services.document.hashing import sha256_hex
from app.services.document.storage import (
    ObjectStorageAdapter,
    StorageKeyError,
    build_storage_key,
)
from app.services.document.validation import DocumentValidationError, validate_upload


class DocumentNotFoundError(Exception):
    pass


class DocumentDuplicateError(Exception):
    """같은 업체 안에 동일 content-hash 문서가 이미 있을 때."""

    def __init__(self, existing_document_id: UUID) -> None:
        super().__init__("duplicate document content")
        self.existing_document_id = existing_document_id


class DocumentDeleteBlockedError(Exception):
    """게시된 콘텐츠가 참조 중인 버전이 있어 하드삭제를 거부할 때."""

    def __init__(self, document_id: UUID, published_file_id: UUID) -> None:
        super().__init__("document is referenced by published content")
        self.document_id = document_id
        self.published_file_id = published_file_id


class DownloadTokenInvalidError(Exception):
    pass


@dataclass(frozen=True)
class UploadResult:
    document: SourceDocument
    file: DocumentFile
    processing_job: DocumentProcessingJob


async def _log_access(
    db: AsyncSession,
    *,
    document_id: UUID,
    action: str,
    file_id: UUID | None = None,
    exhibitor_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    detail: dict | None = None,
) -> None:
    """감사 로그 행을 세션에 add한다 - 커밋은 호출부(같은 트랜잭션)가 책임진다.

    document_id/file_id는 의도적으로 FK가 아니므로(app/models/document.py 모듈 docstring
    결정 3번) 문서가 하드삭제된 뒤에도 DELETE 로그 자체는 남길 수 있다.
    """

    db.add(
        DocumentAccessLog(
            document_id=document_id,
            file_id=file_id,
            exhibitor_id=exhibitor_id,
            actor_user_id=actor_user_id,
            action=action,
            detail_json=detail,
        )
    )


async def find_duplicate(
    db: AsyncSession, *, exhibitor_id: UUID, content_hash: str
) -> SourceDocument | None:
    """같은 업체 소속 문서 중 동일 content_hash를 가진 (삭제되지 않은) 문서를 찾는다.

    source_document.content_hash는 "현재 버전"의 캐시값이므로, 문서가 여러 버전을 거쳐온
    경우 과거 버전과의 중복은 이 조회로 잡지 못한다 - MVP 범위에서는 "지금 최신 상태와
    동일한 내용을 다시 올리는" 흔한 실수만 막는다.
    """

    stmt = select(SourceDocument).where(
        SourceDocument.exhibitor_id == exhibitor_id,
        SourceDocument.content_hash == content_hash,
    )
    return (await db.execute(stmt)).scalars().first()


async def upload_document(
    db: AsyncSession,
    storage: ObjectStorageAdapter,
    *,
    tenant_id: UUID,
    exhibitor_id: UUID,
    event_id: UUID | None,
    document_type: str,
    filename: str,
    data: bytes,
    declared_content_type: str | None,
    actor_user_id: UUID | None,
    max_bytes: int,
) -> UploadResult:
    """신규 문서를 업로드한다 (첫 버전 생성 + 처리작업 생성).

    검증 실패는 DocumentValidationError, 중복은 DocumentDuplicateError를 그대로 던진다 -
    라우터가 이를 각각 400/415/413 계열과 409로 매핑한다.
    """

    validated = validate_upload(
        filename=filename,
        size_bytes=len(data),
        data=data,
        declared_content_type=declared_content_type,
        max_bytes=max_bytes,
    )

    content_hash = sha256_hex(data)
    duplicate = await find_duplicate(db, exhibitor_id=exhibitor_id, content_hash=content_hash)
    if duplicate is not None:
        raise DocumentDuplicateError(existing_document_id=duplicate.document_id)

    document = SourceDocument(
        tenant_id=tenant_id,
        exhibitor_id=exhibitor_id,
        event_id=event_id,
        document_type=document_type,
        status="UPLOADED",
    )
    db.add(document)
    await db.flush()  # document_id를 확정해야 DocumentFile.document_id를 채울 수 있다.

    file_id = new_uuid7()
    storage_key = build_storage_key(
        exhibitor_id=exhibitor_id,
        document_id=document.document_id,
        file_id=file_id,
        extension=validated.extension,
    )

    document_file = DocumentFile(
        file_id=file_id,
        document_id=document.document_id,
        version_no=1,
        storage_key=storage_key,
        original_filename=filename,
        declared_extension=validated.extension,
        mime_type=declared_content_type or f"application/octet-stream; sniffed={validated.sniffed_kind}",
        size_bytes=len(data),
        content_hash=content_hash,
        uploaded_by_user_id=actor_user_id,
    )
    db.add(document_file)

    # DB 행을 먼저 세션에 넣은 뒤 스토리지에 쓴다. 스토리지 쓰기가 실패하면 이 예외가
    # 라우터까지 전파되어 트랜잭션이 커밋되지 않는다(get_db가 예외 시 rollback한다) -
    # "DB엔 있는데 파일은 없는" 상태를 피한다. 반대 순서(스토리지 먼저)라면 DB insert 실패
    # 시 고아 오브젝트가 남을 수 있어, 되돌리기 더 쉬운 이 순서를 택했다.
    storage.put(key=storage_key, data=data)

    document.current_file_id = file_id
    document.original_filename = filename
    document.mime_type = document_file.mime_type
    document.size_bytes = len(data)
    document.content_hash = content_hash

    processing_job = DocumentProcessingJob(
        document_id=document.document_id,
        file_id=file_id,
        status="PENDING",
        requested_by_user_id=actor_user_id,
    )
    db.add(processing_job)
    document.status = "PROCESSING"

    await _log_access(
        db,
        document_id=document.document_id,
        file_id=file_id,
        exhibitor_id=exhibitor_id,
        actor_user_id=actor_user_id,
        action="UPLOAD",
        detail={"filename": filename, "size_bytes": len(data)},
    )

    await db.commit()
    await db.refresh(document)
    await db.refresh(document_file)
    await db.refresh(processing_job)

    return UploadResult(document=document, file=document_file, processing_job=processing_job)


async def list_documents(db: AsyncSession, *, exhibitor_id: UUID) -> list[SourceDocument]:
    stmt = (
        select(SourceDocument)
        .where(SourceDocument.exhibitor_id == exhibitor_id)
        .order_by(SourceDocument.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_document(db: AsyncSession, *, document_id: UUID) -> SourceDocument | None:
    return await db.get(SourceDocument, document_id)


async def get_document_versions(db: AsyncSession, *, document_id: UUID) -> list[DocumentFile]:
    stmt = (
        select(DocumentFile)
        .where(DocumentFile.document_id == document_id)
        .order_by(DocumentFile.version_no.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_document(
    db: AsyncSession,
    storage: ObjectStorageAdapter,
    *,
    document: SourceDocument,
    actor_user_id: UUID | None,
) -> None:
    """문서와 모든 버전을 하드삭제한다.

    published_file_id가 채워져 있으면(=게시된 콘텐츠가 참조 중) 거부한다 - 작업 지시 삭제
    정책: "이미 게시된 콘텐츠가 참조하는 문서는 그냥 삭제할 수 없다. 새 버전을 만들거나 먼저
    게시를 취소해야 한다." 이 함수는 그 정책의 강제 지점이다.
    """

    if document.published_file_id is not None:
        await _log_access(
            db,
            document_id=document.document_id,
            file_id=document.published_file_id,
            exhibitor_id=document.exhibitor_id,
            actor_user_id=actor_user_id,
            action="DELETE_BLOCKED",
            detail={"reason": "PUBLISHED_CONTENT_REFERENCE"},
        )
        await db.commit()
        raise DocumentDeleteBlockedError(
            document_id=document.document_id, published_file_id=document.published_file_id
        )

    versions = await get_document_versions(db, document_id=document.document_id)
    for version in versions:
        try:
            storage.delete(key=version.storage_key)
        except StorageKeyError:
            # 스토리지에 이미 없어도(예: 이전 실패한 삭제 재시도) DB 정리는 계속 진행한다.
            pass
        await db.delete(version)

    await _log_access(
        db,
        document_id=document.document_id,
        exhibitor_id=document.exhibitor_id,
        actor_user_id=actor_user_id,
        action="DELETE",
        detail={"version_count": len(versions)},
    )

    await db.delete(document)
    await db.commit()


async def create_processing_job(
    db: AsyncSession, *, document: SourceDocument, actor_user_id: UUID | None,
) -> DocumentProcessingJob:
    """재처리(또는 최초 처리 재시도)를 요청한다. 실제 실행은 워커 트랙의 몫 (known limitation)."""

    if document.current_file_id is None:
        raise DocumentNotFoundError("document has no uploaded version to process")

    job = DocumentProcessingJob(
        document_id=document.document_id,
        file_id=document.current_file_id,
        status="PENDING",
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    document.status = "PROCESSING"

    await _log_access(
        db,
        document_id=document.document_id,
        file_id=document.current_file_id,
        exhibitor_id=document.exhibitor_id,
        actor_user_id=actor_user_id,
        action="PROCESS_REQUESTED",
    )

    await db.commit()
    await db.refresh(job)
    return job


async def issue_download_token(
    db: AsyncSession,
    *,
    document: SourceDocument,
    file: DocumentFile,
    actor_user_id: UUID | None,
    secret: str,
    ttl_seconds: int,
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    token = token_service.issue_download_token(
        document_id=document.document_id,
        file_id=file.file_id,
        exhibitor_id=document.exhibitor_id,
        expires_at=expires_at,
        secret=secret,
    )

    await _log_access(
        db,
        document_id=document.document_id,
        file_id=file.file_id,
        exhibitor_id=document.exhibitor_id,
        actor_user_id=actor_user_id,
        action="DOWNLOAD_TOKEN_ISSUED",
    )
    await db.commit()

    return token, expires_at


async def resolve_download(
    db: AsyncSession, storage: ObjectStorageAdapter, *, token: str, secret: str,
) -> tuple[SourceDocument, DocumentFile, bytes]:
    """다운로드 토큰을 검증하고 실제 바이트를 반환한다. storage_key는 이 함수 밖으로 절대
    나가지 않는다 - 반환값은 바이트 자체다."""

    claims = token_service.verify_download_token(token, secret=secret)
    if claims is None:
        raise DownloadTokenInvalidError("invalid or expired download token")

    file = await db.get(DocumentFile, claims.file_id)
    if file is None or file.document_id != claims.document_id:
        raise DownloadTokenInvalidError("token does not match any stored document version")

    document = await db.get(SourceDocument, claims.document_id)
    if document is None or document.exhibitor_id != claims.exhibitor_id:
        raise DownloadTokenInvalidError("token does not match any stored document")

    data = storage.get(key=file.storage_key)

    await _log_access(
        db,
        document_id=document.document_id,
        file_id=file.file_id,
        exhibitor_id=document.exhibitor_id,
        action="DOWNLOAD",
    )
    await db.commit()

    return document, file, data


async def mark_current_version_published(db: AsyncSession, *, document: SourceDocument) -> None:
    """운영자 승인 워크플로(이 작업 범위 밖)가 호출할 내부 훅.

    현재 버전을 "게시된 콘텐츠가 참조 중"으로 표시해 이후 하드삭제를 막는다. 실제 승인
    UI/서비스와의 연결은 TODO (app/models/document.py 모듈 docstring 결정 2번 참고).
    """

    document.published_file_id = document.current_file_id
    await db.commit()


async def unpublish_document(db: AsyncSession, *, document: SourceDocument) -> None:
    """게시 참조를 해제해 다시 삭제 가능한 상태로 되돌린다."""

    document.published_file_id = None
    await db.commit()


__all__ = [
    "DocumentDeleteBlockedError",
    "DocumentDuplicateError",
    "DocumentNotFoundError",
    "DocumentValidationError",
    "DownloadTokenInvalidError",
    "UploadResult",
    "create_processing_job",
    "delete_document",
    "find_duplicate",
    "get_document",
    "get_document_versions",
    "issue_download_token",
    "list_documents",
    "mark_current_version_published",
    "resolve_download",
    "unpublish_document",
    "upload_document",
]

"""참가업체 문서 업로드 API의 Pydantic 스키마.

중요 - storage_key를 절대 노출하지 않는다
-----------------------------------------
아래 어떤 Read/Response 모델도 app/models/document.py의 storage_key(내부 저장소 참조값)를
필드로 갖지 않는다. 다운로드는 항상 DownloadTokenRead의 단기 서명 토큰을 통해서만 이루어진다
(작업 지시: "raw storage path나 서명되지 않은 URL을 절대 반환하지 않는다").
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """POST /partner/documents 성공 응답. 작업 지시가 명시한 필드만 담는다."""

    document_id: UUID
    status: str
    filename: str
    document_type: str
    size_bytes: int
    processing_job_id: UUID | None = None
    version_no: int


class DocumentFileVersionRead(BaseModel):
    file_id: UUID
    version_no: int
    filename: str
    mime_type: str
    size_bytes: int
    content_hash: str
    uploaded_at: datetime
    is_current: bool
    is_published: bool


class DocumentRead(BaseModel):
    document_id: UUID
    exhibitor_id: UUID
    event_id: UUID | None = None
    document_type: str
    status: str
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    content_hash: str | None = None
    version_count: int
    is_published: bool
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentRead]


class DocumentDetailResponse(BaseModel):
    document: DocumentRead
    versions: list[DocumentFileVersionRead]


class ProcessingJobRead(BaseModel):
    processing_job_id: UUID
    document_id: UUID
    status: str
    created_at: datetime


class DownloadTokenRead(BaseModel):
    """서명된 URL 대체물. 실제 저장소 경로는 어디에도 없다 - token만 짧은 시간 동안 유효하다."""

    token: str
    expires_at: datetime


class DeleteResponse(BaseModel):
    document_id: UUID
    deleted: bool


class DeleteBlockedDetail(BaseModel):
    """DELETE가 게시된 콘텐츠 참조로 차단됐을 때의 오류 상세 (HTTPException.detail로 사용)."""

    code: str = "DOCUMENT_DELETE_BLOCKED_PUBLISHED"
    message: str = (
        "이 문서 버전은 이미 게시된 콘텐츠가 참조하고 있어 바로 삭제할 수 없습니다. "
        "새 버전을 업로드하거나 먼저 게시를 취소하세요."
    )
    document_id: UUID
    published_file_id: UUID


class DuplicateDocumentDetail(BaseModel):
    code: str = "DOCUMENT_DUPLICATE_CONTENT"
    message: str = "동일한 내용의 문서가 이미 등록되어 있습니다."
    existing_document_id: UUID


class DocumentUploadForm(BaseModel):
    """multipart 업로드 폼 필드 검증용 (파일 자체는 UploadFile로 별도 수신).

    라우터가 Form(...) 파라미터를 개별적으로 선언하는 대신 이 모델로 한 번에 검증하지는
    않는다(FastAPI의 Form+File 혼합 제약) - 라우터 시그니처의 문서화용으로만 남긴다.
    """

    exhibitor_id: UUID
    document_type: str = Field(description="DOCUMENT_TYPES 상수 중 하나")
    event_id: UUID | None = None

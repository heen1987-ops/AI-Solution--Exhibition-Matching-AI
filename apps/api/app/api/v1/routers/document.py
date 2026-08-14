"""참가업체 문서 업로드 API 라우터 (BACKEND-DOCUMENT, WAVE 2D).

경로
----
    POST   /partner/documents                          - 업로드 (자기 업체만)
    GET    /partner/documents                           - 목록 (자기 업체만, ?exhibitor_id=)
    GET    /partner/documents/{document_id}              - 상세 + 버전 목록
    DELETE /partner/documents/{document_id}               - 삭제 (게시참조 시 차단)
    POST   /partner/documents/{document_id}/process        - (재)처리 요청
    GET    /partner/documents/{document_id}/download-token  - 단기 서명 다운로드 토큰 발급
    GET    /partner/documents/download                    - 토큰으로 실제 바이트 조회

이 router는 자체 prefix가 없다 - app/api/v1/api.py(공용 aggregator, 이 작업 범위 밖)가 추가
prefix 없이 include해야 위 경로가 최종적으로 `<API_V1_PREFIX>/partner/documents...`가 된다.
integrator가 모듈 자체를 include하거나(``from app.api.v1.routers import document`` 후
``document.router``) 아래 build_document_router()를 호출해 얻은 APIRouter를 include해도
동일한 라우터 인스턴스를 얻는다.

인증/인가 (통합 STEP 20)
------------------------
원본에 있던 클라이언트 제어 행위자 헤더 스텁(``get_actor_user_id``)과 사설
``_require_exhibitor_access`` 복사본은 삭제했다. 이제 행위자는 검증된 세션/서비스 JWT
principal에서만 파생하고(``app/core/router_auth.py``), 인가 규칙도 그 공용 어댑터 하나만
쓴다. 인가 규칙 자체(소속 EXHIBITOR이거나 OPERATOR/ADMIN)는 바뀌지 않았다.

다운로드 흐름과 "서명된 URL 대체" 요건
----------------------------------------
GET .../download-token은 raw storage path를 절대 포함하지 않는 단기 서명 토큰만 돌려준다.
실제 바이트는 별도 엔드포인트(GET /partner/documents/download?token=...)에서, 그 토큰
자체를 인가 증거로 검증해 스트리밍한다 - 이 두 번째 엔드포인트는 principal 의존성을
의도적으로 갖지 않는다(SECRET_KEY로 서명된 토큰은 인증된 /download-token 경로가
require_exhibitor_access를 통과한 뒤에만 발급되며 raw path를 노출하지 않는다. 서명된 URL을
클릭하는 것과 동등한 모델이므로 principal을 덧붙여도 얻는 것이 없다 - 통합 계획 STEP 20).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.router_auth import get_actor_user_id, require_exhibitor_access
from app.db.session import get_db
from app.models.document import SourceDocument
from app.models.exhibitor import Exhibitor
from app.schemas.document import (
    DeleteResponse,
    DocumentDetailResponse,
    DocumentFileVersionRead,
    DocumentListResponse,
    DocumentRead,
    DocumentUploadResponse,
    DownloadTokenRead,
    ProcessingJobRead,
)
from app.services.document import service as document_service
from app.services.document.storage import (
    ObjectStorageAdapter,
    get_local_storage_adapter,
)
from app.services.document.validation import DocumentValidationError

router = APIRouter()


def build_document_router() -> APIRouter:
    """작업 지시가 명시한 등록 함수. 통합 단계가 이 라우터를 얻는 두 번째 방법일 뿐,
    아래 ``router``와 동일한 인스턴스를 반환한다(핸들러를 중복 등록하지 않는다)."""

    return router


async def _get_exhibitor_or_404(db: AsyncSession, exhibitor_id: UUID) -> Exhibitor:
    exhibitor = await db.get(Exhibitor, exhibitor_id)
    if exhibitor is None or exhibitor.deleted_at is not None:
        raise HTTPException(status_code=404, detail="EXHIBITOR_NOT_FOUND")
    return exhibitor


async def _get_document_or_404(db: AsyncSession, document_id: UUID) -> SourceDocument:
    document = await document_service.get_document(db, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
    return document


def get_storage_adapter() -> ObjectStorageAdapter:
    return get_local_storage_adapter()


def _validation_error_status(code: str) -> int:
    """검증 오류코드를 HTTP 상태로 매핑한다."""

    if code == "FILE_TOO_LARGE":
        return 413
    if code in ("EXTENSION_NOT_ALLOWED", "EXTENSION_MISSING", "MIME_EXTENSION_MISMATCH", "CONTENT_NOT_ALLOWED"):
        return 415
    return 400


def _to_document_read(document: SourceDocument) -> DocumentRead:
    # version_count=0은 placeholder다 - 호출부가 get_document_versions 결과 길이로 덮어쓴다
    # (여기서 매번 쿼리하면 목록 조회가 N+1이 되므로, 호출부가 이미 한 번 조회한 값을 재사용).
    return DocumentRead(
        document_id=document.document_id,
        exhibitor_id=document.exhibitor_id,
        event_id=document.event_id,
        document_type=document.document_type,
        status=document.status,
        filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        content_hash=document.content_hash,
        version_count=0,
        is_published=document.published_file_id is not None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


# ---------------------------------------------------------------------------
# 업로드
# ---------------------------------------------------------------------------


@router.post("/partner/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    exhibitor_id: UUID = Form(...),
    document_type: str = Form(...),
    event_id: UUID | None = Form(None),
    file: UploadFile = File(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorageAdapter = Depends(get_storage_adapter),
) -> DocumentUploadResponse:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    exhibitor = await _get_exhibitor_or_404(db, exhibitor_id)

    if document_type not in _ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="DOCUMENT_TYPE_NOT_ALLOWED")

    data = await file.read()
    settings = get_settings()

    try:
        result = await document_service.upload_document(
            db,
            storage,
            tenant_id=exhibitor.tenant_id,
            exhibitor_id=exhibitor_id,
            event_id=event_id,
            document_type=document_type,
            filename=file.filename or "unnamed",
            data=data,
            declared_content_type=file.content_type,
            actor_user_id=actor_user_id,
            max_bytes=settings.DOCUMENT_MAX_UPLOAD_BYTES,
        )
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=_validation_error_status(exc.code),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except document_service.DocumentDuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_DUPLICATE_CONTENT",
                "message": "동일한 내용의 문서가 이미 등록되어 있습니다.",
                "existing_document_id": str(exc.existing_document_id),
            },
        ) from exc

    return DocumentUploadResponse(
        document_id=result.document.document_id,
        status=result.document.status,
        filename=result.file.original_filename,
        document_type=result.document.document_type,
        size_bytes=result.file.size_bytes,
        processing_job_id=result.processing_job.processing_job_id,
        version_no=result.file.version_no,
    )


# ---------------------------------------------------------------------------
# 다운로드 (토큰으로 실제 바이트 조회)
#
# 등록 순서 주의: 이 경로는 반드시 ``/partner/documents/{document_id}``보다 먼저
# 선언돼야 한다. FastAPI/Starlette는 경로 파라미터를 ``[^/]+``로 컴파일하므로 나중에
# 선언하면 리터럴 "download"가 ``{document_id}``에 먹혀서 이 엔드포인트에 영원히
# 도달하지 못한다(원본 WAVE 2D 파일은 이 함수를 맨 아래에 두어 실제로 가려져 있었다).
# ---------------------------------------------------------------------------


@router.get("/partner/documents/download")
async def download_by_token(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorageAdapter = Depends(get_storage_adapter),
) -> Response:
    """토큰 자체가 인가 증거다 - principal 의존성을 두지 않는다(모듈 docstring 참고)."""

    settings = get_settings()
    try:
        document, file, data = await document_service.resolve_download(
            db, storage, token=token, secret=settings.SECRET_KEY
        )
    except document_service.DownloadTokenInvalidError as exc:
        raise HTTPException(status_code=404, detail="DOWNLOAD_TOKEN_INVALID_OR_EXPIRED") from exc
    del document

    return Response(
        content=data,
        media_type=file.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file.original_filename}"'},
    )


# ---------------------------------------------------------------------------
# 목록/상세
# ---------------------------------------------------------------------------


@router.get("/partner/documents", response_model=DocumentListResponse)
async def list_documents(
    exhibitor_id: UUID = Query(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)

    documents = await document_service.list_documents(db, exhibitor_id=exhibitor_id)
    items = []
    for document in documents:
        versions = await document_service.get_document_versions(db, document_id=document.document_id)
        read = _to_document_read(document)
        read.version_count = len(versions)
        items.append(read)
    return DocumentListResponse(items=items)


@router.get("/partner/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(
    document_id: UUID,
    exhibitor_id: UUID = Query(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentDetailResponse:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    document = await _get_document_or_404(db, document_id)
    if document.exhibitor_id != exhibitor_id:
        # 존재는 하지만 다른 업체 소유 - 존재 여부 자체를 흘리지 않도록 404로 통일한다
        # (인터페이스 명세 23절 "다른 업체의 리소스를 조회할 수 없다"와 동일한 원칙).
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    versions = await document_service.get_document_versions(db, document_id=document_id)
    read = _to_document_read(document)
    read.version_count = len(versions)

    version_reads = [
        DocumentFileVersionRead(
            file_id=v.file_id,
            version_no=v.version_no,
            filename=v.original_filename,
            mime_type=v.mime_type,
            size_bytes=v.size_bytes,
            content_hash=v.content_hash,
            uploaded_at=v.uploaded_at,
            is_current=(v.file_id == document.current_file_id),
            is_published=(v.file_id == document.published_file_id),
        )
        for v in versions
    ]
    return DocumentDetailResponse(document=read, versions=version_reads)


# ---------------------------------------------------------------------------
# 삭제
# ---------------------------------------------------------------------------


@router.delete("/partner/documents/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: UUID,
    exhibitor_id: UUID = Query(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorageAdapter = Depends(get_storage_adapter),
) -> DeleteResponse:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    document = await _get_document_or_404(db, document_id)
    if document.exhibitor_id != exhibitor_id:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    try:
        await document_service.delete_document(
            db, storage, document=document, actor_user_id=actor_user_id
        )
    except document_service.DocumentDeleteBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_DELETE_BLOCKED_PUBLISHED",
                "message": (
                    "이 문서는 이미 게시된 콘텐츠가 참조하고 있어 바로 삭제할 수 없습니다. "
                    "새 버전을 업로드하거나 먼저 게시를 취소하세요."
                ),
                "document_id": str(exc.document_id),
                "published_file_id": str(exc.published_file_id),
            },
        ) from exc

    return DeleteResponse(document_id=document_id, deleted=True)


# ---------------------------------------------------------------------------
# 처리 요청
# ---------------------------------------------------------------------------


@router.post("/partner/documents/{document_id}/process", response_model=ProcessingJobRead)
async def request_processing(
    document_id: UUID,
    exhibitor_id: UUID = Query(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> ProcessingJobRead:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    document = await _get_document_or_404(db, document_id)
    if document.exhibitor_id != exhibitor_id:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    try:
        job = await document_service.create_processing_job(
            db, document=document, actor_user_id=actor_user_id
        )
    except document_service.DocumentNotFoundError as exc:
        raise HTTPException(status_code=422, detail="DOCUMENT_HAS_NO_VERSION") from exc

    return ProcessingJobRead(
        processing_job_id=job.processing_job_id,
        document_id=job.document_id,
        status=job.status,
        created_at=job.created_at,
    )


# ---------------------------------------------------------------------------
# 다운로드 (서명 토큰 발급 - 실제 조회 경로는 위쪽 "다운로드" 절 참고)
# ---------------------------------------------------------------------------


@router.get(
    "/partner/documents/{document_id}/download-token", response_model=DownloadTokenRead
)
async def issue_download_token(
    document_id: UUID,
    exhibitor_id: UUID = Query(...),
    actor_user_id: UUID = Depends(get_actor_user_id),
    db: AsyncSession = Depends(get_db),
) -> DownloadTokenRead:
    await require_exhibitor_access(db, actor_user_id=actor_user_id, exhibitor_id=exhibitor_id)
    document = await _get_document_or_404(db, document_id)
    if document.exhibitor_id != exhibitor_id or document.current_file_id is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    versions = await document_service.get_document_versions(db, document_id=document_id)
    current = next((v for v in versions if v.file_id == document.current_file_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    settings = get_settings()
    token, expires_at = await document_service.issue_download_token(
        db,
        document=document,
        file=current,
        actor_user_id=actor_user_id,
        secret=settings.SECRET_KEY,
        ttl_seconds=settings.DOCUMENT_DOWNLOAD_TOKEN_TTL_SECONDS,
    )
    return DownloadTokenRead(token=token, expires_at=expires_at)


_ALLOWED_DOCUMENT_TYPES = frozenset(
    {"CATALOG", "CERTIFICATE", "PRICE_LIST", "COMPANY_PROFILE", "PRODUCT_SPEC", "OTHER"}
)

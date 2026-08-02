"""원천 사이트(backju.kr) 배치 import 수신 라우터.

경로 근거와 우선순위
--------------------
docs/2026-backju-ai-matching-service-design.md 8.3절은 `/v1/events/{eventId}/imports/...`
형태를 보여 주지만, 문서 우선순위 규칙(작업 지시: 인터페이스 명세 > db-erd > 개별 단계
문서)에 따라 docs/frontend-backend-ai-interface-spec.md 18.1절의 실제 경로를 그대로 쓴다:

    POST /admin/imports/visitors
    POST /admin/imports/exhibitors
    POST /admin/imports/products
    GET  /admin/imports/{import_id}
    GET  /admin/imports/{import_id}/errors

이 라우터는 자체 prefix를 갖지 않는다. app/api/v1/api.py(공용 aggregator, 이 작업 범위 밖)가
이 router를 추가 prefix 없이 include해야 위 경로가 최종적으로 `<API_V1_PREFIX>/admin/imports/...`
가 된다.

인증·경계
-----------
모든 import 경로는 검증된 EVENT_ADMIN + 최근 MFA를 요구한다. 요청의 tenant/event는
세션에서 로드한 명시적 역할 부여와 다시 대조하며, 헤더가 권한을 만들지 않는다.

멱등·오류격리 구현
-------------------
행 단위 upsert는 app/services/ingestion.py가 담당한다. 이 라우터는 배치 오케스트레이션
(integration.sync_job 생성/집계, 행별 SAVEPOINT 격리, integration.sync_row_error 기록)만
책임진다 - 설계문서 8.1절 "잘못된 행은 전체 배치를 중단하지 않고 오류 격리 목록으로
보낸다"를 SQLAlchemy SAVEPOINT(begin_nested)로 구현한다: 한 행이 예외를 던지면 그 행의
변경만 롤백되고 나머지 행들의 이미 커밋 대기 중인 변경은 그대로 세션에 남는다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedPrincipal, _fail, require_roles
from app.db.session import get_db
from app.models.integration import SyncJob, SyncRowError
from app.schemas.imports import (
    ExcelImportResponse,
    ExcelImportSheetSummary,
    ExcelMatchExportRequest,
    ExhibitorImportRequest,
    ExhibitorImportRow,
    ImportBatchResult,
    ImportErrorListResponse,
    ImportRowError,
    ImportStatusResponse,
    ProductImportRequest,
    ProductImportRow,
    VisitorImportRequest,
    VisitorImportRow,
)
from app.services.batch_matching_export import (
    XLSX_MEDIA_TYPE,
    BatchMatchingExportError,
    render_batch_matching_workbook,
    run_batch_matching,
)
from app.services.excel_import import (
    EXCEL_IMPORT_SCHEMA_VERSION,
    ExcelImportValidationError,
    ParsedSheet,
    parse_excel_import,
)
from app.services.ingestion import (
    IngestionError,
    get_or_create_source_system,
    upsert_exhibitor,
    upsert_product,
    upsert_visitor,
)

logger = logging.getLogger(__name__)

router = APIRouter()
require_import_admin = require_roles("EVENT_ADMIN", fresh_mfa=True)
ImportAdmin = Annotated[VerifiedPrincipal, Depends(require_import_admin)]
Database = Annotated[AsyncSession, Depends(get_db)]


def _require_import_scope(
    http_request: Request,
    principal: VerifiedPrincipal,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> None:
    if not principal.has_role("EVENT_ADMIN", tenant_id=tenant_id, event_id=event_id):
        raise _fail(
            http_request,
            403,
            "SCOPE_FORBIDDEN",
            "해당 행사의 import 권한이 없습니다.",
        )


async def _run_batch(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    source_system_code: str,
    job_type: str,
    rows: Sequence[VisitorImportRow | ExhibitorImportRow | ProductImportRow],
    upsert_one,
    error_row_numbers: Sequence[int] | None = None,
    include_source_record_id_in_errors: bool = True,
) -> ImportBatchResult:
    source_system = await get_or_create_source_system(
        db, tenant_id=tenant_id, system_code=source_system_code
    )

    job = SyncJob(
        tenant_id=tenant_id,
        event_id=event_id,
        source_system_id=source_system.source_system_id,
        job_type=job_type,
        status="RUNNING",
        total_rows=len(rows),
    )
    job.started_at = datetime.now(UTC)
    db.add(job)
    await db.flush()

    errors: list[ImportRowError] = []
    success_rows = 0

    for row_index, row in enumerate(rows):
        reported_row_index = (
            error_row_numbers[row_index] if error_row_numbers is not None else row_index
        )
        try:
            async with db.begin_nested():
                await upsert_one(
                    db,
                    tenant_id=tenant_id,
                    event_id=event_id,
                    source_system_id=source_system.source_system_id,
                    row=row,
                )
        except IngestionError as exc:
            errors.append(
                ImportRowError(
                    row_index=reported_row_index,
                    source_record_id=(
                        row.source_record_id
                        if include_source_record_id_in_errors
                        else None
                    ),
                    error_code=exc.code,
                    message=exc.message,
                )
            )
            db.add(
                SyncRowError(
                    sync_job_id=job.sync_job_id,
                    row_number=reported_row_index,
                    external_id=row.source_record_id,
                    error_code=exc.code,
                    error_message=exc.message,
                    raw_row_json=row.model_dump(mode="json"),
                )
            )
        except (
            Exception
        ):  # Unexpected row failures are isolated from the rest of the batch.
            logger.exception(
                "import row failed unexpectedly: job=%s row=%s",
                job.sync_job_id,
                row_index,
            )
            errors.append(
                ImportRowError(
                    row_index=reported_row_index,
                    source_record_id=(
                        row.source_record_id
                        if include_source_record_id_in_errors
                        else None
                    ),
                    error_code="INTERNAL_ERROR",
                    message="행 처리 중 알 수 없는 오류가 발생했습니다.",
                )
            )
            db.add(
                SyncRowError(
                    sync_job_id=job.sync_job_id,
                    row_number=reported_row_index,
                    external_id=row.source_record_id,
                    error_code="INTERNAL_ERROR",
                    error_message="행 처리 중 알 수 없는 오류가 발생했습니다.",
                    raw_row_json=row.model_dump(mode="json"),
                )
            )
        else:
            success_rows += 1

    failed_rows = len(errors)
    if failed_rows == 0:
        job.status = "COMPLETED"
    elif success_rows == 0:
        job.status = "FAILED"
    else:
        job.status = "COMPLETED_WITH_ERRORS"
    job.success_rows = success_rows
    job.failed_rows = failed_rows
    job.completed_at = datetime.now(UTC)

    await db.commit()

    return ImportBatchResult(
        import_id=job.sync_job_id,
        status=job.status,  # type: ignore[arg-type]
        total_rows=job.total_rows,
        success_rows=success_rows,
        failed_rows=failed_rows,
        errors=errors,
    )


@router.post("/admin/imports/visitors", response_model=ImportBatchResult)
async def import_visitors(
    payload: VisitorImportRequest,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
) -> ImportBatchResult:
    """방문객(관람객) 사전등록 배치 upsert. 설계문서 8.3절, 인터페이스 명세 18.1절."""

    _require_import_scope(
        http_request, principal, tenant_id=payload.tenant_id, event_id=payload.event_id
    )
    return await _run_batch(
        db,
        tenant_id=payload.tenant_id,
        event_id=payload.event_id,
        source_system_code=payload.source_system_code,
        job_type="VISITOR_IMPORT",
        rows=payload.rows,
        upsert_one=upsert_visitor,
    )


@router.post("/admin/imports/exhibitors", response_model=ImportBatchResult)
async def import_exhibitors(
    payload: ExhibitorImportRequest,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
) -> ImportBatchResult:
    """참가업체 신청 배치 upsert."""

    _require_import_scope(
        http_request, principal, tenant_id=payload.tenant_id, event_id=payload.event_id
    )
    return await _run_batch(
        db,
        tenant_id=payload.tenant_id,
        event_id=payload.event_id,
        source_system_code=payload.source_system_code,
        job_type="EXHIBITOR_IMPORT",
        rows=payload.rows,
        upsert_one=upsert_exhibitor,
    )


def _excel_sheet_summary(sheet: ParsedSheet) -> ExcelImportSheetSummary:
    return ExcelImportSheetSummary(
        sheet_name=sheet.sheet_name,
        total_rows=sheet.total_rows,
        valid_rows=len(sheet.rows),
        failed_rows=len(sheet.errors),
        errors=list(sheet.errors),
    )


@router.post("/admin/imports/excel", response_model=ExcelImportResponse)
async def import_excel(
    http_request: Request,
    principal: ImportAdmin,
    tenant_id: UUID,
    event_id: UUID,
    db: Database,
    source_system_code: str = Query(default="EXCEL_UPLOAD", max_length=50),
    dry_run: bool = Query(default=True),
    workbook_bytes: bytes = Body(
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    content_type: str | None = Header(default=None, alias="Content-Type"),
) -> ExcelImportResponse:
    """Validate or import the published visitor/exhibitor XLSX workbook.

    ``dry_run=true`` performs no write. Valid rows use the existing canonical JSON import and
    ingestion path; the XLSX adapter does not bypass approval or matching eligibility policies.
    """

    _require_import_scope(
        http_request, principal, tenant_id=tenant_id, event_id=event_id
    )
    expected_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if content_type is None or content_type.split(";", 1)[0].strip() != expected_type:
        raise HTTPException(status_code=415, detail="EXCEL_CONTENT_TYPE_UNSUPPORTED")
    try:
        parsed = parse_excel_import(workbook_bytes)
    except ExcelImportValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from None

    visitor_summary = _excel_sheet_summary(parsed.visitors)
    exhibitor_summary = _excel_sheet_summary(parsed.exhibitors)
    valid_count = visitor_summary.valid_rows + exhibitor_summary.valid_rows
    parse_error_count = visitor_summary.failed_rows + exhibitor_summary.failed_rows

    if valid_count == 0:
        return ExcelImportResponse(
            schema_version=EXCEL_IMPORT_SCHEMA_VERSION,
            status="INVALID",
            dry_run=dry_run,
            visitors=visitor_summary,
            exhibitors=exhibitor_summary,
        )
    if dry_run:
        return ExcelImportResponse(
            schema_version=EXCEL_IMPORT_SCHEMA_VERSION,
            status="VALID_WITH_ERRORS" if parse_error_count else "VALID",
            dry_run=True,
            visitors=visitor_summary,
            exhibitors=exhibitor_summary,
        )

    visitor_import = None
    if parsed.visitors.rows:
        visitor_import = await _run_batch(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            source_system_code=source_system_code,
            job_type="VISITOR_IMPORT",
            rows=parsed.visitors.rows,
            upsert_one=upsert_visitor,
            error_row_numbers=parsed.visitors.row_numbers,
            include_source_record_id_in_errors=False,
        )
    exhibitor_import = None
    if parsed.exhibitors.rows:
        exhibitor_import = await _run_batch(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            source_system_code=source_system_code,
            job_type="EXHIBITOR_IMPORT",
            rows=parsed.exhibitors.rows,
            upsert_one=upsert_exhibitor,
            error_row_numbers=parsed.exhibitors.row_numbers,
            include_source_record_id_in_errors=False,
        )
    import_failed = any(
        result is not None and result.failed_rows > 0
        for result in (visitor_import, exhibitor_import)
    )
    return ExcelImportResponse(
        schema_version=EXCEL_IMPORT_SCHEMA_VERSION,
        status=(
            "IMPORTED_WITH_ERRORS" if parse_error_count or import_failed else "IMPORTED"
        ),
        dry_run=False,
        visitors=visitor_summary,
        exhibitors=exhibitor_summary,
        visitor_import=visitor_import,
        exhibitor_import=exhibitor_import,
    )


@router.post(
    "/admin/imports/excel/matches",
    response_class=Response,
    responses={
        200: {
            "content": {XLSX_MEDIA_TYPE: {}},
            "description": "사전등록자별 Top-N 참여기업 매칭 XLSX",
        }
    },
)
async def export_excel_matches(
    payload: ExcelMatchExportRequest,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
) -> Response:
    """Export canonical recommendations for selected imported preregistrants.

    The operation does not match raw workbook rows. Every source ID must resolve to a canonical
    profile, and each result goes through consent, approved catalog, Hard Filter, common scoring,
    explanation, and persistence policies.
    """

    _require_import_scope(
        http_request, principal, tenant_id=payload.tenant_id, event_id=payload.event_id
    )
    try:
        report = await run_batch_matching(
            db,
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            source_system_code=payload.source_system_code,
            source_record_ids=payload.source_record_ids,
            top_n=payload.top_n,
        )
    except BatchMatchingExportError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from None

    return Response(
        content=render_batch_matching_workbook(report),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                'attachment; filename="meet-ai-batch-matches.xlsx"'
            ),
            "X-Workbook-Schema": report.schema_version,
        },
    )


@router.post("/admin/imports/products", response_model=ImportBatchResult)
async def import_products(
    payload: ProductImportRequest,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
) -> ImportBatchResult:
    """제품 배치 upsert. 부모 업체는 먼저 import_exhibitors로 연계되어 있어야 한다."""

    _require_import_scope(
        http_request, principal, tenant_id=payload.tenant_id, event_id=payload.event_id
    )
    return await _run_batch(
        db,
        tenant_id=payload.tenant_id,
        event_id=payload.event_id,
        source_system_code=payload.source_system_code,
        job_type="PRODUCT_IMPORT",
        rows=payload.rows,
        upsert_one=upsert_product,
    )


@router.get("/admin/imports/{import_id}", response_model=ImportStatusResponse)
async def get_import_status(
    import_id: UUID,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
) -> ImportStatusResponse:
    job = await db.get(SyncJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="IMPORT_NOT_FOUND")
    _require_import_scope(
        http_request, principal, tenant_id=job.tenant_id, event_id=job.event_id
    )
    return ImportStatusResponse(
        import_id=job.sync_job_id,
        job_type=job.job_type,
        status=job.status,
        total_rows=job.total_rows,
        success_rows=job.success_rows,
        failed_rows=job.failed_rows,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/admin/imports/{import_id}/errors", response_model=ImportErrorListResponse)
async def get_import_errors(
    import_id: UUID,
    http_request: Request,
    principal: ImportAdmin,
    db: Database,
    cursor: str | None = Query(default=None, description="이전 응답의 next_cursor 값"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ImportErrorListResponse:
    """인터페이스 명세 4.1절 "불투명 Cursor Pagination"을 만족하는 최소 구현.

    TODO: 지금은 offset을 base64 없이 그대로 문자열로 노출하는 단순 구현이다(진짜 "불투명"
    커서는 아니다). 다른 목록 API들의 커서 구현이 정해지면 그 방식으로 통일해야 한다.
    """

    job = await db.get(SyncJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="IMPORT_NOT_FOUND")
    _require_import_scope(
        http_request, principal, tenant_id=job.tenant_id, event_id=job.event_id
    )

    offset = 0
    if cursor:
        try:
            offset = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="INVALID_CURSOR") from None

    stmt = (
        select(SyncRowError)
        .where(SyncRowError.sync_job_id == import_id)
        .order_by(SyncRowError.row_number)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        ImportRowError(
            row_index=row.row_number,
            source_record_id=row.external_id,
            error_code=row.error_code,
            message=row.error_message,
        )
        for row in rows
    ]
    next_cursor = str(offset + limit) if has_more else None

    return ImportErrorListResponse(
        import_id=import_id, items=items, next_cursor=next_cursor
    )

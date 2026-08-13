"""원천 사이트(backju.kr) 실시간 웹훅 수신 라우터.

경로 근거
---------
docs/2026-backju-ai-matching-service-design.md 8.3절 "주요 API 경계": `POST /v1/webhooks/backju`.
인터페이스 명세(docs/frontend-backend-ai-interface-spec.md) 18.2절은 헤더 계약만 정의하고
구체 경로를 다시 쓰지 않으므로, 이 값은 문서 간 충돌이 아니라 설계문서 쪽이 유일한 근거다.
이 router는 자체 prefix가 없다 - app/api/v1/api.py(공용 aggregator, 이 작업 범위 밖)가 추가
prefix 없이 include해야 `<API_V1_PREFIX>/webhooks/backju`가 완성된다.

검증 순서 (설계문서 8.2절)
---------------------------
1. 원문 바이트(request.body())를 그대로 서명 검증에 쓴다 - JSON을 재직렬화해서 검증하면 키
   순서·공백 차이로 서명이 어긋난다.
2. 페이로드는 일단 파싱만 한다(스키마 검증). 이 시점의 tenant_id/source_system_code는 아직
   "신뢰"하지 않은 값이며, 오직 "이 요청을 검증할 때 어떤 연동처 비밀키를 대조해야 하는가"를
   알아내는 용도로만 쓴다 - 실제 업무 처리는 서명 검증을 통과한 뒤에만 수행한다.
3. X-Webhook-Signature(HMAC-SHA256, `v1=hex`)를 검증한다.
4. X-Webhook-Timestamp 허용범위를 검사한다(재전송 공격 방지).
5. X-Webhook-ID로 중복을 제거한다(integration.idempotency_record) - 원천이 202/5xx를 받고
   재전송한 동일 webhook_id는 재처리하지 않고 이전 결과를 그대로 반환한다.
6. app/services/ingestion.py의 upsert 함수로 실제 반영한다.

실패 시 재시도 유도
--------------------
설계문서 8.2절 "2xx만 성공으로 간주하고 지수 백오프 재시도·실패보관함을 운영한다"에 따라,
서명/타임스탬프 실패나 upsert 실패는 2xx가 아닌 상태코드로 응답해 원천이 재시도하도록 한다.
성공적으로 처리된 요청만 idempotency_record에 기록해, 실패한 시도는 재전송 시 다시 처리될
수 있게 남겨 둔다.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    compute_principal_fingerprint,
    derive_webhook_secret,
    verify_webhook_signature,
    verify_webhook_timestamp,
)
from app.db.session import get_db
from app.models.integration import IdempotencyRecord, SyncJob, SyncRowError
from app.schemas.imports import (
    ExhibitorImportRow,
    ProductImportRow,
    VisitorImportRow,
    WebhookAcceptedResponse,
    WebhookEnvelope,
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

_ROUTE = "/webhooks/backju"

#: event_type -> (row 스키마, upsert 함수).
_HANDLERS = {
    "VISITOR_UPSERTED": (VisitorImportRow, upsert_visitor),
    "EXHIBITOR_UPSERTED": (ExhibitorImportRow, upsert_exhibitor),
    "PRODUCT_UPSERTED": (ProductImportRow, upsert_product),
}


@router.post("/webhooks/backju", response_model=WebhookAcceptedResponse)
async def receive_backju_webhook(
    request: Request,
    x_webhook_id: str = Header(..., alias="X-Webhook-ID"),
    x_webhook_timestamp: str = Header(..., alias="X-Webhook-Timestamp"),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
) -> WebhookAcceptedResponse:
    raw_body = await request.body()

    try:
        body_dict = json.loads(raw_body)
        envelope = WebhookEnvelope.model_validate(body_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="WEBHOOK_PAYLOAD_INVALID") from exc

    secret = derive_webhook_secret(envelope.source_system_code)

    signature_result = verify_webhook_signature(raw_body, x_webhook_signature, secret=secret)
    if not signature_result.valid:
        logger.warning(
            "webhook signature rejected: source_system=%s reason=%s",
            envelope.source_system_code,
            signature_result.reason,
        )
        raise HTTPException(status_code=401, detail="WEBHOOK_SIGNATURE_INVALID")

    timestamp_result = verify_webhook_timestamp(x_webhook_timestamp)
    if not timestamp_result.valid:
        raise HTTPException(status_code=401, detail="WEBHOOK_TIMESTAMP_INVALID")

    handler = _HANDLERS.get(envelope.event_type)
    if handler is None:  # pragma: no cover - Literal이 이미 event_type을 제한한다
        raise HTTPException(status_code=400, detail="UNSUPPORTED_EVENT_TYPE")
    row_cls, upsert_fn = handler

    principal_fingerprint = compute_principal_fingerprint(envelope.source_system_code)
    dedupe_stmt = select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == envelope.tenant_id,
        IdempotencyRecord.principal_fingerprint == principal_fingerprint,
        IdempotencyRecord.method == "WEBHOOK",
        IdempotencyRecord.route == _ROUTE,
        IdempotencyRecord.idempotency_key == x_webhook_id,
    )
    existing_record = (await db.execute(dedupe_stmt)).scalar_one_or_none()
    if existing_record is not None:
        return WebhookAcceptedResponse(
            webhook_id=x_webhook_id,
            event_type=envelope.event_type,  # type: ignore[arg-type]
            duplicate=True,
            internal_id=existing_record.response_reference,
        )

    try:
        row = row_cls.model_validate(
            {
                **envelope.data,
                "source_record_id": envelope.source_record_id,
                "source_updated_at": envelope.changed_at,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="WEBHOOK_DATA_INVALID") from exc

    source_system = await get_or_create_source_system(
        db,
        tenant_id=envelope.tenant_id,
        system_code=envelope.source_system_code,
        sync_type="WEBHOOK",
    )

    job = SyncJob(
        tenant_id=envelope.tenant_id,
        event_id=envelope.event_id,
        source_system_id=source_system.source_system_id,
        job_type="WEBHOOK_INGEST",
        status="RUNNING",
        total_rows=1,
        started_at=datetime.now(UTC),
    )
    db.add(job)
    await db.flush()

    try:
        async with db.begin_nested():
            outcome = await upsert_fn(
                db,
                tenant_id=envelope.tenant_id,
                event_id=envelope.event_id,
                source_system_id=source_system.source_system_id,
                row=row,
            )
    except IngestionError as exc:
        job.status = "FAILED"
        job.failed_rows = 1
        job.completed_at = datetime.now(UTC)
        db.add(
            SyncRowError(
                sync_job_id=job.sync_job_id,
                row_number=0,
                external_id=envelope.source_record_id,
                error_code=exc.code,
                error_message=exc.message,
                raw_row_json=envelope.model_dump(mode="json"),
            )
        )
        await db.commit()
        # 실패는 2xx가 아닌 상태로 응답해 원천의 재시도를 유도한다 (설계문서 8.2절).
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception:
        logger.exception("webhook processing failed unexpectedly: webhook_id=%s", x_webhook_id)
        job.status = "FAILED"
        job.failed_rows = 1
        job.completed_at = datetime.now(UTC)
        db.add(
            SyncRowError(
                sync_job_id=job.sync_job_id,
                row_number=0,
                external_id=envelope.source_record_id,
                error_code="INTERNAL_ERROR",
                error_message="웹훅 처리 중 알 수 없는 오류가 발생했습니다.",
                raw_row_json=envelope.model_dump(mode="json"),
            )
        )
        await db.commit()
        raise HTTPException(status_code=500, detail="WEBHOOK_PROCESSING_FAILED") from None

    job.status = "COMPLETED"
    job.success_rows = 1
    job.completed_at = datetime.now(UTC)

    db.add(
        IdempotencyRecord(
            tenant_id=envelope.tenant_id,
            principal_fingerprint=principal_fingerprint,
            method="WEBHOOK",
            route=_ROUTE,
            idempotency_key=x_webhook_id,
            response_status=200,
            response_reference=outcome.internal_id,
        )
    )

    await db.commit()

    return WebhookAcceptedResponse(
        webhook_id=x_webhook_id,
        event_type=envelope.event_type,  # type: ignore[arg-type]
        duplicate=False,
        internal_id=outcome.internal_id,
    )

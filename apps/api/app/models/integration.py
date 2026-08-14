"""integration 도메인 SQLAlchemy 모델 - 원천연계, 배치 import, 웹훅 멱등성.

근거 문서와 우선순위
---------------------
- docs/db-erd-table-spec.md 19절(연계·멱등성·Outbox) - 이 파일 전체의 1차 근거.
  19.1 source_system, 19.2 external_reference, 19.3 sync_job·sync_row_error,
  19.4 idempotency_record를 그대로 구현한다.
- docs/2026-backju-ai-matching-service-design.md 8절(연동 계약) - "import는 source_record_id와
  source_updated_at으로 멱등 upsert한다", "잘못된 행은 전체 배치를 중단하지 않고 오류 격리
  목록으로 보낸다", "웹훅에는 ... HMAC 서명, 타임스탬프 허용범위, 재전송 방지 ID를 적용한다"는
  요구를 만족하는 저장소가 이 파일이다.
- docs/frontend-backend-ai-interface-spec.md 18절(원천 데이터 연계) - "파일 전체 checksum,
  행별 원천 ID, 원천 수정시각을 기록한다", "webhook_id로 중복을 제거한다".

이 파일을 새로 만든 이유
-------------------------
app/db/base.py는 이미 SCHEMA_INTEGRATION = "integration" 상수를 "원천연계, import, 멱등성,
outbox" 용도로 선언해 두었지만, 이 스키마의 실제 테이블을 정의하는 모델 파일은 아직 없었다.
imports/webhooks 라우터가 "source_record_id 기준 멱등 upsert"와 "실패 행 오류 격리"를 실제로
동작하게 하려면 (원천 ID → 내부 ID) 매핑과 배치·오류 이력을 저장할 테이블이 반드시 있어야
하므로, 이번 작업(외부 데이터 수신 API) 범위의 일부로 이 모델을 함께 만든다.

app/models/__init__.py(공용 aggregator, 여러 에이전트가 동시에 자신의 도메인 모듈을 등록하는
파일)는 이 작업 지시가 명시적으로 건드리지 말라고 한 파일 목록에는 없지만, api.py/main.py와
같은 성격의 공용 파일이라 판단해 일부러 수정하지 않았다. Alembic autogenerate가 이 모듈을
인식하게 하려면 통합 단계에서 `from app.models import integration`을 __init__.py에 추가해야
한다 (TODO: 통합 담당 에이전트).

outbox_event(db-erd 19.5)는 이번 작업의 세 라우터(imports/webhooks/partner) 중 어느 것도
직접 필요로 하지 않아 이번 범위에서 만들지 않는다 - 이벤트 발행이 필요해지는 후속 단계에서
추가한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_CORE,
    SCHEMA_EXHIBITION,
    SCHEMA_IDENTITY,
    SCHEMA_INTEGRATION,
    SCHEMA_MATCHING,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: 08 문서의 세 배치 import 대상 + 웹훅 실시간 반영을 아우르는 작업 유형.
#: WEBHOOK_INGEST는 db-erd 19.3절에는 없지만, 웹훅 처리도 동일한 "행 단위 결과 기록" 구조가
#: 필요해 sync_job/sync_row_error를 재사용하기 위해 추가했다 (TODO: 6~30단계 중 웹훅 운영
#: 대시보드 상세설계에서 값 목록 재검토).
SYNC_JOB_TYPES: tuple[str, ...] = (
    "VISITOR_IMPORT",
    "EXHIBITOR_IMPORT",
    "PRODUCT_IMPORT",
    "WEBHOOK_INGEST",
)

SYNC_JOB_STATUSES: tuple[str, ...] = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "COMPLETED_WITH_ERRORS",
    "FAILED",
)

#: 19.2절 "USER, EXHIBITOR 등" 예시를 이 프로젝트의 실제 import 대상 세 가지로 구체화했다.
EXTERNAL_REFERENCE_OBJECT_TYPES: tuple[str, ...] = ("VISITOR", "EXHIBITOR", "PRODUCT")

EXTERNAL_REFERENCE_SYNC_STATUSES: tuple[str, ...] = ("SYNCED", "FAILED", "CONFLICT")

SYNC_ROW_ERROR_RETRY_STATUSES: tuple[str, ...] = ("PENDING", "RETRIED", "IGNORED")

NOTIFICATION_TYPES: tuple[str, ...] = (
    "REGISTRATION_COMPLETED",
    "RECOMMENDATION_READY",
    "EVENT_EVE_REMINDER",
    "MEETING_STATUS_CHANGED",
    "MEETING_IMMINENT",
    "POST_EVENT_SUMMARY",
)
NOTIFICATION_CHANNELS: tuple[str, ...] = ("KAKAO_ALIMTALK", "SMS", "EMAIL")
NOTIFICATION_STATUSES: tuple[str, ...] = (
    "QUEUED",
    "PROCESSING",
    "SENT",
    "DELIVERED",
    "FAILED",
)
NOTIFICATION_ATTEMPT_STATUSES: tuple[str, ...] = (
    "SENT",
    "DELIVERED",
    "FAILED",
    "SKIPPED",
)
OUTBOX_STATUSES: tuple[str, ...] = ("PENDING", "PROCESSING", "PUBLISHED", "FAILED")


class SourceSystem(Base):
    """integration.source_system - db-erd 19.1.

    "tenant, system_code, 이름, sync_type, active를 저장한다"를 그대로 구현한다. 웹훅 서명
    검증에 쓰는 실제 비밀키는 이 테이블에 평문으로 두지 않는다 - app/core/security.py가
    SECRET_KEY와 system_code로부터 결정적으로 파생시키는 방식을 MVP 임시 대안으로 쓴다
    (그 모듈의 TODO 참고, 설계문서 21절이 요구하는 KMS 연동은 후속 작업).
    """

    __tablename__ = "source_system"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "system_code", name="uq_source_system_tenant_code"
        ),
        CheckConstraint(
            "sync_type IN ('CSV', 'API', 'WEBHOOK')", name="sync_type_allowed"
        ),
        {"schema": SCHEMA_INTEGRATION},
    )

    source_system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    system_code: Mapped[str] = mapped_column(String(50), nullable=False)
    system_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    external_references: Mapped[list[ExternalReference]] = relationship(
        back_populates="source_system", cascade="all, delete-orphan"
    )


class ExternalReference(Base):
    """integration.external_reference - db-erd 19.2.

    (source_system_id, object_type, external_id) -> internal_id 매핑. 설계문서 8.1절
    "source_record_id와 source_updated_at으로 멱등 upsert한다"의 핵심 근거 테이블이다:
    같은 external_id(=source_record_id)가 다시 들어오면 이 테이블에서 internal_id를 찾아
    UPDATE하고, source_updated_at보다 오래된 재전송은 무시한다.
    """

    __tablename__ = "external_reference"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id",
            "object_type",
            "external_id",
            name="uq_external_reference_source_object",
        ),
        CheckConstraint(
            f"object_type IN ({_in_list(EXTERNAL_REFERENCE_OBJECT_TYPES)})",
            name="object_type_allowed",
        ),
        CheckConstraint(
            f"sync_status IN ({_in_list(EXTERNAL_REFERENCE_SYNC_STATUSES)})",
            name="sync_status_allowed",
        ),
        Index("ix_external_reference_internal_id", "object_type", "internal_id"),
        {"schema": SCHEMA_INTEGRATION},
    )

    external_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTEGRATION}.source_system.source_system_id"),
        nullable=False,
    )
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 원천(backju.kr) 쪽 레코드 ID. 설계문서 8.1절의 source_record_id에 해당한다.
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # 대상 테이블이 object_type마다 달라 단일 FK를 걸지 않는다 (exhibition.exhibitor.py의
    # SupplyProfileAttribute.object_id와 동일한 다형 참조 패턴).
    internal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_payload_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SYNCED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_system: Mapped[SourceSystem] = relationship(
        back_populates="external_references"
    )


class SyncJob(Base):
    """integration.sync_job - db-erd 19.3.

    "작업 유형, 대상, checksum, 시작·종료, 전체·성공·실패 수, 상태를 저장한다"를 구현한다.
    인터페이스 명세 18.1절의 GET /admin/imports/{import_id} 응답 원천이며, import_id는 이
    테이블의 sync_job_id를 그대로 노출한다.
    """

    __tablename__ = "sync_job"
    __table_args__ = (
        CheckConstraint(
            f"job_type IN ({_in_list(SYNC_JOB_TYPES)})", name="job_type_allowed"
        ),
        CheckConstraint(
            f"status IN ({_in_list(SYNC_JOB_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint("total_rows >= 0", name="total_rows_nonneg"),
        CheckConstraint("success_rows >= 0", name="success_rows_nonneg"),
        CheckConstraint("failed_rows >= 0", name="failed_rows_nonneg"),
        {"schema": SCHEMA_INTEGRATION},
    )

    sync_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTEGRATION}.source_system.source_system_id"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 인터페이스 명세 18.1절 "파일 전체 checksum". API/웹훅 연동은 원본 파일이 없을 수 있어
    # nullable로 둔다.
    file_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 요청한 운영자/서비스 주체. profile.user_account가 없는 서비스 간 호출(webhook)도 있어
    # FK를 걸지 않는다 (db-erd 6.2절 created_by/updated_by와 동일 패턴).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    row_errors: Mapped[list[SyncRowError]] = relationship(
        back_populates="sync_job", cascade="all, delete-orphan"
    )


class SyncRowError(Base):
    """integration.sync_row_error - db-erd 19.3.

    "행 번호, 외부 ID, 오류코드, 안전하게 마스킹된 메시지, 재처리 상태를 저장한다"를 구현한다.
    error_message는 예외 원문이 아니라 애플리케이션이 만든 안전한 메시지여야 한다 - 인터페이스
    명세 4.4절 "외부 응답에는 DB 키, 프롬프트, 공급자 오류 원문, 개인정보를 노출하지 않는다"를
    이 컬럼에도 그대로 적용한다 (라우터 계층에서 원문 예외를 그대로 넣지 않도록 책임진다).
    """

    __tablename__ = "sync_row_error"
    __table_args__ = (
        CheckConstraint("row_number >= 0", name="row_number_nonneg"),
        CheckConstraint(
            f"retry_status IN ({_in_list(SYNC_ROW_ERROR_RETRY_STATUSES)})",
            name="retry_status_allowed",
        ),
        Index("ix_sync_row_error_job", "sync_job_id"),
        {"schema": SCHEMA_INTEGRATION},
    )

    sync_row_error_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    sync_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTEGRATION}.sync_job.sync_job_id"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    # 재처리를 위해 원본 행 자체를 보관한다 (설계문서 8.1절 "원본 파일, import 실행, 행별
    # 결과를 보관한다"). 개인정보가 섞일 수 있으므로 보유기간·접근통제는 운영 정책을 따른다
    # (privacy.retention_policy 연동은 이 파일 범위 밖 - TODO: 통합 단계).
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sync_job: Mapped[SyncJob] = relationship(back_populates="row_errors")


class IdempotencyRecord(Base):
    """integration.idempotency_record - db-erd 19.4.

    범용 멱등성 저장소. 이 작업 범위에서는 webhooks 라우터가 X-Webhook-ID 중복 수신을 막는
    데 사용한다 (method="WEBHOOK", route="/webhooks/backju", idempotency_key=webhook_id).
    인터페이스 명세 4.2절이 설명하는 일반 Idempotency-Key 헤더 처리(모든 POST 공통)는 별도
    미들웨어 담당 에이전트의 책임 범위이며, 이 테이블 자체는 그 미들웨어도 재사용할 수 있는
    구조로 db-erd 19.4절 컬럼을 그대로 따랐다.
    """

    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "principal_fingerprint",
            "method",
            "route",
            "idempotency_key",
            name="uq_idempotency_record_scope",
        ),
        {"schema": SCHEMA_INTEGRATION},
    )

    idempotency_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    # 인증 주체 또는 발신 시스템의 HMAC 지문. 웹훅은 source_system_id를 HMAC한 값을 쓴다.
    principal_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_reference: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationDelivery(Base):
    """One informational notification linked to a web access link.

    Contact values and the raw personal token are deliberately absent. The only secret persisted
    here is the complete access URL encrypted with authenticated encryption; dispatch workers read
    the separately encrypted identity contact only while preparing a provider request.
    """

    __tablename__ = "notification_delivery"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_notification_delivery_event_boundary",
        ),
        UniqueConstraint(
            "tenant_id", "dedupe_key", name="uq_notification_delivery_dedupe"
        ),
        CheckConstraint(
            f"notification_type IN ({_in_list(NOTIFICATION_TYPES)})",
            name="notification_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(NOTIFICATION_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint(
            "message_class = 'INFORMATIONAL'", name="message_class_informational"
        ),
        Index(
            "ix_notification_delivery_dispatch",
            "status",
            "queued_at",
        ),
        Index(
            "ix_notification_delivery_user_event",
            "user_id",
            "event_id",
            "queued_at",
        ),
        {"schema": SCHEMA_INTEGRATION},
    )

    notification_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    recommendation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id"
        ),
        nullable=True,
    )
    personal_access_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_IDENTITY}.personal_access_link.personal_access_link_id"),
        nullable=False,
        unique=True,
    )
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INFORMATIONAL"
    )
    template_code: Mapped[str] = mapped_column(String(100), nullable=False)
    template_parameters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    access_url_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationAttempt(Base):
    """Append-only result of one channel in the Alimtalk → SMS → email chain."""

    __tablename__ = "notification_attempt"
    __table_args__ = (
        UniqueConstraint(
            "notification_delivery_id",
            "sequence",
            name="uq_notification_attempt_sequence",
        ),
        CheckConstraint(
            f"channel IN ({_in_list(NOTIFICATION_CHANNELS)})",
            name="channel_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(NOTIFICATION_ATTEMPT_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        Index(
            "ix_notification_attempt_delivery",
            "notification_delivery_id",
            "sequence",
        ),
        {"schema": SCHEMA_INTEGRATION},
    )

    notification_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    notification_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_INTEGRATION}.notification_delivery.notification_delivery_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    """Privacy-minimized transactional Outbox event claimed with SKIP LOCKED."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_outbox_event_event_boundary",
        ),
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_outbox_event_dedupe"),
        CheckConstraint(
            f"status IN ({_in_list(OUTBOX_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        Index("ix_outbox_event_claim", "status", "next_attempt_at", "created_at"),
        {"schema": SCHEMA_INTEGRATION},
    )

    outbox_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(60), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

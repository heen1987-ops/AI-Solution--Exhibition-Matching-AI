"""document 도메인 SQLAlchemy 모델 - 참가업체 문서 업로드/버전/처리작업/접근감사.

이 파일을 새로 만든 이유
-------------------------
docs/db-erd-table-spec.md에는 "문서(source document)" 절이 없다 (19절 integration은 배치
import/웹훅만 다루고, ai 스키마는 모델 실행·추출속성·임베딩만 다룬다 - app/models/ai.py 참고).
이 기능(참가업체 서류 업로드, AI 구조화 파이프라인의 입력이 될 원본 문서 저장)은 병렬개발
하네스의 외부(Codex) 프롬프트가 WAVE 2D BACKEND-DOCUMENT 트랙으로 지시한 신규 도메인이며,
.harness/assumptions.md ASSUMPTION-003이 이런 외부 프롬프트를 기존 평면 레이아웃
(app/models/<domain>.py)에 도메인명 기준으로 매핑하도록 정한 규칙을 그대로 따른다.

스키마 선택
-----------
기존 12개 스키마 중 어느 것도 "이 파일이 소유해야 할" 문서 원본·버전·처리작업 테이블에
정확히 맞지 않는다:
- exhibition 스키마는 업체 마스터·제품·부스 등 "정본 비즈니스 레코드"를 담는다
  (AGENTS.md 불변식 2: "정본 비즈니스 레코드는 사용자/AI/리뷰 오버레이와 분리해 둔다").
  문서는 그 정본 데이터를 만들어내는 원재료(raw evidence)이지 정본 레코드 자체가 아니다.
- ai 스키마(model_version, ai_run)는 "실행 결과"를 담지 "입력 원본 파일"을 담지 않는다.
- integration 스키마(source_system, sync_job)는 외부 시스템과의 배치/웹훅 연동이 목적이라
  사람이 직접 올리는 파일 업로드와 관심사가 다르다.
그래서 app/db/base.py에 SCHEMA_DOCUMENT="document"를 새로 추가했다(SCHEMA_KIOSK가 그랬던
것과 같은 추가적 방식 - 기존 상수는 건드리지 않았다).

핵심 설계 결정과 근거
----------------------
1. **원본 문서(SourceDocument)와 버전(DocumentFile)을 분리한다.** AGENTS.md 불변식 3
   ("불변 게시 아티팩트를 버전화한다; 이력을 다시 쓰지 않고 새 버전을 만든다")을 문서 도메인에
   적용한 것이다. 같은 논리적 문서(예: "2026 카탈로그")를 다시 업로드하면 새 DocumentFile
   버전이 생기고, 이전 버전은 지워지지 않는다.
2. **published_file_id로 "게시된 콘텐츠가 참조 중"인 버전을 추적한다.** 작업 지시의 삭제
   정책("이미 게시된 콘텐츠가 참조하는 문서는 그냥 삭제할 수 없다 - 새 버전을 만들거나 먼저
   게시를 취소해야 한다")을 구현하는 핵심 컬럼이다. 이 필드를 실제로 채우는 주체(운영자 승인
   워크플로 - AGENTS.md "AI-추출 콘텐츠는 자동 게시되지 않는다, 참가업체 확인과 운영자 승인이
   모두 필요하다")는 이 작업 범위 밖이므로, document 서비스 계층은 이 컬럼을 세팅/해제하는
   내부 함수(mark_file_published/unpublish_document)만 제공하고 실제 승인 UI/로직과의 연결은
   TODO로 남긴다.
3. **document_access_log는 감사 대상 문서에 대한 FK를 걸지 않는다.** 업로드/다운로드/삭제
   감사 로그는 문서가 하드 삭제된 뒤에도 "누가 언제 무엇을 했는지" 증거로 남아야 하므로, FK로
   문서 행에 묶이면 문서 삭제 시 CASCADE로 로그까지 사라지거나(감사 목적에 반함) RESTRICT로
   삭제 자체가 막히는(작업 지시의 "미게시 문서는 하드삭제 가능" 요건에 반함) 딜레마가 생긴다.
   integration.sync_row_error가 원본 행 스냅샷을 그대로 보관하는 것과 같은 이유로, 여기서도
   FK 없이 UUID 값만 저장한다(무결성은 애플리케이션이 보장).
4. **storage_key는 내부 전용이며 이 모델 밖으로 절대 직렬화하지 않는다.** app/schemas/document.py
   의 어떤 응답 모델도 storage_key 컬럼을 필드로 갖지 않는다 - 작업 지시 "raw storage path나
   서명되지 않은 URL을 절대 반환하지 않는다"의 DB측 안전장치는 "그 컬럼을 읽는 코드가 API
   응답 조립에 쓰이지 않는다"는 코드 리뷰 규율에 의존하므로, 스키마 자체에서 컬럼 이름에
   `_internal` 접두는 붙이지 않았지만 이 docstring과 라우터 파일의 주석이 그 경계를 명시한다.

문서 상태 머신
---------------
SourceDocument.status: UPLOADED -> PROCESSING -> (PROCESSED | PROCESSING_FAILED). 여러 번
재처리될 수 있으므로 PROCESSED/PROCESSING_FAILED에서 다시 PROCESSING으로 돌아갈 수 있다.
파일이 하드 삭제되면 행 자체가 사라지므로 별도의 DELETED 상태값은 두지 않는다(문서 3번 결정
참고 - 감사 흔적은 document_access_log가 담당한다).

다른 도메인 모델과의 관계
--------------------------
meeting.py 모듈 docstring과 동일한 원칙을 따른다: 다른 스키마의 테이블은 "스키마명.테이블명.
컬럼명" 문자열 FK 경로만 사용하고 다른 모델 모듈을 import하지 않는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_CORE, SCHEMA_DOCUMENT, SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: 작업 지시가 명시한 허용 문서 형식과 1:1로 대응한다 (app/services/document/validation.py의
#: ALLOWED_DOCUMENT_EXTENSIONS가 단일 진실 공급원이며, 이 값들은 그 파일의 상수와 동기화되어야
#: 한다 - 확장자 자체가 아니라 "이 문서가 업무적으로 어떤 파일인가"를 나타내는 분류값).
DOCUMENT_TYPES: tuple[str, ...] = (
    "CATALOG",
    "CERTIFICATE",
    "PRICE_LIST",
    "COMPANY_PROFILE",
    "PRODUCT_SPEC",
    "OTHER",
)

DOCUMENT_STATUSES: tuple[str, ...] = (
    "UPLOADED",
    "PROCESSING",
    "PROCESSED",
    "PROCESSING_FAILED",
)

PROCESSING_JOB_STATUSES: tuple[str, ...] = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
)

#: 감사 로그 행동 코드. 작업 지시 "업로드/다운로드/삭제에 대한 감사 로그가 존재해야 한다"를
#: 만족하는 최소 집합 + 다운로드 토큰 발급 자체도 별도로 남겨 "토큰만 발급되고 실제 다운로드는
#: 안 된 경우"를 구분할 수 있게 한다.
DOCUMENT_ACCESS_ACTIONS: tuple[str, ...] = (
    "UPLOAD",
    "DOWNLOAD_TOKEN_ISSUED",
    "DOWNLOAD",
    "DELETE",
    "DELETE_BLOCKED",
    "PROCESS_REQUESTED",
)


class SourceDocument(Base):
    """document.source_document - 참가업체가 올린 논리적 문서(버전 묶음의 헤더).

    filename/mime_type/size_bytes/content_hash는 current_file_id가 가리키는 최신
    DocumentFile 값을 그대로 복제해 둔 캐시다(목록 조회에서 매번 조인하지 않기 위함 -
    exhibition.product_profile.category_code가 "표시용 코드 캐시"인 것과 같은 패턴,
    partner.py의 _resolve_concept_code 주석 참고). 정본은 항상 DocumentFile 쪽이다.
    """

    __tablename__ = "source_document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_source_document_tenant_event",
        ),
        CheckConstraint(
            f"document_type IN ({_in_list(DOCUMENT_TYPES)})", name="document_type_allowed"
        ),
        CheckConstraint(f"status IN ({_in_list(DOCUMENT_STATUSES)})", name="status_allowed"),
        CheckConstraint("size_bytes IS NULL OR size_bytes > 0", name="size_bytes_positive"),
        Index("ix_source_document_exhibitor", "exhibitor_id", "document_type"),
        # 중복탐지(content-hash 기반)는 같은 업체 소속 문서들 사이에서만 의미가 있다 -
        # 서로 다른 업체가 우연히 같은 파일을 올리는 것까지 막을 이유는 없다(공개된 표준
        # 서식 등). app/services/document/service.py의 duplicate 조회가 이 인덱스를 탄다.
        Index("ix_source_document_exhibitor_hash", "exhibitor_id", "content_hash"),
        {"schema": SCHEMA_DOCUMENT},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED")

    # 최신 버전 캐시 (모듈 docstring 참고). current_file_id는 첫 DocumentFile을 insert한
    # 뒤 채워지므로 nullable이다(문서 행 생성과 최초 파일 생성이 2단계 INSERT라서).
    current_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 게시된 콘텐츠가 참조 중인 버전. NULL이면 "아직 어떤 버전도 게시물의 근거로 쓰이지
    # 않았다" = 하드삭제 가능. 모듈 docstring 결정 2번 참고.
    published_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    files: Mapped[list[DocumentFile]] = relationship(
        "DocumentFile",
        back_populates="document",
        foreign_keys="DocumentFile.document_id",
        cascade="all, delete-orphan",
    )
    processing_jobs: Mapped[list[DocumentProcessingJob]] = relationship(
        "DocumentProcessingJob", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentFile(Base):
    """document.document_file - 한 논리 문서의 물리적 업로드 버전 하나.

    storage_key는 오브젝트 스토리지/로컬 파일시스템 어댑터가 실제 바이트를 찾는 내부
    참조값이다(app/services/document/storage.py의 ObjectStorageAdapter 키). 이 값은 어떤
    app/schemas/document.py 응답 모델에도 노출하지 않는다 - 작업 지시 "raw storage path나
    서명되지 않은 URL을 절대 반환하지 않는다".
    """

    __tablename__ = "document_file"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_file_document_version"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        Index("ix_document_file_content_hash", "content_hash"),
        {"schema": SCHEMA_DOCUMENT},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_DOCUMENT}.source_document.document_id"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # sha256 hex digest (64 hex chars) - 중복탐지 근거값.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 새 버전이 올라와 더 이상 "현재" 버전이 아니게 된 시각. NULL이면 아직 유효한 과거 버전
    # (게시 참조를 위해 남아있을 수 있음). 하드삭제된 버전은 행 자체가 사라진다.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[SourceDocument] = relationship(
        "SourceDocument", back_populates="files", foreign_keys=[document_id]
    )


class DocumentProcessingJob(Base):
    """document.document_processing_job - AI 구조화 파이프라인 처리 작업 상태.

    이 테이블은 작업 큐 자체가 아니라 "작업이 요청됐다"는 상태 기록이다. 실제 비동기 실행은
    apps/worker(BACKEND 트랙 net-new, 아직 없음 - AGENTS.md 참고)의 몫이며, 이 파일이 만든
    행은 PENDING 상태로 생성된 뒤 그대로 남는다(워커가 아직 없으므로) - 최종 보고서의
    known limitation 항목.
    """

    __tablename__ = "document_processing_job"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_list(PROCESSING_JOB_STATUSES)})", name="status_allowed"
        ),
        Index("ix_document_processing_job_document", "document_id", "status"),
        {"schema": SCHEMA_DOCUMENT},
    )

    processing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_DOCUMENT}.source_document.document_id"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_DOCUMENT}.document_file.file_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 안전한 오류코드만 저장한다(integration.sync_row_error.error_message와 동일한 원칙 -
    # 공급자/예외 원문을 그대로 넣지 않는다). 실제 값은 워커 담당 트랙의 몫이다.
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[SourceDocument] = relationship(
        "SourceDocument", back_populates="processing_jobs"
    )


class DocumentAccessLog(Base):
    """document.document_access_log - 업로드/다운로드/삭제 append-only 감사 로그.

    document_id/file_id에 의도적으로 FK를 걸지 않는다 - 모듈 docstring 결정 3번 참고
    (하드삭제된 문서에 대한 DELETE 로그 자체가 이 테이블의 존재 이유 중 하나이므로, FK가
    있으면 그 로그를 남길 수 없거나 삭제 자체가 막힌다).
    """

    __tablename__ = "document_access_log"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({_in_list(DOCUMENT_ACCESS_ACTIONS)})", name="action_allowed"
        ),
        Index("ix_document_access_log_document_created", "document_id", "created_at"),
        {"schema": SCHEMA_DOCUMENT},
    )

    access_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    # 안전한 부가정보만 (예: {"reason": "PUBLISHED_CONTENT_REFERENCE"}). 개인정보/원문 예외
    # 금지 - AGENTS.md 절대금지 "로그·픽스처·스냅샷에 개인정보를 쓰지 않는다".
    detail_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

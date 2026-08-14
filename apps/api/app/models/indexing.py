"""indexing 도메인 SQLAlchemy 모델 - 검색/추천에 노출되는 유일한 게이트 계층.

트랙: BACKEND-INDEXING (WAVE 2D). GOAL(작업 지시 원문): "the ONLY code path allowed to move
content from extraction_* tables into anything search/recommendation-visible, and ONLY when
review_status is fully APPROVED_BY_OPERATOR (never earlier)".

이 파일이 만드는 3개 테이블
----------------------------
1. ``indexing.search_document``   - exhibitor당 PUBLIC/VERIFIED_BUYER 두 계층으로 미리 만들어
   둔 검색 문서(예를 들어, exhibitor summary + public products + booth number...). 실제
   검색/추천 조회가 읽어야 할 유일한 표면이다 - exhibition.* 원본 테이블이나
   document.published_content_version을 검색 경로에서 직접 읽지 않는다(그 판단/필터링은
   전부 이 문서를 만드는 시점에 끝나 있어야 한다).
2. ``indexing.indexing_job``      - publish/approve/unpublish/visibility-change/document-delete
   이벤트가 들어올 때마다 만들어지는 재생성 작업 기록.
3. ``indexing.cache_invalidation_event`` - 위 작업이 끝날 때 어떤 캐시 영역(업체 상세/검색/
   추천/바이어매칭)이 무효화되어야 하는지 append-only로 남기는 로그.

왜 새 스키마인가 (``ai.object_embedding``과의 관계)
------------------------------------------------------
db-erd-table-spec.md 18.4절의 ``ai.object_embedding``(pgvector 컬럼, ``recommendable_id`` FK)은
"의미 벡터 검색" 테이블이며, **이미 완전히 구현되어 있다** - ``app/models/ai.py``의
``ObjectEmbedding``(VECTOR(512), 활성 SUMMARY 행만 대상으로 하는 부분 HNSW 코사인 인덱스,
모델 버전 FK와 검증 트리거), ``app/services/object_embeddings.py``(승인 카탈로그 문서 적재 →
스테이징 → 원자적 활성화 백필), ``app/services/matching/semantic_search.py``(질의 임베딩과
recall)이 그 구현이다. 이 문단의 이전 판은 "리포지토리 전체를 검색해도 구현한 코드는 없다"고
적고 있었으나 그것은 사실이 아니었다 - 그 문장을 근거로 ``ai.object_embedding``을 "중복"으로
간주해 삭제하면 동작 중인 pgvector 배포와 미승인 콘텐츠를 색인에서 배제하는 DB 트리거가 함께
사라진다.

두 테이블 계열은 중복이 아니라 상호 보완이다:

- ``ai.object_embedding``은 **recommendable 단위의 벡터 recall**을 담당한다(무엇이 의미적으로
  가까운가).
- 이 파일의 ``indexing.search_document``는 **exhibitor 단위의 PUBLIC/VERIFIED_BUYER 계층화된
  결정론적 문서**를 담당한다(누구에게 어떤 필드까지 보여도 되는가). 계층 판정은 벡터 유사도로
  대체할 수 없다.

따라서:

- 이 파일은 ``embedding_vectors``(pgvector 컬럼)를 만들지 않는다 - 벡터는
  ``ai.object_embedding``의 몫이고, 여기서 다시 들고 있을 이유가 없다.
- 대신 ``search_document.content_json``(구조화 JSON)과 ``search_document.search_text``(키워드/
  PostgreSQL FTS용 평문)만으로 "PUBLIC/VERIFIED_BUYER 두 계층 문서"라는 작업 지시의 핵심
  요구사항을 만족시킨다(``ai.object_embedding``이 ``recommendable_id``로 별도 조인되는 구조라
  ``search_document``와 독립적으로 확장 가능).
- 스키마 이름 자체를 ``ai``로 재사용하지 않고 새 ``indexing`` 스키마로 분리한 이유도 같다:
  ``ai`` 스키마는 이미 "AI 도메인 에이전트"(모델 실행, 임베딩)의 개념적 소유 구역으로 문서화돼
  있어(``app/models/exhibitor.py`` 모듈 docstring "pgvector 관련 메모" 참고), 여기서 새 테이블을
  얹으면 트랙 경계가 모호해진다. ``app/db/base.py``가 ``SCHEMA_DOCUMENT``에 대해 이미 쓴 것과
  똑같은 "추가적 신규 스키마" 관례를 그대로 따른다.

이 파일이 "유일한 게이트"라는 것의 실제 의미
------------------------------------------------
``exhibition.exhibitor``/``exhibition.product``/``exhibition.trade_condition`` 등 원본 승인
테이블이나 ``document.published_content_version``(운영자 승인 시점 불변 스냅샷 - 승인 전
어떤 값도 여기 들어오지 않는다, ``app/models/extraction.py`` 모듈 docstring 참고)에서 값을
가져와 ``search_document``를 채우는 코드는 오직 ``app/services/indexing/service.py``뿐이다.
그 서비스 계층의 게이트 규칙(승인 필터를 어디서 적용하는지)은 그 파일의 모듈 docstring에
있다. 이 모델 파일 자체는 게이트를 "강제"하지 않는다(그건 서비스 계층 책임) - 대신 "게이트를
통과한 결과만 담을 수 있는 얕은 스키마"를 제공한다: ``search_document``에는 계약서 상 이 GOAL이
명시적으로 금지한 필드(연락처, 비공개 가격, 내부 메모, 미승인 거래조건, 타 바이어 정보)를 담을
컬럼 자체가 없다 - ``content_json``은 자유 JSON이지만, 그 JSON을 만드는 유일한 함수
(``app/services/indexing/document_builder.py``의 ``build_public_document``/
``build_verified_buyer_document``)가 입력으로 받는 데이터클래스 자체에 그런 필드가 없다(2차
방어선, 그 파일 모듈 docstring 참고).

unpublish/delete 시 "검색에서 실제로 사라짐"을 어떻게 보장하는가
--------------------------------------------------------------------
``search_document.status``는 ``ACTIVE``/``REMOVED`` 2단계뿐이다. 검색/추천이 읽는 모든 조회
함수(``app/services/indexing/service.py``의 ``query_search_documents``)는 항상
``status = 'ACTIVE'``를 강제한다 - unpublish/delete는 행을 지우지 않고 ``REMOVED``로 표시만
하지만(감사 목적, ``indexing_job``/``cache_invalidation_event``와의 시간 순서 추적을 위해),
조회 경로에서는 존재하지 않는 것과 동일하게 취급된다. "행 하나가 (tenant_id, event_id,
exhibitor_id, tier)마다 최대 1개"(아래 UniqueConstraint)이므로 재승인 시 같은 행을 ``ACTIVE``로 되돌리는 것만으로
재게시가 끝난다(새 행을 또 만들지 않음).

버전 불변성(AGENTS.md 불변식 3)과의 관계 - 의도적 차이
----------------------------------------------------------
``document.published_content_version``은 "불변 게시 아티팩트"라 절대 덮어쓰지 않고 새 버전을
추가한다. 이 파일의 ``search_document``는 그 원칙을 그대로 적용하지 않는다 - 이 테이블은
원본이 아니라 파생된 캐시/색인이며, 원본이 바뀌면 그대로 다시 계산해 덮어써도 되는 "언제든
재생성 가능한 뷰"이기 때문이다(재생성 이력 자체가 필요하면 ``indexing_job`` 테이블이 그
append-only 기록을 담당한다 - ``search_document`` 자체를 버전화할 필요는 없다).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INDEXING, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: 작업 지시 GOAL의 "두 계층" 문서. VERIFIED_BUYER는 반드시 바이어 인증 여부를 서버측에서
#: 확인한 뒤에만 조회 결과에 포함되어야 한다(app/services/indexing/service.py의
#: ``allowed_tiers_for`` 참고 - 클라이언트가 보내는 값을 신뢰하지 않는다).
SEARCH_DOCUMENT_TIERS: tuple[str, ...] = ("PUBLIC", "VERIFIED_BUYER")

#: REMOVED는 unpublish/delete/재승인 실패 등으로 더 이상 검색에 노출되면 안 되는 상태.
#: 행을 지우지 않는 이유는 모듈 docstring 참고.
SEARCH_DOCUMENT_STATUSES: tuple[str, ...] = ("ACTIVE", "REMOVED")

#: 재색인을 유발하는 트리거. 작업 지시 "On approve/publish/unpublish/visibility-change/
#: document-delete: create an indexing job..."를 그대로 열거한다. MANUAL은 운영자가 수동으로
#: 재생성을 요청하는 경우(예: 콘텐츠 불일치 신고 후 강제 재계산).
INDEXING_JOB_TRIGGERS: tuple[str, ...] = (
    "APPROVE",
    "PUBLISH",
    "UNPUBLISH",
    "VISIBILITY_CHANGE",
    "DOCUMENT_DELETE",
    "MANUAL",
)

INDEXING_JOB_STATUSES: tuple[str, ...] = ("PENDING", "RUNNING", "COMPLETED", "FAILED")

#: 작업 지시 "invalidate the relevant caches (exhibitor detail, search, recommendation,
#: buyer-match)"를 그대로 열거한다.
#: SEMANTIC_INDEX는 ai.object_embedding(pgvector) 재색인 무효화를 가리킨다 - 승인/게시
#: 변경이 키워드 색인뿐 아니라 임베딩 색인도 무효화하기 때문이다.
CACHE_SCOPES: tuple[str, ...] = (
    "EXHIBITOR_DETAIL",
    "SEARCH",
    "RECOMMENDATION",
    "BUYER_MATCH",
    "SEMANTIC_INDEX",
)


class SearchDocument(Base):
    """indexing.search_document - (tenant, event, exhibitor, tier)당 최대 1행.

    tier는 PUBLIC|VERIFIED_BUYER. event_id는 NOT NULL이다 - 같은 업체가 여러 행사에
    참가할 수 있으므로 행사를 grain에서 빼면 재생성이 다른 행사의 색인을 지운다.

    ``content_json``은 ``app/services/indexing/document_builder.py``가 만든 결과 그대로다(그
    함수만 이 컬럼에 쓴다). ``search_text``는 키워드/PostgreSQL FTS용으로 미리 평탄화해 둔
    문자열이다 - ``app/services/catalog_search.py``가 exhibitor/product 원본 테이블에 대해
    매 검색 요청마다 하는 것과 달리, 이 트랙은 그 계산을 색인 생성 시점으로 미리 당겨 둔다.
    """

    __tablename__ = "search_document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id", f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"],
            name="fk_search_document_exhibitor_boundary",
        ),
        # grain은 (tenant, event, exhibitor, tier)다. event_id를 빼면 같은 업체를 행사 B로
        # 재생성할 때 행사 A의 행을 덮어써서 행사 A의 검색 결과에서 그 업체가 사라진다.
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "exhibitor_id",
            "tier",
            name="uq_search_document_exhibitor_tier",
        ),
        CheckConstraint(
            f"tier IN ({_in_list(SEARCH_DOCUMENT_TIERS)})", name="tier_allowed"
        ),
        CheckConstraint(
            f"status IN ({_in_list(SEARCH_DOCUMENT_STATUSES)})", name="status_allowed"
        ),
        # 검색/추천 조회는 항상 (tenant_id, event_id, tier, status='ACTIVE')로 필터한다 -
        # 조회 경로의 유일한 인덱스가 그 형태를 그대로 반영한다.
        Index(
            "ix_search_document_event_tier_status",
            "tenant_id",
            "event_id",
            "tier",
            "status",
        ),
        {"schema": SCHEMA_INDEXING},
    )

    search_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    # "sha256:" + 64자 hex - document-structuring.md §6 evidence_hash와 동일한 평문
    # 변경감지 관례(보안 목적 아님).
    content_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    # document.published_content_version.version_id 값들의 소프트 참조(FK 없음) - 이 문서가
    # 어떤 승인 스냅샷들로부터 만들어졌는지 추적한다. app/models/extraction.py의
    # document_id/entity_reference와 동일한 이유로 하드 FK를 걸지 않는다(그 테이블에 대한
    # 마이그레이션이 이 트랙보다 먼저 병합된다는 보장이 없다 - 두 트랙이 병렬로 개발 중).
    source_version_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IndexingJob(Base):
    """indexing.indexing_job - 재색인 요청/실행 기록.

    ``exhibitor_id``는 nullable이다 - 지금 구현(app/services/indexing/service.py)은 항상
    exhibitor 단위로 잡을 만들지만, 스키마 자체는 미래의 이벤트 전체 재색인(예: 온톨로지
    개정 후 전체 재계산) 같은 벌크 잡도 표현할 수 있게 열어 둔다.
    """

    __tablename__ = "indexing_job"
    __table_args__ = (
        CheckConstraint(
            f"trigger IN ({_in_list(INDEXING_JOB_TRIGGERS)})", name="trigger_allowed"
        ),
        CheckConstraint(
            f"status IN ({_in_list(INDEXING_JOB_STATUSES)})", name="status_allowed"
        ),
        Index("ix_indexing_job_exhibitor_created", "exhibitor_id", "created_at"),
        {"schema": SCHEMA_INDEXING},
    )

    indexing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 예: {"published_content_version_ids": [...]}  - 무엇이 이 잡을 유발했는지 최소 근거.
    source_reference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CacheInvalidationEvent(Base):
    """indexing.cache_invalidation_event - append-only 캐시 무효화 신호 로그.

    이 리포지토리 전체를 검색해도 실제 Redis 클라이언트 배선(연결/캐시 read-through 코드)이
    아직 어디에도 없다(``app/core/config.py``의 ``REDIS_URL``은 설정값만 존재 - 사용처 없음).
    그래서 이 테이블은 "지금 당장 실제로 무효화할 캐시"가 아니라, 나중에 실제 Redis 배선이
    들어왔을 때 그 배선이 tail-consume할 수 있는 내구성 있는 신호 큐 역할을 한다 - 작업 지시의
    "invalidate the relevant caches"를 지금 시점에 검증 가능한 형태(행이 생겼는지 assert)로
    만족시키면서, 실제 캐시 인프라가 없다는 사실도 숨기지 않는다(최종 보고서에 pending으로
    명시).
    """

    __tablename__ = "cache_invalidation_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["indexing_job_id"],
            [f"{SCHEMA_INDEXING}.indexing_job.indexing_job_id"],
            name="fk_cache_invalidation_event_indexing_job",
        ),
        CheckConstraint(
            f"cache_scope IN ({_in_list(CACHE_SCOPES)})", name="cache_scope_allowed"
        ),
        CheckConstraint(
            f"reason IN ({_in_list(INDEXING_JOB_TRIGGERS)})", name="reason_allowed"
        ),
        Index("ix_cache_invalidation_event_scope_created", "cache_scope", "created_at"),
        {"schema": SCHEMA_INDEXING},
    )

    cache_invalidation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cache_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    indexing_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

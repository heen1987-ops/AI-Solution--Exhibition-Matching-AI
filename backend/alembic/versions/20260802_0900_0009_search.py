"""create matching.search_session/search_query/search_result

이 마이그레이션은 `backend/app/models/search.py`를 대상으로 `alembic revision
--autogenerate`를 실행한 결과를 정리한 것이다(0006_matching과 동일한 관례).

근거 문서: `.harness/contracts/domain-model.md` §15(CTR-008 WAVE-1 크로스워크) -
WAVE-1 프롬프트의 SearchSession/SearchQuery/SearchResult 엔터티는 기존
`matching.recommendation_session`/`matching.match_result`(profile_id NOT NULL)로
표현할 수 없는, 프로파일 없는 검색(키오스크·GUEST_WEB)을 위한 별도 테이블이 진짜로
필요하다고 확인된 유일한 검색 관련 공백이다. `docs/redesign-v2/web/W-2-user-journey.md`
§1-6, `docs/redesign-v2/kiosk/K-4-search-and-results.md`, `docs/redesign-v2/common/
C-4-search-recommendation-engine.md`가 기능 근거다.

autogenerate가 감지했지만 이 마이그레이션에 포함하지 않은 변경 1건
------------------------------------------------------------------
`fk_supply_profile_attribute_concept_code`(exhibition.profile_attribute ->
ontology.concept 복합 FK)도 함께 감지됐으나, 이는 0006_matching/0007_meeting이 이미
문서화한 기존 갭(exhibition 도메인 담당, 이 마이그레이션과 무관)이므로 여기서도 그대로
제외한다.

Revision ID: 0009_search
Revises: 0008_widen_recommended_action
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_search"
down_revision: str | None = "0008_widen_recommended_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_session",
        sa.Column("search_session_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("guest_session_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel IN ('WEB', 'KIOSK')",
            name=op.f("ck_search_session_channel_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'COMPLETED')",
            name=op.f("ck_search_session_status_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name=op.f("ck_search_session_exactly_one_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["guest_session_id"],
            ["profile.guest_session.guest_session_id"],
            name=op.f("fk_search_session_guest_session_id_guest_session"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_search_session_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_search_session_user_id_user_account"),
        ),
        sa.PrimaryKeyConstraint("search_session_id", name=op.f("pk_search_session")),
        schema="matching",
    )
    op.create_index(
        "idx_search_session_guest",
        "search_session",
        ["guest_session_id", "started_at"],
        unique=False,
        schema="matching",
    )
    op.create_index(
        "idx_search_session_user",
        "search_session",
        ["user_id", "started_at"],
        unique=False,
        schema="matching",
    )
    op.create_table(
        "search_query",
        sa.Column("search_query_id", sa.UUID(), nullable=False),
        sa.Column("search_session_id", sa.UUID(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("query_type", sa.String(length=20), nullable=False),
        sa.Column("query_text", sa.String(length=500), nullable=True),
        sa.Column(
            "concept_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "intent_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("fallback_reason", sa.String(length=30), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fallback_reason IS NULL OR fallback_reason IN "
            "('NO_RESULT', 'AI_SERVICE_UNAVAILABLE', 'INVALID_QUERY')",
            name=op.f("ck_search_query_fallback_reason_allowed"),
        ),
        sa.CheckConstraint(
            "query_type IN ('FREE_TEXT', 'CATEGORY')",
            name=op.f("ck_search_query_query_type_allowed"),
        ),
        sa.CheckConstraint(
            "result_count >= 0", name=op.f("ck_search_query_result_count_nonneg")
        ),
        sa.CheckConstraint(
            "sequence_no >= 1", name=op.f("ck_search_query_sequence_no_positive")
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["matching.search_session.search_session_id"],
            name=op.f("fk_search_query_search_session_id_search_session"),
        ),
        sa.PrimaryKeyConstraint("search_query_id", name=op.f("pk_search_query")),
        sa.UniqueConstraint(
            "search_session_id",
            "sequence_no",
            name="uq_search_query_session_sequence",
        ),
        schema="matching",
    )
    op.create_table(
        "search_result",
        sa.Column("search_result_id", sa.UUID(), nullable=False),
        sa.Column("search_query_id", sa.UUID(), nullable=False),
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("structured_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("keyword_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("semantic_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column(
            "data_quality_score", sa.Numeric(precision=8, scale=5), nullable=True
        ),
        sa.Column(
            "availability_score", sa.Numeric(precision=8, scale=5), nullable=True
        ),
        sa.Column("final_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column(
            "reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_search_result_rank_positive")),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name=op.f("fk_search_result_recommendable_id_recommendable"),
        ),
        sa.ForeignKeyConstraint(
            ["search_query_id"],
            ["matching.search_query.search_query_id"],
            name=op.f("fk_search_result_search_query_id_search_query"),
        ),
        sa.PrimaryKeyConstraint("search_result_id", name=op.f("pk_search_result")),
        sa.UniqueConstraint(
            "search_query_id", "rank", name="uq_search_result_query_rank"
        ),
        sa.UniqueConstraint(
            "search_query_id",
            "recommendable_id",
            name="uq_search_result_query_recommendable",
        ),
        schema="matching",
    )
    op.create_index(
        "idx_search_result_query_rank",
        "search_result",
        ["search_query_id", "rank"],
        unique=False,
        schema="matching",
    )
    op.create_index(
        "idx_search_result_target",
        "search_result",
        ["recommendable_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="matching",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_search_result_target", table_name="search_result", schema="matching"
    )
    op.drop_index(
        "idx_search_result_query_rank", table_name="search_result", schema="matching"
    )
    op.drop_table("search_result", schema="matching")
    op.drop_table("search_query", schema="matching")
    op.drop_index(
        "idx_search_session_user", table_name="search_session", schema="matching"
    )
    op.drop_index(
        "idx_search_session_guest", table_name="search_session", schema="matching"
    )
    op.drop_table("search_session", schema="matching")

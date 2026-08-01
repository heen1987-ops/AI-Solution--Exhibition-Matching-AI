"""widen matching.match_result.recommended_action check constraint

근거 문서: docs/09-10-matching-implementation.md "다음 구현 순서" 7번. GENERAL_VISITOR
경로가 쓰는 5단계 상세설계 7.2절 어휘(VISIT_NOW 등 7종)와 BUYER/EXHIBITOR 경로가 쓰는
meet_ai.scoring.calculate_reciprocal_score의 recommended_action 어휘(DO_NOT_PUSH/
REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION, REQUEST_MEETING은 이미 겹침) 중 하나를
matching.match_result 한 테이블이 함께 저장해야 하는데, 기존 CHECK 제약은 전자만 허용해
app/services/matching/orchestrator.py가 후자를 저장하기 위해 손실 있는 매핑을 거쳐야
했다. 이 마이그레이션은 CHECK 제약을 두 어휘의 합집합으로 넓혀 그 매핑을 제거한다
(app/models/matching.py의 RECOMMENDED_ACTIONS 참고).

Postgres는 CHECK 제약을 in-place로 수정할 수 없어 기존 제약을 지우고 새 정의로
다시 만든다. DROP 시 명시적으로 이름을 지정해 SQLAlchemy 명명 규칙
(ck_%(table_name)s_%(constraint_name)s)이 만드는 실제 제약명과 맞춘다.

Revision ID: 0008_widen_recommended_action
Revises: 0007_meeting
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_widen_recommended_action"
down_revision: str | None = "0007_meeting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ACTIONS = (
    "VISIT_NOW",
    "SAVE_FOR_LATER",
    "REQUEST_MEETING",
    "ADD_TO_ROUTE",
    "COMPARE_PRODUCTS",
    "JOIN_PROGRAM",
    "REFINE_PROFILE",
)

_NEW_ACTIONS = _OLD_ACTIONS + (
    "DO_NOT_PUSH",
    "REQUEST_INFORMATION",
    "CONFIRM_TRADE_CONDITION",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_match_result_recommended_action_allowed"),
        "match_result",
        schema="matching",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_match_result_recommended_action_allowed"),
        "match_result",
        f"recommended_action IS NULL OR recommended_action IN ({_in_list(_NEW_ACTIONS)})",
        schema="matching",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_match_result_recommended_action_allowed"),
        "match_result",
        schema="matching",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_match_result_recommended_action_allowed"),
        "match_result",
        f"recommended_action IS NULL OR recommended_action IN ({_in_list(_OLD_ACTIONS)})",
        schema="matching",
    )

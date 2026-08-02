"""create core schemas

db-erd-table-spec.md 4절에 정의된 논리 스키마를 생성한다. 아직 도메인 모델이 없으므로
이 마이그레이션은 스키마(네임스페이스) 생성만 담당한다. 각 스키마의 테이블은 이후 단계
에이전트들이 도메인 모델을 만들 때 별도 마이그레이션으로 추가한다.

Revision ID: 0001_create_schemas
Revises:
Create Date: 2026-08-01

"""

from collections.abc import Sequence

from alembic import op
from app.db.base import ALL_SCHEMAS

# revision identifiers, used by Alembic.
revision: str = "0001_create_schemas"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for schema in ALL_SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    # 역순으로 제거한다. CASCADE는 이 마이그레이션이 스키마 생성만 담당하는 첫 마이그레이션이라
    # 스키마 안에 아직 아무 객체도 없다는 전제 하에 안전하다. 이후 테이블이 추가된 뒤에는
    # 이 다운그레이드를 그대로 재사용하지 말고 각 스키마의 테이블 마이그레이션을 먼저 되돌려야 한다.
    for schema in reversed(ALL_SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')

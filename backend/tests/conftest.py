"""비동기 DB 통합테스트 공용 fixture.

근거 문서: docs/09-10-matching-implementation.md "다음 구현 순서" 5번. 이 저장소에는
지금까지 실제 DB에 연결하는 pytest 관례가 없었다 - 기존 테스트는 전부 정적 검사
(Base.metadata, alembic ScriptDirectory) 또는 DB 없이 동작하는 순수 함수 검증이었다
(test_hard_filter_engine.py 등). 이 conftest가 그 관례를 도입한다.

관례
----
- `TEST_DATABASE_URL` 환경변수(기본값 `_DEFAULT_TEST_DATABASE_URL`)가 가리키는 Postgres에
  연결할 수 없으면(throwaway 인스턴스를 띄우지 않은 게 기본 상태다) `db_engine`/`db_session`을
  쓰는 테스트 전부를 자동으로 건너뛴다 - CI나 다른 개발자 환경에 실제 Postgres가 없어도
  나머지 스위트는 그대로 통과해야 한다.
- 연결 가능하면 세션 시작 시 한 번만 `alembic upgrade head`를 실행해 스키마를 최신으로
  맞춘다(pgvector 확장은 매번 새 DB를 만들 때 직접 `CREATE EXTENSION vector`로 준비해야
  한다 - 이 fixture는 확장을 만들지 않는다).
- 테스트마다(`db_session`) 독립된 AsyncSession 하나를 새로 만들어 준다. SQLAlchemy의
  "join a session into an external transaction"(SAVEPOINT 기반 자동 롤백) 레시피를
  먼저 시도했지만, 이 스택(SQLAlchemy 2.0 async + asyncpg + greenlet)에서 ORM이 내부
  bind-connection 관리를 위해 greenlet_spawn 컨텍스트 밖에서 `conn.begin_nested()`를
  직접 호출하는 경로가 있어 `MissingGreenlet`으로 계속 깨졌다 - 재현성 있는 자동 롤백보다
  "확실히 동작하는 단순한 방식"을 택했다. 그래서 테스트가 만든 행은 실제로 커밋되어 DB에
  남는다: 테스트 함수가 유니크 컬럼(tenant_code 등)에 `uuid.uuid4()` 접미사를 붙여 서로
  충돌하지 않게 하는 책임을 진다(test_orchestrator_integration.py 참고). throwaway DB는
  필요하면 언제든 drop/recreate하면 된다 - 이 저장소에서 지금까지 실제 검증할 때 써온
  방식과 같다.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:5432/backju_test"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)


def _can_connect(url: str) -> bool:
    """TEST_DATABASE_URL이 우리 테스트용 DB를 가리키는지 확인한다.

    "연결 불가"는 소켓 자체가 열리지 않는 경우(OSError)만이 아니다 - 이 포트에 이미 다른
    용도의 Postgres가 떠 있어 인증이 실패하는 경우(예: 기본 5432 포트에 이 저장소와
    무관한 로컬 Postgres가 이미 떠 있는 개발 환경)도 "우리 테스트 DB에 연결할 수 없다"는
    점에서는 같다 - 그래서 예외 종류를 가리지 않고 광범위하게 잡아 건너뛴다.
    """

    async def _probe() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect():
                return True
        except Exception:  # noqa: BLE001 - 어떤 이유로든 못 붙으면 건너뛴다
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_probe())


def _upgrade_to_head(url: str) -> None:
    """alembic/env.py는 app.core.config.get_settings().DATABASE_URL을 최종 접속 주소로
    쓴다(alembic.ini의 sqlalchemy.url을 덮어쓴다) - 그래서 Config에 URL을 지정하는 것만으로는
    부족하고, get_settings()가 이 테스트 DB를 보도록 환경변수를 먼저 맞추고 lru_cache를
    비워야 한다."""

    os.environ["DATABASE_URL"] = url

    from app.core.config import get_settings

    get_settings.cache_clear()

    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def _migrated_test_database_url() -> (
    str
):  # pragma: no cover - 실제 Postgres가 있어야 실행된다
    """세션당 한 번만: 연결 가능 여부 확인 + `alembic upgrade head`.

    AsyncEngine을 여기서 만들어 세션 스코프로 재사용하지 않는다 - asyncpg 커넥션(풀)은
    자신을 만든 이벤트 루프에 묶이는데, pytest-asyncio는 (loop_scope를 별도로 올려두지
    않는 한) 비동기 테스트 함수마다 새 이벤트 루프를 만든다. 세션 스코프 AsyncEngine을
    여러 테스트에 걸쳐 재사용하면 "another operation is in progress" 같은 이벤트루프
    불일치 오류가 난다 - 그래서 무거운 작업(연결 확인, 마이그레이션)만 세션 스코프로 한
    번 하고, AsyncEngine 자체는 테스트(이벤트 루프)마다 새로 만든다(db_engine fixture).
    """

    url = _test_database_url()
    if not _can_connect(url):
        pytest.skip(
            f"TEST_DATABASE_URL({url})에 연결할 수 없어 DB 통합테스트를 건너뜁니다. "
            "throwaway Postgres(+pgvector 확장)를 띄우고 필요하면 TEST_DATABASE_URL을 "
            "지정하세요."
        )

    _upgrade_to_head(url)
    return url


@pytest_asyncio.fixture
async def db_engine(
    _migrated_test_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_migrated_test_database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

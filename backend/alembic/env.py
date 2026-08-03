"""Alembic 마이그레이션 환경 설정 (SQLAlchemy 2.0 async 엔진 연동).

DATABASE_URL은 alembic.ini에 하드코딩하지 않고 app.core.config.Settings에서 읽는다.
그래야 로컬/개발/운영 환경에서 동일한 alembic.ini로 .env만 바꿔서 동작한다.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# --- 프로젝트 모듈 임포트 ---
# alembic.ini의 prepend_sys_path = . 설정 덕분에(backend/ 디렉터리에서 alembic 명령을 실행한다는
# 전제 하에) app 패키지를 임포트할 수 있다.
from app.core.config import get_settings
from app.db.base import SCHEMA_ONTOLOGY, Base
from app.models import (  # noqa: F401
    ai,
    consent,
    core,
    exhibitor,
    identity,
    kiosk,
    matching,
    meeting,
    ontology_refs,
    profile,
    search,
)

# Alembic Config 객체: alembic.ini의 값에 접근하는 통로
config = context.config

# alembic.ini의 sqlalchemy.url 자리표시자를 실제 런타임 설정값으로 덮어쓴다.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# .ini의 로깅 설정 적용
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 비교 대상 메타데이터
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Keep ontology changes in its immutable SQL contract, not autogenerate."""

    del name, type_, reflected, compare_to
    return getattr(object_, "schema", None) != SCHEMA_ONTOLOGY


def run_migrations_offline() -> None:
    """--sql 옵션 등으로 실제 DB 연결 없이 마이그레이션 스크립트만 생성할 때 사용한다."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """비동기 엔진으로 연결한 뒤, 동기 컨텍스트(run_sync)에서 실제 마이그레이션을 수행한다."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

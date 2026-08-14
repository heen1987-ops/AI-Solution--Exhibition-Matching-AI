"""SQLAlchemy 2.0 비동기 엔진/세션 관리.

중요: 이 모듈을 임포트하는 것만으로는 DB에 연결하지 않는다.
create_async_engine 자체가 SQLAlchemy에서 지연(lazy) 초기화지만, 여기서는 한 걸음 더 나아가
엔진과 세션메이커 생성 자체를 첫 사용 시점(get_engine/get_sessionmaker 최초 호출, 보통 요청이
get_db 의존성을 거칠 때)까지 미룬다. 그래서 DB가 떠 있지 않아도 `import app.main`은 항상 성공해야
한다 (헬스체크, OpenAPI 스키마 생성 등은 DB 없이도 동작해야 하기 때문).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """비동기 엔진을 최초 호출 시점에 생성하고 이후 재사용한다.

    create_async_engine 자체는 실제 소켓 연결을 열지 않는다 (connection pool은 checkout 시점에
    연결한다). lru_cache로 감싼 이유는 프로세스당 엔진 인스턴스를 하나로 유지하고, 엔진 생성
    시점을 명시적으로 "필요할 때"로 고정하기 위함이다.
    """

    settings = get_settings()
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """AsyncSession 팩토리를 최초 호출 시점에 생성하고 이후 재사용한다."""

    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends용 세션 제너레이터.

    사용 예:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...

    요청마다 세션을 새로 열고, 요청이 끝나면 닫는다. 커밋은 라우터/서비스 계층 책임이다
    (여기서는 명시적으로 commit하지 않고, 예외 발생 시 rollback만 보장한다).
    """

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

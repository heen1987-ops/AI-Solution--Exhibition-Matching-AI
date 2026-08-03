"""BAC-001 health-check API tests.

이 파일은 BACKEND 트랙(BAC-001)이 작성한 테스트를 QA_SECURITY 소유 경로
(`backend/tests/**`)에 반영한 것이다. 원 요청과 검증 근거는
`.harness/handoffs/qa/BAC-001-test-request.md`에 있다.

실행 규약은 기존 `backend/tests/conftest.py` 관례를 따른다: 실제 Postgres에 연결할 수
없으면 해당 단일 테스트만 skip하고 나머지는 항상 통과해야 한다.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient


def _postgres_reachable(url: str) -> bool:
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _probe() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect():
                return True
        except Exception:  # noqa: BLE001 - 연결 불가면 Postgres 확인만 skip한다.
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_probe())


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_settings_cache_per_test():
    _clear_settings_cache()
    yield
    _clear_settings_cache()


def _clear_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()


def test_health_live_always_succeeds_without_dependencies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nouser:nopass@127.0.0.1:1/nodb")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    _clear_settings_cache()

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready_returns_error_shape_when_redis_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    _clear_settings_cache()

    response = client.get("/health/ready")
    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "error"
    assert set(body["checks"].keys()) == {"postgres", "redis", "s3"}


def test_health_ready_s3_down_is_warning_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.delenv("READY_CHECK_FAILS_ON_S3_DOWN", raising=False)
    _clear_settings_cache()

    response = client.get("/health/ready")
    body = response.json()

    assert body["checks"]["s3"] == "warning"


def test_health_ready_s3_down_fails_when_flag_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.setenv("READY_CHECK_FAILS_ON_S3_DOWN", "true")
    _clear_settings_cache()

    response = client.get("/health/ready")
    body = response.json()

    assert response.status_code == 503
    assert body["checks"]["s3"] == "error"
    assert body["status"] == "not_ready"


def test_health_ready_postgres_ok_when_reachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5432/backju_test"
    )
    if not _postgres_reachable(url):
        pytest.skip(
            f"DATABASE_URL({url})에 연결할 수 없어 건너뜁니다 - throwaway Postgres를 "
            "띄우고 TEST_DATABASE_URL을 지정하면 이 테스트가 실행됩니다."
        )

    monkeypatch.setenv("DATABASE_URL", url)
    _clear_settings_cache()

    response = client.get("/health/ready")
    body = response.json()

    assert body["checks"]["postgres"] == "ok"


def test_system_info_matches_exact_contract_schema(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")
    body = response.json()

    assert response.status_code == 200
    assert body == {
        "service": "backju-ai-matching-api",
        "version": "0.1.0",
        "environment": body["environment"],
        "contract_version": "draft",
    }
    assert set(body.keys()) == {"service", "version", "environment", "contract_version"}


def test_healthz_legacy_endpoint_still_works(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

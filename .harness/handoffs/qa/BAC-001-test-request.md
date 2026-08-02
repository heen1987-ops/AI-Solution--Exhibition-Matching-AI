# BAC-001 - backend/tests/test_health_api.py 반영 요청 (BACKEND -> QA_SECURITY)

## 요청 배경

BAC-001(Health Check API: `/health/live`, `/health/ready`, `/api/v1/system/info`)의
acceptance는 이 엔드포인트들에 대한 실제 테스트를 요구한다. 그런데 `.harness/locks.yaml`상
`backend/tests/**`는 QA_SECURITY 전속 경로다(BAC-001 dispatch 프롬프트의 owned_paths에는
이 사실이 없었지만 `locks.yaml`이 정본이라 그쪽을 따랐다 - AIS-002 때도 동일한 트랙
불일치가 있었고 그때 QA_SECURITY로 정정된 선례가 있다, `backlog.yaml` AIS-002 항목 참고).

그래서 BACKEND가 아래 테스트를 **작성하고 scratch 환경에서 실제로 실행해 통과를 확인**한
뒤, 파일 자체는 `backend/tests/`에 커밋하지 않고 이 handoff로 전달한다.

## 요청 내용

아래 전문을 그대로 `backend/tests/test_health_api.py`로 추가해달라(수정 없이 그대로
써도 통과 확인됨 - 아래 "검증 결과" 참고). 필요하면 이 저장소의 다른 `backend/tests/*.py`
스타일(예: import 순서, docstring 톤)에 맞춰 다듬어도 좋다 - 로직은 바꾸지 않기를 권장한다.

```python
"""BAC-001 health-check API tests.

이 파일은 BACKEND 트랙(BAC-001)이 작성했지만 backend/tests/**가 .harness/locks.yaml상
QA_SECURITY 전속 경로라 직접 커밋하지 않는다(AIS-002와 동일한 선례 - run-log.md 참고).
QA_SECURITY가 이 내용을 backend/tests/test_health_api.py로 반영해달라는 요청을
.harness/handoffs/qa/BAC-001-test-request.md에 남겼다. 아래는 BACKEND가
scratch 환경에서 실제로 실행해 통과를 확인한 원본이다.

실행 규약은 기존 backend/tests/conftest.py 관례를 따른다: 실제 Postgres에 연결할 수
없으면(이 저장소의 기본 상태) 해당 단일 테스트만 skip하고 나머지는 항상 통과해야 한다.
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
        except Exception:  # noqa: BLE001
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_probe())


@pytest.fixture()
def client() -> TestClient:
    """TestClient를 만든다.

    주의(중요): app.core.config.get_settings는 lru_cache다 - 헬스체크/system-info
    핸들러는 요청마다 get_settings()를 새로 호출하므로 캐시만 비우면 최신 환경변수를
    읽지만, "비우는 시점"이 중요하다. monkeypatch.setenv(...)로 환경변수를 바꾼
    "다음"에 캐시를 비워야 한다 - 먼저 비우고 그 다음에 setenv하면 다음 get_settings()
    호출이 setenv 이전 상태를 다시 캐싱해버려 테스트가 아무것도 검증하지 않는 거짓
    통과(false positive)가 된다. 그래서 캐시 비우기는 fixture가 아니라 각 테스트
    본문에서 monkeypatch.setenv(...) 직후 _clear_settings_cache()로 명시적으로 한다.
    """

    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_settings_cache_per_test():
    """테스트 간 lru_cache 오염을 막는다.

    monkeypatch는 테스트 종료 시 환경변수를 자동으로 되돌리지만 get_settings()의
    lru_cache까지 자동으로 비워주지는 않는다 - 그래서 각 테스트 시작·종료 시점에
    명시적으로 비워 이전/이후 테스트가 서로의 캐시된 설정을 보지 않게 한다.
    """

    _clear_settings_cache()
    yield
    _clear_settings_cache()


def _clear_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()


def test_health_live_always_succeeds_without_dependencies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """의존성이 전부 끊겨 있어도 /health/live는 항상 200 {"status": "alive"}."""

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nouser:nopass@127.0.0.1:1/nodb")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    _clear_settings_cache()

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready_returns_error_shape_when_redis_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis에 연결할 수 없으면 checks.redis="error", 전체 status="not_ready"(503).

    실제로 죽어 있는 Redis를 띄울 필요 없이, 아무도 리스닝하지 않는 포트(1)를 가리키는
    것만으로 "장애" 상태를 재현한다(BAC-001 태스크 지시사항).
    """

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
    """READY_CHECK_FAILS_ON_S3_DOWN 기본값(false)에서는 S3 장애가 경고일 뿐 전체 실패로
    번지지 않는다 - Postgres/Redis가 없는 이 테스트 환경에서도 checks.s3만 검증한다."""

    monkeypatch.setenv("S3_ENDPOINT", "http://127.0.0.1:1")
    monkeypatch.delenv("READY_CHECK_FAILS_ON_S3_DOWN", raising=False)
    _clear_settings_cache()

    response = client.get("/health/ready")
    body = response.json()

    assert body["checks"]["s3"] == "warning"


def test_health_ready_s3_down_fails_when_flag_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """READY_CHECK_FAILS_ON_S3_DOWN=true면 S3 장애가 checks.s3="error"이자 전체
    status도 "not_ready"(503)로 번진다."""

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
    """PostgreSQL이 정상일 때 checks.postgres="ok".

    기존 conftest.py 관례와 동일하게, 이 저장소 기본 상태(throwaway Postgres 미기동)에서는
    TEST_DATABASE_URL/DATABASE_URL에 연결할 수 없으므로 이 테스트만 skip한다 - 나머지
    스위트는 항상 통과해야 한다.
    """

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
    """/api/v1/system/info는 개인정보 없이 정확히 4개 필드만 반환한다."""

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
    """기존 /healthz는 하위 호환을 위해 유지된다(README/DEVELOPMENT.md/quality-gates.yaml
    참조 - main.py docstring 참고)."""

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

## 검증 결과 (BACKEND가 scratch 환경에서 실행)

Python 3.12 venv에 `backend/pyproject.toml[dev]` + 루트 `pyproject.toml`(meet_ai)을
`pip install -e`한 뒤, 위 파일을 scratch 경로에 두고
`PYTHONPATH=<backend 절대경로> pytest <scratch>/test_health_api.py -v` 실행:

```
test_health_live_always_succeeds_without_dependencies PASSED
test_health_ready_returns_error_shape_when_redis_down PASSED
test_health_ready_s3_down_is_warning_by_default PASSED
test_health_ready_s3_down_fails_when_flag_enabled PASSED
test_health_ready_postgres_ok_when_reachable SKIPPED (실제 Postgres 없음 - conftest.py 관례와 동일)
test_system_info_matches_exact_contract_schema PASSED
test_healthz_legacy_endpoint_still_works PASSED

6 passed, 1 skipped
```

`backend/tests/`로 그대로 옮기면 `conftest.py`가 자동 적용되므로
`test_health_ready_postgres_ok_when_reachable`은 실제 Postgres가 있는 CI/로컬
환경에서는 PASSED로 바뀔 것으로 예상한다(로직상 `_migrated_test_database_url`류 스킵
조건과 동일).

## 처리 방법

1. 위 코드 블록을 `backend/tests/test_health_api.py`로 저장.
2. `cd backend && pytest tests/test_health_api.py -v`로 재확인.
3. `cd backend && pytest -q`로 전체 스위트 회귀 확인(작업 전 베이스라인 90 passed, 11
   skipped에 이 7개 테스트가 더해져야 한다 - 즉 96 passed 근방 + skip 1개 추가 예상).
4. `.harness/backlog.yaml`의 BAC-001 항목에 이 테스트 반영 완료를 기록(또는 QA_SECURITY
   자체 태스크 ID를 새로 만들어 추적 - 어느 쪽이든 `run-log.md`에 남겨달라).

## 참고

- 이 요청은 `AGENTS.md` §4("다른 트랙 소유 경로가 필요하면 handoffs/{track}/에 요청을
  남긴다")를 따른 것이다 - BACKEND가 `backend/tests/**`를 직접 수정하지 않았다.
- 구현 자체(`backend/app/api/health.py`, `backend/app/api/v1/endpoints/system.py`)에
  대한 상세는 `.harness/handoffs/backend/BAC-001-health.md` 참고.

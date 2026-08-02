"""헬스체크 엔드포인트: liveness와 readiness.

- `GET /health/live`: 프로세스 생존 여부만 확인한다. 의존성 체크가 전혀 없어 항상
  빠르게(밀리초 단위) 응답해야 한다 - 오케스트레이터(k8s 등)가 컨테이너 재시작 여부를
  판단하는 용도라 DB/Redis가 죽어 있어도 프로세스 자체는 살아있다면 alive다.
- `GET /health/ready`: PostgreSQL·Redis 연결을 실제로 확인한다. PostgreSQL 또는
  Redis 중 하나라도 실패하면 전체 status는 "not_ready"(HTTP 503)다. S3(MinIO)는
  `READY_CHECK_FAILS_ON_S3_DOWN` 설정에 따라 분기한다(BAC-001 acceptance):
    - false(기본값): S3 장애는 checks.s3="warning"만 남기고 전체 status는
      "degraded"(HTTP 200 유지) - MinIO는 이번 Wave에서 아직 실제 업로드 경로가
      없어 서비스 가용성에 치명적이지 않다고 판단.
    - true: S3 장애가 checks.s3="error"가 되고 전체 status도 "not_ready"(HTTP 503).

이 라우터는 `/api/v1` 프리픽스 밖(main.py에서 `/health`로 직접 마운트)에 있다 -
헬스체크는 API 버전과 무관한 인프라 계약이라는 기존 `/healthz` 관례를 따른다.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine

router = APIRouter()

DependencyStatus = Literal["ok", "error", "warning"]
ReadyStatus = Literal["ready", "degraded", "not_ready"]


class ReadyChecks(BaseModel):
    postgres: DependencyStatus
    redis: DependencyStatus
    s3: DependencyStatus


class ReadyResponse(BaseModel):
    status: ReadyStatus
    checks: ReadyChecks


@router.get("/live")
async def live() -> dict[str, str]:
    """의존성 체크 없는 순수 liveness 확인. 항상 즉시 200을 반환한다."""

    return {"status": "alive"}


async def _check_postgres() -> DependencyStatus:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - 원인 불문, 연결 실패는 전부 error로 취급
        return "error"


async def _check_redis() -> DependencyStatus:
    settings = get_settings()
    client: Redis = Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await client.ping()
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"
    finally:
        await client.aclose()


def _s3_reachable() -> bool:
    """S3(MinIO) 엔드포인트에 TCP 연결이 가능한지만 확인한다.

    버킷 권한·실제 오브젝트 접근까지는 검증하지 않는다 - 헬스체크 목적상 "네트워크로
    도달 가능한가"만 확인하면 충분하고, 이 정도를 위해 boto3 등 새 SDK 의존성을 추가하지
    않기 위해 표준 라이브러리 socket으로 host:port 연결만 시도한다.
    """

    settings = get_settings()
    parsed = urlparse(settings.S3_ENDPOINT)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


async def _check_s3() -> DependencyStatus:
    settings = get_settings()
    reachable = await asyncio.to_thread(_s3_reachable)
    if reachable:
        return "ok"
    return "error" if settings.READY_CHECK_FAILS_ON_S3_DOWN else "warning"


@router.get("/ready", response_model=ReadyResponse)
async def ready(response: Response) -> ReadyResponse:
    settings = get_settings()

    postgres_status, redis_status, s3_status = await asyncio.gather(
        _check_postgres(), _check_redis(), _check_s3()
    )

    critical_failure = postgres_status == "error" or redis_status == "error"
    s3_hard_failure = s3_status == "error" and settings.READY_CHECK_FAILS_ON_S3_DOWN

    if critical_failure or s3_hard_failure:
        overall: ReadyStatus = "not_ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif s3_status in ("warning", "error"):
        overall = "degraded"
        response.status_code = status.HTTP_200_OK
    else:
        overall = "ready"
        response.status_code = status.HTTP_200_OK

    return ReadyResponse(
        status=overall,
        checks=ReadyChecks(postgres=postgres_status, redis=redis_status, s3=s3_status),
    )

"""시스템 정보 엔드포인트.

`GET /api/v1/system/info`는 개인정보·비밀값을 전혀 포함하지 않는 정적 메타데이터만
반환한다(AGENTS.md §8). 응답 스키마는 BAC-001 acceptance에 정의된 그대로 고정한다 -
필드를 추가하려면 계약 변경(CTR 트랙 Change Request)을 거친다.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter()

_SERVICE_NAME = "backju-ai-matching-api"
_CONTRACT_VERSION = "draft"


class SystemInfo(BaseModel):
    service: str
    version: str
    environment: str
    contract_version: str


@router.get("/info", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    settings = get_settings()
    return SystemInfo(
        service=_SERVICE_NAME,
        version="0.1.0",
        environment=settings.ENV,
        contract_version=_CONTRACT_VERSION,
    )

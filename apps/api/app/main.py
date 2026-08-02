"""FastAPI 애플리케이션 엔트리포인트.

이 파일을 임포트하는 것(`import app.main` 또는 `uvicorn app.main:app`)은 DB/Redis가
떠 있지 않아도 항상 성공해야 한다. 실제 DB 연결은 app.db.session.get_db가 요청 처리 중
호출될 때 비로소 이루어진다 (app/db/session.py docstring 참고).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.api import api_router
from app.api.v1.routers.recommendations import (
    RecommendationApiException,
    database_exception_handler,
    recommendation_exception_handler,
)
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
)
app.add_exception_handler(
    RecommendationApiException,
    recommendation_exception_handler,
)
app.add_exception_handler(SQLAlchemyError, database_exception_handler)

# 개발용 CORS 설정: 기본값(CORS_ORIGINS=*)은 전체 허용이다.
# 운영 환경에서는 .env의 CORS_ORIGINS를 콤마로 구분된 실제 origin 목록으로 반드시 재정의한다.
# 참고: allow_origins=["*"]와 allow_credentials=True는 브라우저 CORS 규격상 함께 쓸 수 없으므로,
# 와일드카드일 때는 쿠키 기반 인증(allow_credentials)을 끈다.
_cors_origins = settings.cors_origins_list
_allow_credentials = _cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """가벼운 liveness 체크. DB/Redis 연결을 확인하지 않는다(의도적으로 무의존).

    실제 readiness(DB/Redis 연결 확인)가 필요해지면 별도 /readyz 엔드포인트로 분리한다.
    """

    return {"status": "ok"}


# 이후 단계 에이전트들이 app/api/v1/api.py의 api_router에 각자 라우터를 추가한다.
# 여기서는 완성된 api_router를 설정된 기본 경로(기본값 /api/v1, docs/frontend-backend-ai-interface-spec.md
# 4.1절 기준)에 마운트하기만 한다.
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

"""v1 API 라우터 애그리게이터.

주의: 이 파일은 여러 에이전트가 동시에 작업하는 공용 파일이다.
각 도메인 라우터(예: profiles, recommendations, meetings ...)를 구현하는 에이전트가
자신의 router를 여기에 include_router로 추가한다. 지금 단계에서는 기반 골격만 제공하므로
빈 APIRouter만 둔다.

app.main은 이 모듈의 api_router를 settings.API_V1_PREFIX(기본 /api/v1)로 include한다.

추가 예시:
    from app.api.v1.endpoints import profiles

    api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
"""

from fastapi import APIRouter

from app.api.v1.endpoints import ontology
from app.api.v1.routers import (
    adaptive,
    auth,
    consent,
    conversation,
    exhibitors,
    imports,
    kiosk,
    meetings,
    partner,
    profile,
    recommendations,
    search,
    sessions,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(sessions.router, tags=["sessions"])
api_router.include_router(ontology.router, prefix="/ontology", tags=["ontology"])
api_router.include_router(profile.router, tags=["profiles"])
api_router.include_router(consent.router, tags=["consent-and-privacy"])
api_router.include_router(conversation.router, tags=["conversational-profiling"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(adaptive.router, tags=["adaptive-personalization"])
api_router.include_router(partner.router, tags=["partner"])
api_router.include_router(meetings.router, tags=["meetings"])
api_router.include_router(imports.router, tags=["imports"])
api_router.include_router(webhooks.router, tags=["webhooks"])
api_router.include_router(exhibitors.router, tags=["public-catalog"])
api_router.include_router(search.router, tags=["search"])
api_router.include_router(kiosk.router, tags=["kiosk"])

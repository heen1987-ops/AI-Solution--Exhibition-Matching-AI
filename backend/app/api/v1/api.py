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

from app.api.v1.endpoints import (
    admin,
    buyer,
    exhibitors,
    favorites,
    guest,
    kiosk,
    ontology,
    profile,
    search,
    system,
)

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(buyer.buyer_router, prefix="/buyer", tags=["buyer"])
api_router.include_router(exhibitors.router)
api_router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(guest.router, prefix="/guest", tags=["guest"])
api_router.include_router(kiosk.router, prefix="/kiosk", tags=["kiosk"])
api_router.include_router(buyer.meetings_router, prefix="/meetings", tags=["meetings"])
api_router.include_router(ontology.router, prefix="/ontology", tags=["ontology"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(search.router)
api_router.include_router(system.router, prefix="/system", tags=["system"])

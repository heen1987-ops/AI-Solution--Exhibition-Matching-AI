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
from app.api.v1.routers.admin import build_admin_router
from app.api.v1.routers.analytics import build_analytics_router
from app.api.v1.routers.buyer_match import build_buyer_match_router
from app.api.v1.routers.buyer_profile import build_buyer_profile_router
from app.api.v1.routers.checkin import build_checkin_router
from app.api.v1.routers.document import build_document_router
from app.api.v1.routers.event_message import build_event_message_router
from app.api.v1.routers.exhibitor_preference import build_exhibitor_preference_router
from app.api.v1.routers.extraction import build_extraction_router
from app.api.v1.routers.favorites import build_favorites_router
from app.api.v1.routers.feedback import build_feedback_router
from app.api.v1.routers.notification import build_notification_router
from app.api.v1.routers.route import build_route_router

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

# --- MERGE STEP 27: WAVE 2C/2D/2E ported routers (additive only) -----------
# meeting_buyer_extension.py and interaction_event.py are DELIBERATELY not
# registered here - steps 22 and 25 folded their capabilities into the
# existing meetings.py / recommendations.py surfaces (see those modules'
# docstrings). Registering either would create a second, unauthenticated or
# doubly-governed write path over the same rows.
api_router.include_router(build_buyer_profile_router(), tags=["buyer-profile"])
api_router.include_router(build_buyer_match_router(), tags=["buyer-match"])
api_router.include_router(
    build_exhibitor_preference_router(), tags=["exhibitor-preference"]
)
api_router.include_router(build_document_router(), tags=["documents"])
api_router.include_router(build_extraction_router(), tags=["ai-extraction-review"])
api_router.include_router(build_analytics_router(), tags=["operator-analytics"])
api_router.include_router(build_notification_router(), tags=["notifications"])
api_router.include_router(
    build_event_message_router(), prefix="/admin", tags=["event-messages"]
)

# --- MERGE STEP 28: favorites/check-in/feedback/admin (additive only) ------
# Each track's own docstring documents this exact registration call; none of
# these need an extra prefix (favorites/checkin/feedback bake in their own
# full paths, admin.py's router already carries prefix="/admin").
api_router.include_router(build_favorites_router(), tags=["favorites"])
api_router.include_router(build_checkin_router(), tags=["checkin"])
api_router.include_router(build_feedback_router(), tags=["feedback"])
api_router.include_router(build_admin_router(), tags=["admin"])

# --- MERGE STEP 29: ROUTE-001 indoor route navigation (additive only) ------
api_router.include_router(build_route_router(), tags=["indoor-route"])

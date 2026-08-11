"""WAVE2C BACKEND-EXHIBITOR-PREFERENCE 서비스 계층.

``app/api/v1/routers/exhibitor_preference.py``(파트너 인증 프리픽스 아래 마운트는
integrator 책임)와 향후 AI-BUYER-MATCH 트랙이 이 패키지의 공개 함수만 사용해야 한다.
"""

from __future__ import annotations

from app.services.exhibitor_preference.service import (
    get_exhibitor_preference_view,
    has_buyer_preference,
    is_publicly_visible,
    replace_cooperation_types,
    upsert_trade_availability,
)

__all__ = [
    "get_exhibitor_preference_view",
    "has_buyer_preference",
    "is_publicly_visible",
    "replace_cooperation_types",
    "upsert_trade_availability",
]

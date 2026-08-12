"""BACKEND-016 QR 체크인 서비스 계층.

``app/api/v1/routers/checkin.py``만 이 패키지의 공개 함수를 써야 한다. 자세한 설계 근거는
``app/services/checkin/service.py``의 모듈 docstring 참고.
"""

from __future__ import annotations

from app.services.checkin.service import (
    BoothClosedError,
    InvalidQrError,
    VerifiedBoothQr,
    VisitSessionNotFoundError,
    find_recent_check_in,
    resolve_active_visit_session_id,
    submit_check_in,
    verify_booth_qr,
)

__all__ = [
    "BoothClosedError",
    "InvalidQrError",
    "VerifiedBoothQr",
    "VisitSessionNotFoundError",
    "find_recent_check_in",
    "resolve_active_visit_session_id",
    "submit_check_in",
    "verify_booth_qr",
]

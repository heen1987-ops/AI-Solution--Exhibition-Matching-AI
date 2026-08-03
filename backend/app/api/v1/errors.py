"""OpenAPI-compatible error helpers for v1 endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException


def error_body(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: uuid.UUID | None = None,
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": str(request_id or uuid.uuid4()),
            "details": details,
        }
    }


def api_error(
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_body(code, message, details=details)["error"],
    )

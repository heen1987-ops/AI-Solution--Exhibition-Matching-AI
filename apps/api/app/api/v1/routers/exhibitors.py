"""Compatibility entrypoint for the public exhibition catalog router.

BACKEND-008 owns this module path, while the complete implementation is split
into the dedicated ``exhibition_public`` router/service/repository layers.
Re-exporting the router keeps one canonical route set and prevents duplicate
FastAPI registrations from shadowing the richer implementation.
"""

from app.api.v1.routers.exhibition_public import router

__all__ = ["router"]

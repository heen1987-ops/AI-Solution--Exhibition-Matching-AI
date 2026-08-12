"""BACKEND-009 관심목록(즐겨찾기) 서비스 계층.

``app/api/v1/routers/favorites.py``만 이 패키지의 공개 함수를 써야 한다. 자세한 설계 근거는
``app/services/favorite/service.py``의 모듈 docstring 참고.
"""

from __future__ import annotations

from app.services.favorite.service import (
    RECOMMENDABLE_TYPE_TO_PUBLIC,
    FavoriteObjectType,
    FavoriteWithTarget,
    InvalidMatchResultError,
    active_favorite_for_target_stmt,
    create_favorite,
    list_favorites,
    list_favorites_stmt,
    own_favorite_stmt,
    resolve_recommendable_id,
    soft_delete_favorite,
)

__all__ = [
    "RECOMMENDABLE_TYPE_TO_PUBLIC",
    "FavoriteObjectType",
    "FavoriteWithTarget",
    "InvalidMatchResultError",
    "active_favorite_for_target_stmt",
    "create_favorite",
    "list_favorites",
    "list_favorites_stmt",
    "own_favorite_stmt",
    "resolve_recommendable_id",
    "soft_delete_favorite",
]

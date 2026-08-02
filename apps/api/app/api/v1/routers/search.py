"""Anonymous web/kiosk catalog search endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import build_envelope, get_request_id
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.profile import Envelope
from app.schemas.search import (
    SearchClarification,
    SearchInterpretedQuery,
    SearchRequest,
    SearchResponse,
)
from app.services.catalog_search import search_approved_catalog
from app.services.search_query_interpreter import interpret_query
from app.services.search_sessions import (
    SearchSessionRecord,
    SearchSessionStore,
    get_search_session_store,
)

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StoreDep = Annotated[SearchSessionStore, Depends(get_search_session_store)]
RequestIdDep = Annotated[str, Depends(get_request_id)]


def _error(
    status_code: int, code: str, message: str, *, retryable: bool = False
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "field_errors": [],
            "retryable": retryable,
            "retry_after_seconds": 3 if retryable else None,
        },
    )


def _clarification_for_empty_results() -> SearchClarification:
    return SearchClarification(
        question="조건에 맞는 부스를 찾지 못했어요. 다른 표현으로 다시 검색해 보시겠어요?",
        options=["막걸리", "증류주", "전통주 체험", "선물용 제품"],
    )


@router.post("/search", response_model=Envelope[SearchResponse])
async def create_search(
    payload: SearchRequest,
    db: DbDep,
    settings: SettingsDep,
    store: StoreDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    # TODO: replace with ai.query_interpreter.QueryInterpreter once that
    # interface is published (BACKEND-008 note) — interpret_query() is a
    # deliberate minimal stand-in (see search_query_interpreter.py docstring).
    interpreted = interpret_query(payload.query)
    concept_codes = list(
        dict.fromkeys([*payload.category_codes, *interpreted.concept_codes])
    )

    try:
        results = await search_approved_catalog(
            db,
            event_id=payload.event_id,
            query=payload.query,
            category_codes=concept_codes,
            limit=payload.limit,
        )
    except SQLAlchemyError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SEARCH_UNAVAILABLE",
            "승인된 업체 정보를 검색할 수 없습니다.",
            retryable=True,
        ) from exc

    created_at = datetime.now(UTC)
    response = SearchResponse(
        search_session_id=uuid.uuid4(),
        channel=payload.channel,
        interpreted_query=SearchInterpretedQuery(concepts=concept_codes),
        results=results,
        clarification=None if results else _clarification_for_empty_results(),
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=settings.SEARCH_SESSION_TTL_SECONDS),
    )
    try:
        await store.save(
            SearchSessionRecord(
                response=response,
                event_id=payload.event_id,
                query=payload.query,
                category_codes=payload.category_codes,
            ),
            settings.SEARCH_SESSION_TTL_SECONDS,
        )
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SEARCH_SESSION_STORE_UNAVAILABLE",
            "검색 결과를 안전하게 보관할 수 없습니다.",
            retryable=True,
        ) from exc
    return build_envelope(response, request_id)


@router.get("/search/{search_session_id}", response_model=Envelope[SearchResponse])
async def get_search(
    search_session_id: uuid.UUID,
    store: StoreDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    try:
        record = await store.get(search_session_id)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SEARCH_SESSION_STORE_UNAVAILABLE",
            "검색 결과를 불러올 수 없습니다.",
            retryable=True,
        ) from exc
    if record is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "SEARCH_SESSION_NOT_FOUND",
            "검색 결과가 만료되었거나 존재하지 않습니다.",
        )
    return build_envelope(record.response, request_id)

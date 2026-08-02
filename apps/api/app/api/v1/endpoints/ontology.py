"""Published matching-ontology read and normalization endpoints.

The catalog is an application artifact, not a set of Python enums.  Loading it
through the shared ``meet_ai`` package gives the API, seed generator, matching
jobs, and Netlify extraction boundary one validated source of truth.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from meet_ai.ontology import Catalog, load_catalog

router = APIRouter()


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


class ResolveRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    locale: str = Field(default="ko-KR", min_length=2, max_length=20)
    context: str = Field(default="ANY", min_length=1, max_length=50)


class DeriveBandRequest(BaseModel):
    metric: Literal["alcohol_percentage", "price_krw"]
    value: Decimal = Field(ge=0)


@router.get("")
async def catalog_metadata() -> dict[str, object]:
    catalog = _catalog()
    return {
        "taxonomy_version": catalog.version,
        "status": catalog.metadata["status"],
        "default_locale": catalog.metadata["default_locale"],
        "concept_count": len(catalog.concepts),
    }


@router.get("/concepts")
async def list_concepts(
    concept_type: Annotated[str | None, Query(max_length=50)] = None,
    parent_code: Annotated[str | None, Query(max_length=100)] = None,
    assignable_only: bool = True,
) -> dict[str, object]:
    catalog = _catalog()
    items = [
        concept
        for concept in catalog.concepts
        if (concept_type is None or concept["concept_type"] == concept_type)
        and (parent_code is None or concept.get("parent") == parent_code)
        and (not assignable_only or concept.get("assignable", True))
    ]
    return {"taxonomy_version": catalog.version, "items": items}


@router.get("/concepts/{concept_code}")
async def get_concept(concept_code: str) -> dict[str, object]:
    try:
        concept = _catalog().get(concept_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ONTOLOGY_CODE_NOT_FOUND") from exc
    return {"taxonomy_version": _catalog().version, "concept": concept}


@router.post("/resolve")
async def resolve_synonym(request: ResolveRequest) -> dict[str, object]:
    catalog = _catalog()
    matches = catalog.resolve_synonym(
        request.text,
        locale=request.locale,
        context=request.context.upper(),
    )
    return {
        "taxonomy_version": catalog.version,
        "matches": [
            {
                "concept_code": match.concept_code,
                "priority": match.priority,
                "context": match.context,
                "locale": match.locale,
            }
            for match in matches
        ],
        "review_required": len(matches) != 1,
    }


@router.post("/derive-band")
async def derive_band(request: DeriveBandRequest) -> dict[str, str]:
    catalog = _catalog()
    try:
        concept_code = catalog.derive_band(request.metric, request.value)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="ONTOLOGY_VALUE_OUT_OF_RANGE"
        ) from exc
    return {"taxonomy_version": catalog.version, "concept_code": concept_code}

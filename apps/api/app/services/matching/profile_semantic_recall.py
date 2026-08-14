"""Privacy-minimized semantic recall for the recommendation engine.

Only canonical ontology codes and their public labels are embedded. Identifiers,
free-form profile context, and numeric trade constraints are deliberately excluded.
Semantic similarity expands the candidate pool; it never decides eligibility or rank.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from meet_ai.ontology import Catalog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching.ontology_support import get_catalog
from app.services.matching.semantic_search import SemanticScorer, SemanticStatus
from app.services.matching.types import GoalItem, ResolvedProfile, TaxonomyItem

PROFILE_SEMANTIC_RECALL_VERSION = "PROFILE_SEMANTIC_RECALL_V1"

_LEVEL_ORDER = {
    "REQUIRED": 0,
    "PREFERRED": 1,
    "ACCEPTABLE": 2,
}


@dataclass(frozen=True, slots=True)
class ProfileSemanticRecall:
    participation_scores: dict[uuid.UUID, float]
    status: SemanticStatus
    input_fingerprint: str
    model_version_id: uuid.UUID | None = None


def _concept_text(catalog: Catalog, code: str) -> str | None:
    """Return only catalog-owned text; arbitrary profile strings never pass through."""

    try:
        concept = catalog.get(code)
    except KeyError:
        return None
    return f"{code} {concept['label_ko']}"


def _taxonomy_lines(
    *, bucket_name: str, items: list[TaxonomyItem], catalog: Catalog
) -> list[str]:
    values: set[tuple[int, str, str]] = set()
    for item in items:
        level_order = _LEVEL_ORDER.get(item.level)
        concept_text = _concept_text(catalog, item.code)
        if level_order is None or concept_text is None:
            # EXCLUDED values belong to the hard filter, not positive semantic recall.
            continue
        values.add(
            (level_order, item.code, f"{bucket_name} {item.level} {concept_text}")
        )
    return [line for _, _, line in sorted(values)]


def _goal_lines(goals: list[GoalItem], catalog: Catalog) -> list[str]:
    values: set[tuple[int, int, str, str]] = set()
    for goal in goals:
        level_order = _LEVEL_ORDER.get(goal.requirement_level)
        concept_text = _concept_text(catalog, goal.code)
        if level_order is None or concept_text is None:
            continue
        priority = goal.priority if goal.priority is not None else 2_147_483_647
        values.add(
            (
                level_order,
                priority,
                goal.code,
                f"goal {goal.requirement_level} priority-{priority} {concept_text}",
            )
        )
    return [line for _, _, _, line in sorted(values)]


def build_profile_semantic_query(
    profile: ResolvedProfile, *, catalog: Catalog | None = None
) -> str:
    """Build a stable, allowlisted query without profile IDs or free-form values."""

    resolved_catalog = catalog or get_catalog()
    lines = [
        f"engine {PROFILE_SEMANTIC_RECALL_VERSION}",
        f"taxonomy {resolved_catalog.version}",
        f"audience {profile.user_type}",
    ]
    lines.extend(_goal_lines(profile.goals, resolved_catalog))

    buckets = (
        ("category", profile.categories),
        ("channel", profile.channels),
        ("region", profile.regions),
        ("taste", profile.taste),
        ("aroma", profile.aroma),
    )
    for bucket_name, items in buckets:
        lines.extend(
            _taxonomy_lines(
                bucket_name=bucket_name,
                items=items,
                catalog=resolved_catalog,
            )
        )
    for bucket_name in sorted(profile.extra):
        lines.extend(
            _taxonomy_lines(
                bucket_name=f"extra-{bucket_name}",
                items=profile.extra[bucket_name],
                catalog=resolved_catalog,
            )
        )

    # Metadata alone must not trigger an embedding provider request.
    return "\n".join(lines) if len(lines) > 3 else ""


def profile_semantic_fingerprint(query: str) -> str:
    canonical = json.dumps(
        {"query": query, "version": PROFILE_SEMANTIC_RECALL_VERSION},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def recall_profile_participations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    profile: ResolvedProfile,
    semantic_scorer: SemanticScorer,
) -> ProfileSemanticRecall:
    query = build_profile_semantic_query(profile)
    fingerprint = profile_semantic_fingerprint(query)
    if not query:
        return ProfileSemanticRecall({}, "DISABLED", fingerprint)

    prepared = await semantic_scorer.prepare(query=query)
    if prepared.status != "AVAILABLE":
        return ProfileSemanticRecall(
            {}, prepared.status, fingerprint, prepared.model_version_id
        )

    batch = await semantic_scorer.score(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        language="ko",
        prepared=prepared,
    )
    return ProfileSemanticRecall(
        batch.participation_scores,
        batch.status,
        fingerprint,
        batch.model_version_id,
    )

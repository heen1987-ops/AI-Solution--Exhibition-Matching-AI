"""Pure, DB-free construction of the two search-index document tiers.

Track GOAL (verbatim from the task brief): "Generate two document tiers per
exhibitor/product: a PUBLIC search document (name, brand, public intro,
public products, public interest codes, booth number, public homepage -
explicitly excluding contact info, non-public price, internal memos,
unapproved trade conditions, other-buyer info) and a VERIFIED_BUYER-only
document (approved MOQ, channels, region, OEM/PB/export, new-trade-available,
meeting-available)".

Why this module has no SQLAlchemy/DB imports
----------------------------------------------
1. Testability: every function here is exercised in
   ``apps/api/tests/test_indexing.py`` without a live database.
2. Reuse: ``apps/worker`` has no SQLAlchemy dependency at all (see
   ``apps/worker/pyproject.toml`` and ``document_parsing.py``'s own module
   docstring for the established precedent of keeping worker-side logic
   pure/protocol-based). Keeping the actual document-shape logic ORM-free
   here means a future worker-side re-implementation does not have to
   duplicate the shape rules - it can vendor or mirror this exact module.

Structural (not just conventional) privacy enforcement
----------------------------------------------------------
The forbidden fields (business contact info, non-public price, internal
memos, unapproved trade-condition detail, other-buyer info, raw storage
paths) are not merely "left out by discipline" - the input dataclasses below
simply have no field to carry them. ``build_public_document``/
``build_verified_buyer_document`` cannot leak what they were never given.
The caller (``app/services/indexing/service.py``) is still responsible for
only ever constructing these dataclasses from rows that have already passed
the project's approval gates (``master_approval_status``/``approval_status``/
``review_status`` == 'APPROVED', or ``document.published_content_version``
rows, which by construction only exist once an extraction has reached
``review_status='APPROVED_BY_OPERATOR'`` - see ``app/models/extraction.py``)
- this module is the second line of defense, not the first.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field

from app.services.extraction.visibility import forbidden_public_attribute_codes


@dataclass(frozen=True)
class PublicProductFact:
    """One already-approved product, as far as the PUBLIC tier may know it."""

    product_id: uuid.UUID
    product_name: str
    product_summary: str | None = None


@dataclass(frozen=True)
class ExhibitorPublicFacts:
    """Everything eligible for the PUBLIC search-document tier.

    Every field here must already be approval-gated by the caller before
    construction - see module docstring. In particular this dataclass has
    no field for: business contact info, wholesale/event pricing, internal
    memos, trade-condition detail, or any other buyer's data.
    """

    exhibitor_id: uuid.UUID
    company_name: str
    public_intro: str | None
    homepage_url: str | None
    booth_number: str | None
    brand_name: str | None = None
    products: tuple[PublicProductFact, ...] = ()
    interest_concept_codes: tuple[str, ...] = ()
    # attribute_code -> value, sourced only from document.published_content_version
    # rows visible at PUBLIC clearance (visibility == 'PUBLIC') that are not
    # superseded - see module docstring on why that already implies
    # review_status == 'APPROVED_BY_OPERATOR'.
    published_attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedBuyerFacts:
    """Everything eligible for the VERIFIED_BUYER-only search-document tier.

    Sourced only from approved ``exhibition.trade_condition`` rows
    (``approval_status == 'APPROVED'``) plus
    ``document.published_content_version`` rows visible at VERIFIED_BUYER
    clearance or looser (PUBLIC/REGISTERED_USER/VERIFIED_BUYER). Never
    includes a specific buyer's negotiated terms (those live in the
    ``interaction.meeting`` domain, out of this pipeline's scope entirely).
    """

    exhibitor_id: uuid.UUID
    min_order_quantity: int | None = None
    max_order_quantity: int | None = None
    regions: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    oem_status: str | None = None
    private_label_status: str | None = None
    export_status: str | None = None
    # Best-effort derived flag - "at least one approved trade condition is
    # still within its valid_from/valid_until window (or has no expiry)".
    # This is a pragmatic stand-in for "new-trade-available" since no
    # dedicated field exists on exhibition.trade_condition for that exact
    # concept; documented here rather than silently assumed (Blocker Score
    # < 7 - reversible, no privacy/security dimension).
    new_trade_available: bool = False
    # Whether the exhibitor has open meeting availability. This pipeline
    # does not own the interaction.availability_slot domain
    # (app/models/meeting.py, a different track) - defaults to False and is
    # meant to be supplied by the caller once that integration exists.
    # Documented as a known limitation, not silently coerced to True/False
    # without basis (AGENTS.md "unknown stays unknown").
    meeting_available: bool = False
    published_attributes: dict[str, object] = field(default_factory=dict)


def _clean_text(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


class ForbiddenPublicAttributeError(ValueError):
    """A tier-forbidden ``attribute_code`` reached the PUBLIC document builder.

    Raised rather than silently dropped, matching ``build_embedding_input``'s
    fail-loud convention in ``app/services/object_embeddings.py``: a
    trade-condition or price attribute arriving here means an upstream
    visibility gate (``document.published_content_version.visibility`` /
    ``app/services/extraction/visibility.py``) has already failed, and
    swallowing it would hide that failure until it shows up on the anonymous
    public/kiosk surface.
    """

    def __init__(self, attribute_code: str) -> None:
        self.attribute_code = attribute_code
        super().__init__(
            f"attribute_code {attribute_code!r} is not permitted in a PUBLIC-tier "
            "search document"
        )


def _assert_public_attributes_allowed(published_attributes: dict[str, object]) -> None:
    forbidden = forbidden_public_attribute_codes()
    for attribute_code in published_attributes:
        if attribute_code in forbidden:
            raise ForbiddenPublicAttributeError(attribute_code)


def build_public_document(facts: ExhibitorPublicFacts) -> dict:
    """Build the PUBLIC-tier ``content_json`` payload.

    Field set matches the GOAL list exactly: name, brand, public intro,
    public products, public interest codes, booth number, public homepage.

    ``published_attributes`` is an untyped ``attribute_code -> value`` map, so
    unlike every other field on :class:`ExhibitorPublicFacts` it is NOT
    structurally incapable of carrying trade terms or pricing. It is therefore
    checked against a per-tier denylist here and
    :class:`ForbiddenPublicAttributeError` is raised on any hit.
    """

    _assert_public_attributes_allowed(facts.published_attributes)

    return {
        "tier": "PUBLIC",
        "exhibitor_id": str(facts.exhibitor_id),
        "name": facts.company_name,
        "brand": facts.brand_name or facts.company_name,
        "public_intro": facts.public_intro,
        "public_homepage": facts.homepage_url,
        "booth_number": facts.booth_number,
        "public_products": [
            {
                "product_id": str(p.product_id),
                "product_name": p.product_name,
                "product_summary": p.product_summary,
            }
            for p in facts.products
        ],
        "public_interest_codes": list(dict.fromkeys(facts.interest_concept_codes)),
        "published_attributes": dict(facts.published_attributes),
    }


def build_verified_buyer_document(facts: VerifiedBuyerFacts) -> dict:
    """Build the VERIFIED_BUYER-tier ``content_json`` payload.

    Field set matches the GOAL list exactly: approved MOQ, channels, region,
    OEM/PB/export, new-trade-available, meeting-available.
    """

    return {
        "tier": "VERIFIED_BUYER",
        "exhibitor_id": str(facts.exhibitor_id),
        "min_order_quantity": facts.min_order_quantity,
        "max_order_quantity": facts.max_order_quantity,
        "regions": list(dict.fromkeys(facts.regions)),
        "channels": list(dict.fromkeys(facts.channels)),
        "oem_status": facts.oem_status,
        "private_label_status": facts.private_label_status,
        "export_status": facts.export_status,
        "new_trade_available": facts.new_trade_available,
        "meeting_available": facts.meeting_available,
        "published_attributes": dict(facts.published_attributes),
    }


def build_public_search_text(facts: ExhibitorPublicFacts) -> str:
    """Flattened keyword/FTS text for the PUBLIC document.

    Computed once at index-generation time rather than per-query (unlike
    ``app/services/catalog_search.py``'s live-query approach) - that is the
    whole point of materializing an index.
    """

    product_text = " ".join(p.product_name for p in facts.products)
    return _clean_text(
        facts.company_name,
        facts.brand_name,
        facts.public_intro,
        product_text,
        " ".join(facts.interest_concept_codes),
    )


def build_verified_buyer_search_text(facts: VerifiedBuyerFacts) -> str:
    return _clean_text(
        " ".join(facts.regions),
        " ".join(facts.channels),
        facts.oem_status,
        facts.private_label_status,
        facts.export_status,
    )


def content_hash(payload: dict) -> str:
    """``"sha256:" + hex`` of the canonical JSON payload.

    Same plain-hash-for-change-detection convention used throughout this
    repo (``app/services/ingestion.py``'s ``hash_payload``,
    ``document-structuring.md`` §6 ``evidence_hash``) - not a security
    control, purely for idempotent-regeneration/change-detection.
    """

    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

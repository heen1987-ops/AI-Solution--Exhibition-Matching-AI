"""Verified-buyer trade profile domain model (profile schema).

Track: WAVE2C BACKEND-BUYER-PROFILE. Owned paths: see AGENTS.md/this track's worker prompt.

Prior-art review (mandatory per this track's worker prompt) and why this is a new table
-------------------------------------------------------------------------------------------
``app/models/profile.py`` already defines ``profile.buyer_need`` (class ``BuyerNeed``), a 1:1
extension of the *per-event* ``UserProfile`` that captures matching criteria for the current
event visit (target price, monthly order volume, distribution channels, decision timeline,
two plain booleans ``business_email_verified``/``company_verified``). That table is correct and
is left untouched here.

This module implements a different concept the track prompt calls a "verified-buyer trade
profile": a durable, cross-event buyer identity with a multi-state operator verification
workflow (``UNVERIFIED -> PENDING -> VERIFIED|REJECTED``, plus ``LIMITED``/``SUSPENDED``/
``EXPIRED``) that gates access to full matching/meeting features. ``BuyerNeed.company_verified``
is a single boolean with no workflow, no operator attribution, and it lives on the per-event
``UserProfile`` (a buyer attending two events gets two independent ``UserProfile``/``BuyerNeed``
rows today). A durable trade-verification identity does not fit that shape, so a new table is
the right call rather than overloading ``BuyerNeed``. ``BuyerNeed`` is not modified or reused.

Design decision recorded here (Blocker Score < 7, safest-reversible-default rule per this
track's worker prompt): this profile is scoped to ``(tenant_id, user_id)`` — one row per
authenticated user per tenant, independent of ``event_id`` — because verification is a KYB-like
identity fact ("is this a real trade buyer") rather than a per-visit preference. It only applies
to ``profile.user_account`` (``PHONE_VERIFIED``/``ACCOUNT_AUTHENTICATED``) subjects; anonymous
kiosk/guest sessions cannot hold one (no ``guest_session_id`` column, deliberately, matching the
"no kiosk long-term personalization" scope exclusion in PROJECT_SCOPE.md). Reversible: this is a
brand-new table with no readers yet; if a future contract review decides verification should
instead be per-event, migrating is a straightforward follow-up migration + backfill.

Ontology-code normalization
----------------------------
``industry_codes``/``interest_codes``/``channel_codes``/``preferred_region_codes``/
``cooperation_codes`` are ontology concept codes (task spec: "ontology concept codes only -
validate against the catalog"). Every other ontology-code-bearing column in this codebase
(``profile.profile_attribute``, ``profile.inferred_preference``,
``interaction.availability_slot``, ``interaction.meeting``, ``interaction.meeting_outcome``,
``interaction.follow_up_action``) normalizes such codes into a child row carrying a composite
``(taxonomy_version_id, concept_id)`` FK into ``ontology.concept_revision`` plus a denormalized
``attribute_code`` cross-checked against ``ontology.concept.concept_code`` (see
``app/models/profile.py``'s ``ProfileAttribute`` docstring for the rationale). ``BuyerProfileCode``
follows the same pattern rather than storing bare code strings in a JSONB array, so this table
gets the same DB-level integrity guarantee as every other ontology-referencing table in the repo.

``buyer_type`` is a fixed application-level classification enum given verbatim by the task spec
(``DISTRIBUTOR``/``RETAILER``/... ``OTHER``) — it is *not* one of the catalog's ``BUYER_TYPE``
concept codes (``BUYER.DEPARTMENT_STORE`` etc., a different axis used for consumer/venue channel
matching), so it is a plain ``CHECK``-constrained column, not an ontology reference.

``order_scale_code`` and ``decision_timeline`` are free-form short codes, listed separately from
the "validate against the catalog" fields in the task spec. This mirrors
``BuyerNeed.decision_timeline``/``BuyerNeed.organization_type`` in ``app/models/profile.py``,
which are also plain un-constrained strings with a TODO to formalize once a dedicated code
namespace exists — same treatment here, same reasoning.

Optimistic concurrency and the operator-only verification path
-----------------------------------------------------------------
``version`` is a plain optimistic-concurrency counter, incremented on every successful mutation
(mirrors ``row_version`` in ``app/models/meeting.py``/``app/models/profile.py``, exposed to
clients under the field name the task spec asks for: ``version``). The buyer-facing router
(``app/api/v1/routers/buyer_profile.py``) never writes ``verification_status`` — the only writer
is ``app/services/buyer_profile/verification.py``'s ``set_verification_status`` stub, meant to be
called from the ADMIN-BUYER track's own operator-authenticated router.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_PROFILE, Base
from app.models.common import new_uuid7

#: Task spec's fixed buyer classification enum (verbatim, not an ontology concept axis - see
#: module docstring "Ontology-code normalization").
BUYER_TYPES: tuple[str, ...] = (
    "DISTRIBUTOR",
    "RETAILER",
    "ONLINE_COMMERCE",
    "IMPORTER",
    "EXPORTER",
    "MANUFACTURER",
    "PUBLIC_BUYER",
    "CORPORATE_BUYER",
    "INVESTOR",
    "OTHER",
)

#: Task spec's verification lifecycle. Buyers can never set this themselves (module docstring
#: "Optimistic concurrency and the operator-only verification path").
VERIFICATION_STATUSES: tuple[str, ...] = (
    "UNVERIFIED",
    "PENDING",
    "VERIFIED",
    "LIMITED",
    "REJECTED",
    "SUSPENDED",
    "EXPIRED",
)

#: Task spec: "only VERIFIED (and LIMITED per policy) can use full matching/meetings." /
#: "UNVERIFIED blocked from meeting-eligible actions." Single source of truth for
#: ``app/services/buyer_profile/eligibility.py``'s ``is_meeting_eligible``.
MEETING_ELIGIBLE_VERIFICATION_STATUSES: frozenset[str] = frozenset({"VERIFIED", "LIMITED"})

#: ``BuyerProfileCode.code_group`` - one group per ontology-validated list field on
#: ``BuyerProfile`` (module docstring "Ontology-code normalization").
BUYER_PROFILE_CODE_GROUPS: tuple[str, ...] = (
    "INDUSTRY",
    "INTEREST",
    "CHANNEL",
    "PREFERRED_REGION",
    "COOPERATION",
)


def _sql_in_list(values: tuple[str, ...]) -> str:
    """CHECK 제약의 'col IN (...)' 리터럴 목록 문자열을 상수 튜플에서 생성한다.

    (Same helper as ``app/models/meeting.py``'s ``_sql_in_list`` - kept local rather than
    imported to avoid a cross-domain-model import; see that module's docstring "다른 도메인
    모델과의 관계" for why domain model files in this codebase avoid importing each other.)
    """

    return ", ".join(f"'{value}'" for value in values)


class BuyerProfile(Base):
    """profile.buyer_profile - durable per-(tenant, user) verified-buyer trade profile.

    See module docstring for the full design rationale and how this differs from
    ``profile.buyer_need``.
    """

    __tablename__ = "buyer_profile"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", name="uq_buyer_profile_tenant_user"
        ),
        CheckConstraint(
            f"buyer_type IN ({_sql_in_list(BUYER_TYPES)})", name="buyer_type_allowed"
        ),
        CheckConstraint(
            f"verification_status IN ({_sql_in_list(VERIFICATION_STATUSES)})",
            name="verification_status_allowed",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        {"schema": SCHEMA_PROFILE},
    )

    buyer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )

    buyer_type: Mapped[str] = mapped_column(String(30), nullable=False, default="OTHER")
    order_scale_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    decision_timeline: Mapped[str | None] = mapped_column(String(30), nullable=True)

    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNVERIFIED"
    )
    # Operator-only mutation trail. Never set by the buyer-facing router (module docstring).
    verification_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verification_reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=True,
    )
    verification_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Optimistic-concurrency counter exposed to clients as "version" (task spec wording).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    codes: Mapped[list[BuyerProfileCode]] = relationship(
        back_populates="buyer_profile", cascade="all, delete-orphan"
    )


class BuyerProfileCode(Base):
    """profile.buyer_profile_code - normalized ontology-code membership rows for a buyer profile.

    One row per (buyer_profile, code_group, concept). See module docstring "Ontology-code
    normalization" for why this mirrors ``profile.profile_attribute`` instead of a JSONB array.
    """

    __tablename__ = "buyer_profile_code"
    __table_args__ = (
        UniqueConstraint(
            "buyer_profile_id",
            "code_group",
            "concept_id",
            name="uq_buyer_profile_code_group_concept",
        ),
        CheckConstraint(
            f"code_group IN ({_sql_in_list(BUYER_PROFILE_CODE_GROUPS)})",
            name="code_group_allowed",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_buyer_profile_code_ontology_revision",
        ),
        ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_buyer_profile_code_concept_code",
        ),
        Index(
            "ix_buyer_profile_code_lookup", "buyer_profile_id", "code_group"
        ),
        {"schema": SCHEMA_PROFILE},
    )

    buyer_profile_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    buyer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.buyer_profile.buyer_profile_id"),
        nullable=False,
    )
    code_group: Mapped[str] = mapped_column(String(20), nullable=False)

    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Denormalized code value for cheap API responses without joining ontology tables every
    # read (same rationale as ProfileAttribute.attribute_code in app/models/profile.py).
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    buyer_profile: Mapped[BuyerProfile] = relationship(back_populates="codes")

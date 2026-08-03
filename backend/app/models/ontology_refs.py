"""Minimal metadata bridge to the immutable ontology SQL contract.

Ontology DDL is owned by ``db/migrations/0001_ontology.sql`` and intentionally
excluded from Alembic autogenerate. These key definitions let other ORM models
resolve cross-schema foreign keys without duplicating the ontology contract.
"""

from sqlalchemy import Boolean, Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import SCHEMA_ONTOLOGY, Base

taxonomy_version = Table(
    "taxonomy_version",
    Base.metadata,
    Column("taxonomy_version_id", UUID(as_uuid=True), primary_key=True),
    schema=SCHEMA_ONTOLOGY,
    info={"migration_managed_externally": True},
)

concept = Table(
    "concept",
    Base.metadata,
    Column("concept_id", UUID(as_uuid=True), primary_key=True),
    Column("concept_code", String(100), nullable=False),
    UniqueConstraint("concept_id", "concept_code", name="uq_ontology_concept_id_code"),
    schema=SCHEMA_ONTOLOGY,
    info={"migration_managed_externally": True},
)

concept_revision = Table(
    "concept_revision",
    Base.metadata,
    Column(
        "taxonomy_version_id",
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_ONTOLOGY}.taxonomy_version.taxonomy_version_id"),
        primary_key=True,
    ),
    Column(
        "concept_id",
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_ONTOLOGY}.concept.concept_id"),
        primary_key=True,
    ),
    Column("assignable", Boolean, nullable=False),
    Column("status", String(20), nullable=False),
    Column("validation_json", JSONB, nullable=False),
    schema=SCHEMA_ONTOLOGY,
    info={"migration_managed_externally": True},
)

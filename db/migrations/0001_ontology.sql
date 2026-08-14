BEGIN;

CREATE SCHEMA IF NOT EXISTS ontology;

CREATE TABLE ontology.taxonomy_version (
    taxonomy_version_id UUID PRIMARY KEY,
    tenant_id UUID NULL,
    semantic_version VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,
    default_locale VARCHAR(20) NOT NULL DEFAULT 'ko-KR',
    base_version_id UUID NULL REFERENCES ontology.taxonomy_version(taxonomy_version_id),
    checksum BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID NULL,
    published_at TIMESTAMPTZ NULL,
    published_by UUID NULL,
    retired_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_ontology_taxonomy_version_tenant_semver
        UNIQUE NULLS NOT DISTINCT (tenant_id, semantic_version),
    CONSTRAINT ck_ontology_taxonomy_version_status
        CHECK (status IN ('DRAFT', 'REVIEW', 'PUBLISHED', 'RETIRED')),
    CONSTRAINT ck_ontology_taxonomy_version_publish_state
        CHECK (
            (status IN ('DRAFT', 'REVIEW') AND published_at IS NULL)
            OR (status IN ('PUBLISHED', 'RETIRED') AND published_at IS NOT NULL)
        )
);

CREATE TABLE ontology.concept (
    concept_id UUID PRIMARY KEY,
    concept_code VARCHAR(100) NOT NULL,
    concept_type VARCHAR(50) NOT NULL,
    data_type VARCHAR(20) NOT NULL DEFAULT 'CODE',
    unit_code VARCHAR(30) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deprecated_at TIMESTAMPTZ NULL,
    replacement_concept_id UUID NULL REFERENCES ontology.concept(concept_id),
    CONSTRAINT uq_ontology_concept_code UNIQUE (concept_code),
    CONSTRAINT ck_ontology_concept_code
        CHECK (concept_code ~ '^[A-Z][A-Z0-9_]*(\.[A-Z][A-Z0-9_]*)+$'),
    CONSTRAINT ck_ontology_concept_data_type
        CHECK (data_type IN ('CODE', 'NUMBER', 'BOOLEAN', 'TEXT')),
    CONSTRAINT ck_ontology_concept_not_self_replacement
        CHECK (replacement_concept_id IS NULL OR replacement_concept_id <> concept_id)
);

CREATE TABLE ontology.concept_revision (
    taxonomy_version_id UUID NOT NULL REFERENCES ontology.taxonomy_version(taxonomy_version_id),
    concept_id UUID NOT NULL REFERENCES ontology.concept(concept_id),
    parent_concept_id UUID NULL,
    assignable BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    sort_order INTEGER NOT NULL DEFAULT 0,
    validation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (taxonomy_version_id, concept_id),
    CONSTRAINT fk_ontology_revision_parent_same_version
        FOREIGN KEY (taxonomy_version_id, parent_concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_ontology_revision_status
        CHECK (status IN ('ACTIVE', 'DEPRECATED', 'DISABLED')),
    CONSTRAINT ck_ontology_revision_not_self_parent
        CHECK (parent_concept_id IS NULL OR parent_concept_id <> concept_id),
    CONSTRAINT ck_ontology_revision_validation_object
        CHECK (jsonb_typeof(validation_json) = 'object')
);

CREATE TABLE ontology.concept_label (
    taxonomy_version_id UUID NOT NULL,
    concept_id UUID NOT NULL,
    locale VARCHAR(20) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    short_name VARCHAR(100) NULL,
    description VARCHAR(1000) NULL,
    search_keywords TEXT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (taxonomy_version_id, concept_id, locale),
    CONSTRAINT fk_ontology_label_revision
        FOREIGN KEY (taxonomy_version_id, concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_ontology_label_locale CHECK (locale ~ '^[a-z]{2,3}(-[A-Z]{2})?$')
);

CREATE TABLE ontology.concept_synonym (
    synonym_id UUID PRIMARY KEY,
    taxonomy_version_id UUID NOT NULL,
    concept_id UUID NOT NULL,
    locale VARCHAR(20) NOT NULL,
    synonym_text VARCHAR(300) NOT NULL,
    normalized_text VARCHAR(300) NOT NULL,
    context_type VARCHAR(30) NOT NULL DEFAULT 'ANY',
    match_type VARCHAR(20) NOT NULL DEFAULT 'PHRASE',
    priority INTEGER NOT NULL DEFAULT 100,
    approval_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    source_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ NULL,
    approved_by UUID NULL,
    CONSTRAINT fk_ontology_synonym_revision
        FOREIGN KEY (taxonomy_version_id, concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_ontology_synonym_target
        UNIQUE (taxonomy_version_id, locale, context_type, normalized_text, concept_id),
    CONSTRAINT ck_ontology_synonym_match_type
        CHECK (match_type IN ('EXACT', 'TOKEN', 'PHRASE')),
    CONSTRAINT ck_ontology_synonym_approval_status
        CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT ck_ontology_synonym_priority CHECK (priority >= 0)
);

CREATE INDEX ix_ontology_synonym_lookup
    ON ontology.concept_synonym (taxonomy_version_id, locale, context_type, normalized_text)
    WHERE approval_status = 'APPROVED';

CREATE TABLE ontology.concept_relation (
    relation_id UUID PRIMARY KEY,
    taxonomy_version_id UUID NOT NULL,
    source_concept_id UUID NOT NULL,
    relation_type VARCHAR(30) NOT NULL,
    target_concept_id UUID NOT NULL,
    semantic_weight NUMERIC(5,4) NOT NULL DEFAULT 1,
    rule_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_ontology_relation_source
        FOREIGN KEY (taxonomy_version_id, source_concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id),
    CONSTRAINT fk_ontology_relation_target
        FOREIGN KEY (taxonomy_version_id, target_concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id),
    CONSTRAINT uq_ontology_relation
        UNIQUE (taxonomy_version_id, source_concept_id, relation_type, target_concept_id),
    CONSTRAINT ck_ontology_relation_type
        CHECK (relation_type IN (
            'IS_A', 'RELATED_TO', 'MATCHES_GOAL',
            'SIMILAR_TO', 'COMPLEMENTS', 'CONFLICTS_WITH'
        )),
    CONSTRAINT ck_ontology_relation_weight CHECK (semantic_weight BETWEEN 0 AND 1),
    CONSTRAINT ck_ontology_relation_status CHECK (status IN ('ACTIVE', 'DISABLED')),
    CONSTRAINT ck_ontology_relation_rule_object CHECK (jsonb_typeof(rule_json) = 'object')
);

CREATE INDEX ix_ontology_relation_traversal
    ON ontology.concept_relation (taxonomy_version_id, source_concept_id, relation_type)
    WHERE status = 'ACTIVE';

CREATE TABLE ontology.external_mapping (
    mapping_id UUID PRIMARY KEY,
    taxonomy_version_id UUID NOT NULL,
    source_system_id UUID NOT NULL,
    source_namespace VARCHAR(100) NOT NULL,
    source_code VARCHAR(300) NOT NULL,
    source_label VARCHAR(500) NULL,
    target_concept_id UUID NOT NULL,
    mapping_type VARCHAR(20) NOT NULL,
    confidence NUMERIC(4,3) NOT NULL,
    approval_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    valid_from TIMESTAMPTZ NULL,
    valid_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ NULL,
    approved_by UUID NULL,
    CONSTRAINT fk_ontology_external_mapping_revision
        FOREIGN KEY (taxonomy_version_id, target_concept_id)
        REFERENCES ontology.concept_revision(taxonomy_version_id, concept_id),
    CONSTRAINT uq_ontology_external_mapping_source
        UNIQUE (taxonomy_version_id, source_system_id, source_namespace, source_code),
    CONSTRAINT ck_ontology_external_mapping_type
        CHECK (mapping_type IN ('EXACT', 'BROAD', 'NARROW', 'RELATED')),
    CONSTRAINT ck_ontology_external_mapping_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_ontology_external_mapping_approval
        CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT ck_ontology_external_mapping_period
        CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from)
);

CREATE TABLE ontology.unknown_term_queue (
    unknown_term_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    event_id UUID NOT NULL,
    taxonomy_version_id UUID NOT NULL REFERENCES ontology.taxonomy_version(taxonomy_version_id),
    locale VARCHAR(20) NOT NULL,
    context_type VARCHAR(30) NOT NULL,
    normalized_text VARCHAR(300) NOT NULL,
    sample_hash BYTEA NOT NULL,
    occurrence_count BIGINT NOT NULL DEFAULT 1,
    suggested_concept_id UUID NULL REFERENCES ontology.concept(concept_id),
    confidence NUMERIC(4,3) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ NULL,
    reviewed_by UUID NULL,
    resolution_note VARCHAR(1000) NULL,
    CONSTRAINT uq_ontology_unknown_term_aggregate
        UNIQUE (tenant_id, event_id, taxonomy_version_id, locale, context_type, normalized_text),
    CONSTRAINT ck_ontology_unknown_term_count CHECK (occurrence_count > 0),
    CONSTRAINT ck_ontology_unknown_term_confidence
        CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_ontology_unknown_term_status
        CHECK (status IN ('OPEN', 'MAPPED', 'IGNORED', 'REJECTED'))
);

CREATE INDEX ix_ontology_unknown_term_review
    ON ontology.unknown_term_queue (tenant_id, event_id, status, occurrence_count DESC, last_seen_at DESC)
    WHERE status = 'OPEN';

CREATE OR REPLACE FUNCTION ontology.reject_published_child_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        version_id := OLD.taxonomy_version_id;
    ELSE
        version_id := NEW.taxonomy_version_id;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM ontology.taxonomy_version
        WHERE taxonomy_version_id = version_id
          AND status IN ('PUBLISHED', 'RETIRED')
    ) THEN
        RAISE EXCEPTION 'published ontology version % is immutable', version_id
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_ontology_revision_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ontology.concept_revision
FOR EACH ROW EXECUTE FUNCTION ontology.reject_published_child_mutation();

CREATE TRIGGER trg_ontology_label_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ontology.concept_label
FOR EACH ROW EXECUTE FUNCTION ontology.reject_published_child_mutation();

CREATE TRIGGER trg_ontology_synonym_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ontology.concept_synonym
FOR EACH ROW EXECUTE FUNCTION ontology.reject_published_child_mutation();

CREATE TRIGGER trg_ontology_relation_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ontology.concept_relation
FOR EACH ROW EXECUTE FUNCTION ontology.reject_published_child_mutation();

CREATE TRIGGER trg_ontology_mapping_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ontology.external_mapping
FOR EACH ROW EXECUTE FUNCTION ontology.reject_published_child_mutation();

COMMENT ON TABLE ontology.concept IS
    'Stable concept identity and immutable code; version-specific structure lives in concept_revision.';
COMMENT ON TABLE ontology.unknown_term_queue IS
    'Review queue stores normalized/redacted terms and hashes, not unrestricted raw user text.';

COMMIT;

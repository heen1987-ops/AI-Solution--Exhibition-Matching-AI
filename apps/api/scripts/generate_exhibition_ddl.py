"""Generate the reviewed exhibition-domain PostgreSQL contract from metadata."""

from __future__ import annotations

from pathlib import Path

from app.db.base import SCHEMA_EXHIBITION, Base
from app.models import (  # noqa: F401
    consent,
    core,
    exhibitor,
    identity,
    ontology_refs,
    profile,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "db" / "migrations" / "0002_exhibition.sql"
PREEXISTING_TABLES = {"event", "event_day", "event_zone"}


def _statement(ddl) -> str:
    compiled = str(ddl.compile(dialect=postgresql.dialect())).strip()
    return "\n".join(line.rstrip() for line in compiled.splitlines()) + ";"


def _trigger_contract() -> str:
    return r"""
ALTER TABLE profile.user_role
    ADD CONSTRAINT fk_user_role_exhibitor_boundary
    FOREIGN KEY (tenant_id, exhibitor_id)
    REFERENCES exhibition.exhibitor (tenant_id, exhibitor_id);

CREATE OR REPLACE FUNCTION exhibition.validate_event_product_owner()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM exhibition.exhibitor_participation participation
        JOIN exhibition.product product
          ON product.exhibitor_id = participation.exhibitor_id
        WHERE participation.participation_id = NEW.participation_id
          AND participation.tenant_id = NEW.tenant_id
          AND participation.event_id = NEW.event_id
          AND product.product_id = NEW.product_id
    ) THEN
        RAISE EXCEPTION
            'event product %, participation %, and product % do not share an exhibitor/event boundary',
            NEW.event_product_id, NEW.participation_id, NEW.product_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_event_product_owner_boundary
BEFORE INSERT OR UPDATE OF tenant_id, event_id, participation_id, product_id
ON exhibition.event_product
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_event_product_owner();

CREATE OR REPLACE FUNCTION exhibition.validate_trade_condition_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.event_product_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.event_product event_product
        WHERE event_product.event_product_id = NEW.event_product_id
          AND event_product.participation_id = NEW.participation_id
    ) THEN
        RAISE EXCEPTION
            'trade condition % references an event product outside participation %',
            NEW.trade_condition_id, NEW.participation_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_trade_condition_scope
BEFORE INSERT OR UPDATE OF participation_id, event_product_id
ON exhibition.trade_condition
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_trade_condition_scope();

CREATE OR REPLACE FUNCTION exhibition.validate_supply_capability_owner()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.product_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.product product
        WHERE product.product_id = NEW.product_id
          AND product.exhibitor_id = NEW.exhibitor_id
    ) THEN
        RAISE EXCEPTION
            'supply capability % product does not belong to exhibitor %',
            NEW.supply_capability_id, NEW.exhibitor_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_supply_capability_owner
BEFORE INSERT OR UPDATE OF exhibitor_id, product_id
ON exhibition.supply_capability
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_supply_capability_owner();

CREATE OR REPLACE FUNCTION exhibition.validate_product_profile_category_code()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.category_code IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM exhibition.product product
        JOIN ontology.concept concept
          ON concept.concept_id = product.category_concept_id
        WHERE product.product_id = NEW.product_id
          AND concept.concept_code = NEW.category_code
    ) THEN
        RAISE EXCEPTION
            'product profile % category code does not match product taxonomy',
            NEW.product_profile_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_product_profile_category_code
BEFORE INSERT OR UPDATE OF product_id, category_code
ON exhibition.product_profile
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_product_profile_category_code();

CREATE OR REPLACE FUNCTION exhibition.validate_supply_attribute_target()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.object_type = 'EXHIBITOR' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.exhibitor WHERE exhibitor_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown exhibitor attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    ELSIF NEW.object_type = 'PRODUCT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.product WHERE product_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown product attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    ELSIF NEW.object_type = 'TRADE_CONDITION' THEN
        IF NOT EXISTS (
            SELECT 1 FROM exhibition.trade_condition WHERE trade_condition_id = NEW.object_id
        ) THEN
            RAISE EXCEPTION 'unknown trade-condition attribute target %', NEW.object_id
                USING ERRCODE = '23503';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_supply_attribute_target
BEFORE INSERT OR UPDATE OF object_type, object_id
ON exhibition.profile_attribute
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_supply_attribute_target();

CREATE OR REPLACE FUNCTION exhibition.validate_user_role_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    selected_role_code VARCHAR(30);
BEGIN
    SELECT role_code INTO selected_role_code
    FROM profile.role
    WHERE role_id = NEW.role_id;

    IF selected_role_code = 'EXHIBITOR' AND NEW.exhibitor_id IS NULL THEN
        RAISE EXCEPTION 'EXHIBITOR role requires exhibitor_id' USING ERRCODE = '23514';
    END IF;
    IF selected_role_code = 'OPERATOR' AND NEW.event_id IS NULL THEN
        RAISE EXCEPTION 'OPERATOR role requires event_id' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_user_role_scope
BEFORE INSERT OR UPDATE OF role_id, event_id, exhibitor_id
ON profile.user_role
FOR EACH ROW EXECUTE FUNCTION exhibition.validate_user_role_scope();
""".strip()


def render() -> str:
    tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.schema == SCHEMA_EXHIBITION and table.name not in PREEXISTING_TABLES
    ]

    statements = ["BEGIN;"]
    for table in tables:
        statements.append(_statement(CreateTable(table)))
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(_statement(CreateIndex(index)))
    statements.extend([_trigger_contract(), "COMMIT;"])
    return "\n\n".join(statements) + "\n"


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

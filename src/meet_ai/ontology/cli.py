from __future__ import annotations

import argparse
import json
from decimal import Decimal

from .catalog import CatalogValidationError, emit_postgres_seed, load_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and inspect the Meet AI ontology"
    )
    parser.add_argument("--catalog", help="Optional catalog JSON path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="Validate the complete catalog")

    resolve = subparsers.add_parser("resolve", help="Resolve a curated synonym")
    resolve.add_argument("text")
    resolve.add_argument("--locale", default="ko-KR")
    resolve.add_argument("--context", default="ANY")

    derive = subparsers.add_parser("derive", help="Derive a numeric band")
    derive.add_argument("metric")
    derive.add_argument("value", type=Decimal)

    subparsers.add_parser("emit-sql", help="Emit deterministic PostgreSQL seed SQL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
    except (CatalogValidationError, OSError, json.JSONDecodeError) as exc:
        print(str(exc))
        return 1

    if args.command == "validate":
        print(
            f"OK ontology {catalog.version}: "
            f"{len(catalog.concepts)} concepts, "
            f"{len(catalog.synonyms)} synonyms, "
            f"{len(catalog.relations)} relations"
        )
        return 0
    if args.command == "resolve":
        matches = catalog.resolve_synonym(
            args.text, locale=args.locale, context=args.context
        )
        print(
            json.dumps(
                [item.__dict__ for item in matches], ensure_ascii=False, indent=2
            )
        )
        return 0 if matches else 2
    if args.command == "derive":
        print(catalog.derive_band(args.metric, args.value))
        return 0
    if args.command == "emit-sql":
        print(emit_postgres_seed(catalog), end="")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

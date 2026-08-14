"""Stage or publish approved catalog embeddings for one event."""

from __future__ import annotations

import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.matching.semantic_search import get_query_embedding_provider
from app.services.object_embeddings import backfill_catalog_embeddings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=uuid.UUID, required=True)
    parser.add_argument(
        "--language",
        default="und",
        choices=("und", "ko", "en", "ja", "zh"),
        help="source catalog language; use und for the current non-localized fields",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="atomically switch active pointers after the backfill validates",
    )
    return parser.parse_args()


async def _run() -> None:
    args = _arguments()
    settings = get_settings()
    provider = get_query_embedding_provider(settings)
    if provider is None:
        raise SystemExit(
            "semantic search must be enabled with its dedicated provider key"
        )

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        result = await backfill_catalog_embeddings(
            db,
            provider=provider,
            model_version_id=settings.SEARCH_EMBEDDING_MODEL_VERSION_ID,
            event_id=args.event_id,
            language=args.language,
            activate=args.activate,
        )
    print(
        "catalog embedding backfill complete: "
        f"discovered={result.discovered} embedded={result.embedded} "
        f"reused={result.reused} activated={result.activated}"
    )


if __name__ == "__main__":
    asyncio.run(_run())

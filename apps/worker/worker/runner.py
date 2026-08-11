"""Worker process entry point: an asyncio poll loop over the registered jobs.

Modelled on `apps/api/scripts/backfill_catalog_embeddings.py`'s own
`get_settings -> get_sessionmaker -> async with session_factory()` pattern (the only
existing precedent in this repo for a standalone async DB-touching script), rather than
inventing a bespoke job-registry runtime. Replaces the five never-implemented
`JobRegistry` Protocol stubs each job module still ships (`register_*_job(registry)`,
kept only as documentation of the job's public name) with one real loop.

Importing this module must never open a DB connection - `get_settings()`/
`get_sessionmaker()` are only called inside `run_forever()`, and `app.db.session`'s own
module docstring documents the same lazy-initialization discipline this relies on.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import get_sessionmaker

from worker.jobs.notification_outbox import drain_notification_outbox

logger = logging.getLogger("worker.runner")

#: Seconds between drain passes when a pass finds nothing to do.
DEFAULT_POLL_INTERVAL_SECONDS = 5.0


class _ShutdownRequested:
    """Cooperative shutdown flag flipped by a SIGTERM/SIGINT handler.

    A plain flag (checked between iterations), not `loop.stop()` - a shutdown request must
    never interrupt a batch already being dispatched, only stop the *next* one from starting.
    """

    def __init__(self) -> None:
        self.flag = False

    def request(self, *_args: object) -> None:
        self.flag = True


def _install_signal_handlers(shutdown: _ShutdownRequested) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, shutdown.request)
        except (ValueError, OSError):
            # Not the main thread, or the platform does not expose this signal (SIGTERM is
            # unavailable in some Windows configurations) - best effort, never fatal.
            continue


async def run_forever(
    *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
) -> None:
    """Poll loop: one notification-outbox drain pass per iteration.

    Never lets one iteration's exception kill the process - a bad batch is logged and the
    loop continues on the next tick, the same "must not crash the worker" discipline
    `document_parsing.parse_document` applies to a single corrupted file.
    """

    settings = get_settings()
    session_factory = get_sessionmaker()
    shutdown = _ShutdownRequested()
    _install_signal_handlers(shutdown)

    logger.info("worker runner starting (poll_interval=%.1fs)", poll_interval_seconds)
    while not shutdown.flag:
        started_at = datetime.now(UTC)
        try:
            async with session_factory() as db:
                result = await drain_notification_outbox(db, settings=settings)
                await db.commit()
            if result.claimed:
                logger.info("notification_outbox drain: %s", result)
        except Exception:
            logger.exception("worker iteration failed")

        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        remaining = max(0.0, poll_interval_seconds - elapsed)
        if remaining and not shutdown.flag:
            await asyncio.sleep(remaining)

    logger.info("worker runner shutting down")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()

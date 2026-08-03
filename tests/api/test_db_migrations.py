"""DB migration upgrade -> downgrade -> upgrade round trip (QAS-003 acceptance).

Mirrors the env-gating convention already established by
`backend/tests/conftest.py` (env var `TEST_DATABASE_URL`, same default URL,
broad "any connection failure at all = skip" catch - see that file's docstring
for why: an unrelated local Postgres answering on the default port with a role/
auth error must skip just like "nothing listening" does) so this test behaves
identically to the rest of the suite in environments that do or do not have a
throwaway Postgres available.

This file intentionally does NOT import or modify `backend/tests/conftest.py` -
QAS-003's owned path for this task is `tests/api/**` only, so the small
connectivity probe is re-implemented locally here rather than reaching into
`backend/tests/`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
_DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:5432/backju_test"


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)


def _can_connect(url: str) -> bool:
    async def _probe() -> bool:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        try:
            async with engine.connect():
                return True
        except Exception:  # noqa: BLE001 - any failure means "skip", see module docstring
            return False
        finally:
            await engine.dispose()

    return asyncio.run(_probe())


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = _test_database_url()
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_alembic_upgrade_downgrade_upgrade_roundtrip():
    url = _test_database_url()

    try:
        reachable = _can_connect(url)
    except Exception:  # noqa: BLE001 - e.g. sqlalchemy/asyncpg not importable at all
        reachable = False

    if not reachable:
        pytest.skip(
            f"TEST_DATABASE_URL ({url}) is not reachable in this environment - "
            "skipping the DB migration round-trip, matching backend/tests/"
            "conftest.py's existing env-gating convention. Set TEST_DATABASE_URL "
            "to point at a throwaway Postgres (with the pgvector extension "
            "creatable) to actually exercise this test."
        )

    up1 = _run_alembic("upgrade", "head")
    assert up1.returncode == 0, (
        f"alembic upgrade head failed (rc={up1.returncode}):\n"
        f"stdout:\n{up1.stdout}\nstderr:\n{up1.stderr}"
    )

    down = _run_alembic("downgrade", "-1")
    assert down.returncode == 0, (
        f"alembic downgrade -1 failed (rc={down.returncode}):\n"
        f"stdout:\n{down.stdout}\nstderr:\n{down.stderr}"
    )

    up2 = _run_alembic("upgrade", "head")
    assert up2.returncode == 0, (
        f"second alembic upgrade head failed (rc={up2.returncode}):\n"
        f"stdout:\n{up2.stdout}\nstderr:\n{up2.stderr}"
    )

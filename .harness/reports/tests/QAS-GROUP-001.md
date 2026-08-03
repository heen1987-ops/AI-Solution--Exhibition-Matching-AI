# QAS-GROUP-001 Test Report

Date: 2026-08-03

## Result

PASS with remaining environment blockers.

## Passed

- `cd apps/user-web && npm run lint && npm test && npm run build`
  - user-web Vitest: 5 files, 12 tests passed.
- `cd apps/admin && npm run lint && npm run typecheck && npm test && npm run build`
  - admin Vitest: 5 files, 8 tests passed.
- `npm run typecheck`
  - passed.
- `npm run e2e`
  - Playwright desktop/mobile Chromium: 6 passed.
- `.venv/bin/python -m pytest tests/security -q`
  - 5 passed.
- `infra/scripts/scope-violation-check`
  - passed.
- `cd backend && ../.venv/bin/ruff check . && ../.venv/bin/pytest -q`
  - backend: 104 passed, 12 skipped.
- `.venv/bin/python ai/evaluation/validate_gold_set.py`
  - PASS, 15 samples, 0 schema violations.
- `.venv/bin/python -m pytest ai/schemas/tests/ -q`
  - 60 passed.
- `.venv/bin/ruff check ai src/meet_ai`
  - passed.
- `TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/backju_test .venv/bin/python -m pytest tests/api/test_db_migrations.py -q`
  - passed against temporary PostgreSQL 17 + pgvector clean DB.
- `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head`
  - passed against temporary PostgreSQL 17 + pgvector clean DB.
- `npm run perf:web-only`
  - WEB_ONLY HTTP smoke passed against local dev servers.
  - P95: home 39.2ms, recommendations 37.9ms, guest search 22.0ms, company detail 21.2ms, admin console 28.0ms.
- `PERF_STRICT=1 npm run perf:web-only`
  - WEB_ONLY HTTP strict target smoke passed against local dev servers.
  - P95: home 26.1ms, recommendations 25.9ms, guest search 19.6ms, company detail 21.5ms, admin console 32.2ms.
- `LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load`
  - WEB_ONLY local load smoke passed with 0 errors.
  - P95: home 84.7ms, recommendations 137.5ms, guest search 80.8ms, company detail 83.0ms, admin console 73.6ms.
- `LOAD_STRICT=1 LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load`
  - WEB_ONLY strict target load smoke passed with 0 errors.
  - P95: home 84.4ms, recommendations 109.5ms, guest search 84.5ms, company detail 81.8ms, admin console 75.9ms.
- `.github/workflows/ci.yml` local validation
  - YAML parsed successfully.
  - WEB_ONLY frontend job commands passed locally: user-web lint/test/build, admin lint/typecheck/test/build.
  - CI runner execution remains external.

## Environment Blockers

- Docker Compose actual startup not run: Docker unavailable in this execution environment.
- Formal representative load target not run; representative DB/cache/network/concurrency environment is still required.

## Migration Fix

- Initial clean PostgreSQL 17 migration verification failed at `0013_search_web_only_indexes` because pgvector HNSW cannot index an unconstrained `vector` column.
- Fixed the index as a 1536-dimensional partial expression HNSW index: `embedding::vector(1536)` where `active AND embedding_dimension = 1536`.

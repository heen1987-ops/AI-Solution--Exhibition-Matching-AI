# G0 CI WEB_ONLY Expansion

Date: 2026-08-03

## Result

PARTIAL PASS. Workflow is expanded and locally validated; actual GitHub Actions runner execution remains environment-dependent.

## Updated Workflow

`.github/workflows/ci.yml` now includes:

- `frontend-web-only`
  - root typecheck
  - user-web lint/test/build
  - admin lint/typecheck/test/build
- `e2e-web-only`
  - Chromium install
  - `npm run e2e`
- `performance-web-only`
  - `PERF_STRICT=1 npm run perf:web-only`
  - `LOAD_STRICT=1 LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load`
- `docker-build`
  - now runs `infra/scripts/verify-docker-stack`

## Local Verification

- Workflow YAML parsed successfully.
- Job list confirmed:
  - backend
  - build-artifact
  - docker-build
  - e2e-web-only
  - frontend-web-only
  - harness-validate
  - meet-ai-core
  - performance-web-only
  - secret-scan
  - ts-boundary
- `npm run typecheck` passed.
- user-web lint/test/build passed.
- admin lint/typecheck/test/build passed.
- `bash -n infra/scripts/verify-docker-stack` passed.
- Performance scripts passed syntax checks.

## Runtime Note

Backend local app startup was verified separately via `uvicorn app.main:app` on port 8010. `/health/live` returned HTTP 200. The first port 8000 attempt was blocked by an existing listener, not by application startup failure.

## Remaining External Check

Trigger GitHub Actions once in the real repository to verify runner-only factors such as Docker availability, Playwright browser dependencies, and network access for gitleaks download.

# MVP Release Decision

Date: 2026-08-03

## Decision

NO-GO: `BLOCKED_EXTERNAL`

## Why

Local WEB_ONLY MVP checks are green, but release readiness still depends on external execution:

1. GitHub Actions remote CI run
   - Current status: NOT_RUN
   - Reason: local `.github/workflows/ci.yml` changes have not been pushed, so no workflow is visible remotely.
   - Verifier: `infra/scripts/verify-github-actions`
2. Docker Compose infrastructure and backend image build
   - Current status: NOT_RUN
   - Reason: Docker CLI is unavailable in this execution environment.
   - Verifier: `infra/scripts/verify-docker-stack`
3. Formal representative load test
   - Current status: NOT_RUN
   - Reason: requires representative DB/cache/network/concurrency environment.
   - Local substitute completed: WEB_ONLY HTTP/load strict smoke.

## Local Evidence

- `infra/scripts/release-readiness-check`
  - Harness validation: PASS
  - Scope violation check: PASS
  - Git diff whitespace check: PASS
  - Overall: `RELEASE_READINESS=BLOCKED_EXTERNAL`
- WEB_ONLY E2E: PASS
- Clean PostgreSQL 17 + pgvector migration roundtrip: PASS
- WEB_ONLY strict HTTP/load smoke: PASS
- Backend runtime OpenAPI operationId mismatch: 0

## Recheck Commands

After committing/pushing the local branch:

```bash
infra/scripts/verify-github-actions
```

In a Docker-capable environment:

```bash
infra/scripts/verify-docker-stack
```

For the combined local/external gate:

```bash
infra/scripts/release-readiness-check
```

## Promotion Rule

Do not move `G3_MVP_RELEASE` to PASSED until the combined readiness check returns:

```text
RELEASE_READINESS=PASSED
```

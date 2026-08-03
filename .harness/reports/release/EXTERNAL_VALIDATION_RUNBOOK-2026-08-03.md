# External Validation Runbook

Date: 2026-08-03

## Purpose

Move `G3_MVP_RELEASE` from `BLOCKED_EXTERNAL` to `PASSED` only after the checks below pass in the required external environments.

## Preconditions

- Local branch changes are committed and pushed.
- GitHub Actions is enabled for `heen1987-ops/AI-Solution--Exhibition-Matching-AI`.
- A Docker-capable local or CI environment is available.
- A representative performance environment is available when formal load approval is required.

## Step 1: Remote CI

Run after pushing `.github/workflows/ci.yml`:

```bash
infra/scripts/verify-github-actions
```

Pass criterion:

```text
PASS: latest 'CI' GitHub Actions run succeeded
```

If this returns `NOT_RUN`, confirm that the pushed branch contains `.github/workflows/ci.yml` and that Actions is enabled for the repository.

## Step 2: Docker Stack

Run in a Docker-capable environment:

```bash
infra/scripts/verify-docker-stack
```

Pass criterion:

```text
PASS: Docker Compose infrastructure is healthy and backend image builds
```

By default, the script cleans up the Compose stack. Set `VERIFY_DOCKER_KEEP=1` only when debugging.

## Step 3: Formal Performance

Run local-style smoke first against the representative URLs:

```bash
USER_WEB_BASE_URL=https://<user-web-host> \
ADMIN_BASE_URL=https://<admin-host> \
PERF_STRICT=1 \
npm run perf:web-only
```

Then run load smoke against the same representative URLs:

```bash
USER_WEB_BASE_URL=https://<user-web-host> \
ADMIN_BASE_URL=https://<admin-host> \
LOAD_STRICT=1 \
LOAD_DURATION_SECONDS=300 \
LOAD_CONCURRENCY=<approved-concurrency> \
npm run perf:web-only:load
```

Pass criteria:

- Error rate: 0 unless an explicit release exception is approved.
- P95 thresholds:
  - registered-web-home: 1000ms
  - registered-web-recommendations: 3000ms
  - guest-web-search: 2000ms
  - company-detail: 1000ms
  - admin-console: 1500ms

## Step 4: Combined Readiness

Run:

```bash
infra/scripts/release-readiness-check
```

Pass criterion:

```text
RELEASE_READINESS=PASSED
```

## Promotion Updates

Only after all pass criteria are met:

1. Update `.harness/state.json`
   - `gate_status`: `PASSED`
   - `gate_status_detail.G3_MVP_RELEASE`: include CI, Docker, and formal performance pass evidence.
   - `mvp_progress_percent`: `100`
2. Update `.harness/quality-gates.yaml`
   - `G0_BOOTSTRAP.status`: `PASSED` if Docker and CI are also green.
   - `G3_MVP_RELEASE.status`: `PASSED`.
   - `g0-2`, `g0-5`, `g0-6`, `g3-11`: `PASSED` with evidence notes.
3. Add a release decision report:
   - `.harness/reports/release/MVP_RELEASE_DECISION-YYYY-MM-DD.md`
4. Add a run-log entry at the top of `.harness/run-log.md`.

## Current Status

As of 2026-08-03, do not promote:

```text
RELEASE_READINESS=BLOCKED_EXTERNAL
```

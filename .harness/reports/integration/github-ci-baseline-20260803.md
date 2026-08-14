# FND-003 — GitHub CI baseline

Date: 2026-08-03

Status: PASS

## Outcome

`.github/workflows/ci.yml` now protects pull requests and `main` pushes with two independent jobs:

1. `Engine and API` installs the root matching engine and FastAPI development dependencies,
   checks fatal Python lint categories, verifies installed dependencies, and runs the root engine
   and full backend test suites.
2. `Active web apps` installs the frozen pnpm workspace, then runs the root lint, typecheck, test,
   and production build commands.

The root pnpm commands explicitly exclude `backju-kiosk`. They cover `apps/user-web`,
`apps/admin`, and the root Netlify TypeScript boundary, matching CR-009's active web scope. The
workflow has read-only repository permissions, does not persist checkout credentials, cancels
superseded runs on the same ref, and contains no secrets or deployment authority.

## Python lint baseline

The repository currently has six pre-existing import-order findings in backend code outside this
task. To publish a green baseline without rewriting other owners' files, CI checks Ruff's fatal
categories `E9,F63,F7,F82`. Full formatting and import-order cleanup remains separate technical
debt; the CI does not claim that the whole repository passes every Ruff rule.

## Reproducible validation

The workflow YAML shape was parsed and asserted locally. A clean NTFS Git worktree then reproduced
the intended runner sequence:

- Python 3.12 fresh virtual environment editable install: pass
- Python fatal Ruff categories: pass
- `pip check`: pass
- Common engine tests: 72 passed
- FastAPI backend tests: 219 passed, 2 optional PostgreSQL tests skipped
- pnpm 9.15.0 frozen install: pass, 727 packages
- Active web lint: pass, zero warnings/errors
- Active web typecheck plus root TypeScript check: pass
- Active web test command: pass
- Admin production build: pass, 13 generated routes
- User-web production build: pass, 21 generated routes

On a Windows worktree with global `core.autocrlf=true`, one immutable SQL byte-hash test initially
observed CRLF bytes. Re-checking the tracked Git blob with LF—the exact form used by the fixed
Ubuntu runner—produced the expected SHA-256 and all 219 backend tests passed. No production SQL or
test contract was changed.

## Roadmap alignment

The newest living-roadmap turns keep the product web-first and describe a mobile `나의 행사` HTML
surface reached through Kakao notification links. This CI protects the active web surface but does
not implement Kakao delivery, magic-link authentication, or new personal-data flows. Those require
the frozen authentication/session and notification contracts before implementation. Dedicated
kiosk runtime remains excluded.

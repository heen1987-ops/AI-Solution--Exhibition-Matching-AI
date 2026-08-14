# Canonical Root Materialization — Integration Report

Date: 2026-08-02
Target: `G:/내 드라이브/CODE/Meet AI`

## Outcome

- The current monorepo implementation now lives directly at the requested project root.
- `.claude/` and its linked worktrees remain local-only and are ignored by the project repository.
- The target is an independent Git repository on `codex/backju-ontology-ai-gateway`, rather than
  inheriting the unrelated parent repository at `G:/내 드라이브`.
- Public catalog/search, anonymous kiosk sessions, signed QR handoff, guest web resolution,
  user web, and the current admin UI are present under the canonical `apps/*` layout.

## Corrections made during materialization

1. Corrected the API pytest path from `../src` to `../../src`.
2. Corrected the API editable-install instruction from `..` to `../..`.
3. Corrected the exhibition DDL generator repository root from `parents[2]` to `parents[3]`.
4. Updated the opt-in live PostgreSQL integration assertion to Alembic head
   `0016_kiosk_session`.
5. Replaced the stale broad `lib/` exclusion with explicit `apps/*/lib` re-inclusion and restored
   19 required frontend source modules.
6. Re-resolved the pnpm lock to Rollup `4.62.3` and allowed install scripts only for `esbuild` and
   `unrs-resolver`; frozen installation now passes the active supply-chain policy.

## Verification evidence

- Backend: `148 passed, 2 skipped`; skips require an explicitly configured live PostgreSQL DB.
- Root ontology/AI/scoring: `177 passed`.
- Alembic: one head, `0016_kiosk_session`.
- Ontology: 259 concepts, 11 synonyms, 7 relations.
- Contract: harness JSON/YAML parse; FastAPI OpenAPI exactly matches the snapshot with 66 paths and
  171 schemas.
- Dependency installation: `pnpm install --frozen-lockfile` passes supply-chain verification.
- Kiosk: 3 component/privacy tests pass.
- TypeScript: admin, kiosk, user web, and root Netlify functions pass typecheck.
- Production builds: kiosk 12 pages, admin 13 pages, user web 20 pages.
- Targeted Python undefined-name checks pass.

## Remaining release work

- Run the opt-in live PostgreSQL and Redis integration checks against an isolated test stack.
- Publish/populate `ai.object_embedding` and verify the pgvector semantic channel; semantic search
  remains explicitly zero-weight input until that contract exists.
- Resolve existing full-repository Ruff debt before treating G3 lint as green.
- Complete the remaining G2 backlog items before starting Wave 3 release-candidate evaluation.

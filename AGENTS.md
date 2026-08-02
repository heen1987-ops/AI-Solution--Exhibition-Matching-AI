# Project implementation contract

## Required design baseline

Before changing architecture, data models, AI behavior, API contracts, or user flows, review the shared ChatGPT design thread:

- https://chatgpt.com/share/6a6d8239-5d0c-83ee-a5b5-7505c996e874

The page is larger than ordinary text fetch limits. If a tool cannot return it directly, inspect the page through a browser session or decode the page's serialized current-branch conversation. Do not treat a failed lightweight fetch as evidence that the reference is unavailable.

Apply its transferable design principles to this exhibition domain; do not copy the source thread's unrelated research-platform entities.

Mandatory invariants:

1. Start as a modular monolith and add service boundaries only from measured operational need.
2. Keep canonical business records separate from user, AI, and review overlays.
3. Version immutable published artifacts; changes create a new version rather than rewriting history.
4. Put external AI and integration providers behind adapters.
5. Store provenance, evidence references, review state, and append-only activity needed to reproduce decisions.
6. Include observability, retry/idempotency, recovery, privacy, and operator review in the design—not as later add-ons.
7. AI output is a proposal. Deterministic validation and user/operator confirmation govern hard constraints and canonical data.

Record any deliberate exception in the relevant design document before implementing it.

## Delivery

After an implementation unit passes relevant checks, commit it intentionally and push it to the `exhibition` Git remote unless the user says otherwise. Never include secrets, local dependency directories, or unrelated workspace changes.

---

## Parallel development harness (added 2026-08-02)

This project is developed by multiple parallel agents/workers coordinated through a
persistent harness in `.harness/`. Read these before any task:

1. `PROJECT_SCOPE.md` — the three modules (web personalization / kiosk search / common AI platform), fixed tech stack, explicit exclusions.
2. `.harness/state.json` — current wave/gate/task pointers.
3. `.harness/backlog.yaml` — the task list.
4. `.harness/locks.yaml` — which track owns which paths.
5. `.harness/contracts/**` — domain model, OpenAPI, event catalog, ontology, error codes.
6. Relevant prior `.harness/handoffs/**`.

Full methodology (tracks, waves, quality gates, "다음"/status/verify/retry/rollback command
protocol, worker prompt templates): [docs/harness-orchestrator-prompt-pack.md](./docs/harness-orchestrator-prompt-pack.md).
Product scope pivot rationale: [docs/redesign-web-kiosk-split.md](./docs/redesign-web-kiosk-split.md) and
[docs/vibe-coding-master-spec-v1.md](./docs/vibe-coding-master-spec-v1.md).

### Absolute rules

- Never modify files outside your assigned `owned_paths` (see `.harness/locks.yaml`).
- Never modify shared contracts without a Change Request (`.harness/handoffs/contracts/change-request-{id}.md`), approved before implementing.
- Never implement out-of-scope features (see `PROJECT_SCOPE.md` §exclusions) — record ideas in `.harness/expansion-candidates.md` instead.
- Never mark a task complete without meeting its acceptance criteria and tests.
- Validate all AI output against a JSON Schema before use.
- Never write personal data into logs, fixtures, or snapshots.
- Never leave a temporary mock committed as if it were production code.
- Trust only published contracts for other tracks' implementations — never guess.
- Database schema changes go through Alembic migrations only, owned by the CONTRACTS track.
- Kiosk builds collect no login, no personal data, no long-lived profile — verified by QA before release.
- Meeting/contact details stay hidden until the exhibitor accepts a request.
- Unapproved exhibitor data never reaches search or recommendation output.

### Monorepo layout (pnpm workspace, canonical since 2026-08-02, DECISION-006)

`backend/` and `frontend/` were physically migrated to `apps/api` and `apps/user-web` on
2026-08-02 (this superseded the earlier ASSUMPTION-001, which had deliberately kept the legacy
names — see `.harness/assumptions.md` for that history). The repo now uses a pnpm workspace
(`pnpm-workspace.yaml`: `apps/*`, `packages/*`) with all app names canonical:
`apps/api`, `apps/user-web`, `apps/kiosk`, `apps/admin`, `apps/worker`. `apps/kiosk`, `apps/admin`,
`apps/worker`, `ai/`, `packages/**` are still net-new (not yet created) — create them directly
under their canonical paths when their backlog task starts.

Two hardcoded-path bugs were found and fixed during the migration (Alembic DDL-file lookups and
test `ROOT` path constants that assumed the old `backend/` nesting depth) — if you find another
file computing paths via `Path(__file__).resolve().parents[N]` with a hardcoded `N`, re-verify it
after any further directory moves.

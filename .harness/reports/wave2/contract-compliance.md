# QA-003: Contract Compliance Report (Wave 2)

Scope: BACKEND-008(공개API), BACKEND-006(키오스크API), KIOSK-001+002, ADMIN-001+002,
AISEARCH-002(쿼리인터프리터). Verification only, no code written.

## Verdict: PASS_WITH_WARNING

## 1. Shared file protection (`apps/api/app/api/v1/api.py`, `apps/api/app/models/__init__.py`)

- `git status --porcelain` shows both files as untracked (`??`) with no commit history at all
  (`git log` returns nothing for either path) — every file in this wave is new/uncommitted, so
  authorship cannot be attributed from git blame.
- File mtimes: `api.py` was last written at `2026-08-02 11:05:04`, which is **before** the final
  edits to `kiosk.py` (11:25), `search.py` (11:26), `exhibitors.py` (11:30), and
  `exhibition_public.py` (11:32). `api.py` already contained
  `include_router(kiosk.router, ...)`, `include_router(search.router, ...)`, and
  `include_router(exhibitors.router, tags=["public-catalog"])` at that earlier timestamp, i.e.
  no edit to `api.py` occurred after the BACKEND-006/BACKEND-008 router work began. Same pattern
  for `models/__init__.py` (11:31:22, one edit importing `kiosk` among others) vs.
  `models/kiosk.py` (11:32:16).
- Conclusion: neither shared file was touched by the currently active router/model work in this
  wave; both were already pre-wired (plausibly by FOUNDATION/CONTRACTS scaffolding) with
  forward-looking imports. **No violation of the "add router but don't register" rule found**,
  but this can't be proven with 100% certainty until these files are committed and blame becomes
  available — flag as a WARNING for the CONTRACTS/FOUNDATION track to confirm at integration
  time, not a hard failure.
- Side finding (not a violation, but a documentation/reality mismatch worth fixing before
  release): `apps/api/app/api/v1/routers/exhibition_public.py`'s module docstring says the
  router "아직 등록하지 않는다" (not yet registered) and describes a future manual
  registration step. In fact `apps/api/app/api/v1/routers/exhibitors.py` was turned into a
  thin re-export shim (`from app.api.v1.routers.exhibition_public import router`), and
  `api.py` already includes `exhibitors.router` under `tags=["public-catalog"]`. So the new
  public-catalog implementation **is** already live through the pre-existing `exhibitors`
  registration slot, contradicting its own docstring. Functionally harmless (approval filters
  are correctly in place either way, see scope-compliance / security-baseline reports), but the
  docstring should be corrected so future readers don't assume the endpoints are inert.

## 2. Alembic migration chain

- New migration `apps/api/alembic/versions/20260802_0016_kiosk_session.py` has
  `down_revision = "0015_conversation_profile"`, matching the actual latest prior revision
  (`20260802_0015_conversation_profile.py`, `revision = "0015_conversation_profile"`). Chain is
  correctly linked, not a `.pending` stub.
- Two unrelated `.pending` files already exist in `apps/api/alembic/pending/` from other tracks
  (`20260801_1600_...interaction_domain....pending`,
  `20260801_0003_0005_exhibitor_domain.py.pending`) — pre-existing, not introduced by this
  wave's active tasks, no action needed from QA-003.

## 3. AI query interpreter uses the canonical ontology (DECISION-004)

- `ai/query_interpreter.py` imports `from meet_ai.ontology import Catalog, load_catalog` and
  `from meet_ai.ontology.catalog import normalize_text`, loading
  `src/meet_ai/ontology/catalog.v1.json` (confirmed 259 concepts) through the canonical
  `meet_ai.ontology` package. No hardcoded concept-code enums (no `INDUSTRY.MANUFACTURING`-style
  literals) found in the file. `ai/tests/test_query_interpreter.py` is described as covering
  `test_never_invents_codes_outside_catalog`.
- `apps/api/app/services/search_query_interpreter.py` (the interim matcher actually wired into
  the live `/search` and `/kiosk/sessions/{id}/search` endpoints today, pending
  `ai.query_interpreter.QueryInterpreter` integration) also imports
  `from meet_ai.ontology.catalog import Catalog, load_catalog, normalize_text` and only reads
  concept codes/labels out of the loaded catalog — no hardcoded codes there either. Its own
  docstring correctly cites AGENTS.md/DECISION-004.
- **PASS** — no violation of "never hardcode ontology codes" found in either interpreter.

## 4. New router registration hygiene

- `apps/api/app/api/v1/routers/exhibition_public.py`, `search.py`, `kiosk.py` all delegate
  approval/visibility filtering to service/repository layers
  (`app.services.exhibition_public_repository`, `app.services.catalog_search`) rather than
  embedding SQL/approval logic in the router — matches the layering the BACKEND-008 docstring
  commits to, and keeps the filter independently testable (see security-baseline.md for the
  actual filter verification).

## Summary

| Check | Result |
|---|---|
| Shared `api.py` / `models/__init__.py` untouched by active tasks | PASS (unverifiable via git blame yet — WARNING) |
| Alembic chain integrity for new kiosk migration | PASS |
| `ai/query_interpreter.py` uses canonical ontology catalog, no hardcoded codes | PASS |
| Interim `search_query_interpreter.py` also uses canonical catalog | PASS |
| Router/service/repository layering respected | PASS |
| Docstring in `exhibition_public.py` inaccurately claims "not yet registered" | WARNING (fix docstring) |

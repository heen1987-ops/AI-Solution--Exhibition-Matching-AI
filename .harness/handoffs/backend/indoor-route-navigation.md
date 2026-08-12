# Indoor route navigation (U-13) - integration handoff

## What was built

The user-web `/route` page ("AI 추천 방문 동선") already called `POST /routes` and
`POST /routes/{id}/recalculate` against a fully-specified contract
(`apps/user-web/lib/types.ts`), but neither endpoint existed on the backend - a
straight 404 in production. This work makes the feature real, end to end:

- **Backend (already committed on this branch before this integration pass,
  commit `72ec013`)**: `interaction.route` / `route_item` /
  `indoor_checkpoint_scan` tables (`apps/api/app/models/route.py`,
  `apps/api/app/models/indoor_positioning.py`), migration
  `apps/api/alembic/versions/20260812_0032_route_positioning.py`, a pure
  DB-free pathfinding engine (`apps/api/app/services/routing/pathfinding.py`),
  an `IndoorPositionSource` provider seam
  (`apps/api/app/services/routing/positioning.py`), the service layer
  (`apps/api/app/services/routing/service.py`), and the router
  (`apps/api/app/api/v1/routers/route.py`, `build_route_router()`) exposing:
  - `POST /api/v1/routes`
  - `GET /api/v1/routes/{route_id}`
  - `POST /api/v1/routes/{route_id}/recalculate`
  - `POST /api/v1/routes/{route_id}/items/{item_id}/status`
  - `POST /api/v1/routes/checkpoint-scans`
- **This integration pass**: wired `build_route_router()` into
  `apps/api/app/api/v1/api.py` and registered `route` + `indoor_positioning`
  in `apps/api/app/models/__init__.py` so Alembic autogenerate/metadata see
  the new tables. Bumped the two hardcoded schema-guard assertions in
  `apps/api/tests/test_exhibitor_models.py` (table count 135 -> 138, single
  alembic head 0031 -> 0032) that the new migration made stale. Landed the
  frontend track's uncommitted work: `apps/user-web/app/route/page.tsx`
  wiring adjustments, `apps/user-web/lib/api-client.ts` /
  `apps/user-web/lib/types.ts` contract updates, a small route-aware tweak to
  `apps/user-web/app/booths/[boothId]/page.tsx`, and the new
  `apps/user-web/features/indoor-route/` components
  (`RouteFloorPlan.tsx`, `CheckpointScanButton.tsx` + their tests).

## Honest scope - what "indoor positioning" means here

The user asked to ground indoor-guidance improvements in the spirit of
베스텔라랩(Vestella Lab)'s Watchmile product - camera-vision + on-device-AI
indoor positioning, sub-2m accuracy, no GPS, US-patented. That is proprietary,
hardware-dependent technology this codebase cannot reimplement (no camera
infrastructure exists at the venue, and their approach is patented). Nothing
in this change claims or implies real camera-based positioning was built.

What was actually built as the honest, deployable-today equivalent:

1. **Real optimal-route calculation** from actual booth floor coordinates
   (`exhibition.booth.map_x/map_y`, already-existing `NUMERIC(10,3)` columns) -
   nearest-neighbor construction + bounded 2-opt improvement over Euclidean
   plan-distance. No physical unit for `map_x/map_y` is documented anywhere in
   this repo (re-checked `docs/db-erd-table-spec.md` 13.1 and
   `docs/08-exhibitor-product-profile-model.md`), so "walking minutes" is a
   single configurable constant (`WALKING_SPEED_PLAN_UNITS_PER_MINUTE` in
   `pathfinding.py`) converting plan-distance to a minutes estimate - a
   documented placeholder, not a calibrated real-world ETA.
2. **A deployable-today indoor positioning fallback using existing QR
   infrastructure**: `QrCheckpointProvider` reads the most recent
   `interaction.indoor_checkpoint_scan` row, written when a visitor scans a
   booth's existing `exhibition.booth_qr` code. This reuses the kiosk QR
   model as a visitor checkpoint scan-in signal, not a manual 5-zone
   self-report (though `ManualZoneProvider` still exists as the coarser
   fallback when no recent scan exists).
3. **A clean provider seam** (`IndoorPositionSource` Protocol in
   `positioning.py`) so a real camera-based positioning feed
   (Vestella-Lab-style or anything else) can be added later as a one-file
   third provider class, without touching `pathfinding.py` or `service.py` -
   both only ever see a `PositionObservation` or `None`.

## What is explicitly NOT done

- **No camera QR scanner UI.** `CheckpointScanButton.tsx` is manual code
  entry only, matching this repo's existing `check-in/[qrToken]` flow's
  `ManualCodeEntry` fallback convention. A camera-based QR reader is future
  work, not silently faked.
- **No wall-aware / turn-by-turn pathfinding.** Distances are straight-line
  (Euclidean) between plan coordinates; there is no aisle/corridor graph and
  no obstacle data anywhere in this repo to route around.
- **No calibrated real-world walking-speed constant.** `WALKING_SPEED_PLAN_UNITS_PER_MINUTE`
  is a placeholder pending a documented physical unit for `map_x/map_y`.
- **TSP beyond nearest-neighbor + bounded 2-opt.** Not an exact or
  metaheuristic (e.g. Lin-Kernighan, simulated annealing) solver - a
  reasonable, fast, testable approximation, not the optimum.
- **No real camera/AI-vision indoor positioning** (see "Honest scope" above)
  - by design, not an oversight.

## Verification numbers

- `apps/api` pytest (full suite): **1109 passed, 3 skipped, 1 xfailed** (was
  1107 passed / 2 failed before the two guard-test assertions were bumped for
  the new migration - both failures were hardcoded counts/head, not logic
  bugs).
- `alembic heads`: single head, `0032_route_positioning`.
- `alembic upgrade head --sql`: compiles clean through the new migration
  (verified the full `CREATE TABLE`/`CREATE INDEX`/constraint DDL for
  `route`, `route_item`, `indoor_checkpoint_scan` and the final
  `alembic_version` UPDATE).
- `apps/user-web` typecheck (`tsc --noEmit`, clean `C:\tmp` copy, `pnpm
  install` fresh): fails only on `vitest.config.ts`'s pre-existing
  `esbuild.jsx` option not matching vite 8's `ESBuildOptions` type - a
  documented, pre-existing toolchain defect from the WAVE2C/2D/2E merge
  (commit `bda6af6`, months before this feature branched), *not* something
  introduced by this feature. Isolated by temporarily excluding
  `vitest.config.ts` in the same clean copy (never committed): typecheck is
  **clean** across all feature code, confirming the route/indoor-route
  TypeScript is fully type-safe.
- `apps/user-web` vitest (`vitest run`, same clean copy): **133 passed, 26
  test files passed**, 0 failed - includes the two new
  `features/indoor-route/__tests__/*.test.tsx` files.

## Branch / commit

- Started on `track/route-positioning-pathfinding` (descendant of `72ec013`,
  which already carried the full backend implementation).
- Created new branch `feature/indoor-route-navigation` from that tip.
- Committed this integration pass's changes there as commit `efa3714`:
  `feat: wire indoor route navigation backend into the API and land frontend
  integration` - 13 files changed (see commit for the exact list: the two
  wiring files, the guard-test fix, the four already-existing frontend files
  the frontend track had modified but left uncommitted, and the six new
  `features/indoor-route/` files).
- `codex/backju-ontology-ai-gateway` (PR #4, under active human review) was
  **not** touched, committed to, or pushed. `feature/indoor-route-navigation`
  was **not** pushed to origin - left for a human decision.
- `.harness/backlog.yaml` has unrelated concurrent-work backlog entries
  (`NOTIFY-002`, `CLEANUP-001`, `QUALITY-001`, `RECONCILE-001`) mixed in with
  the `ROUTE-001` entry for this feature; it was deliberately left
  uncommitted/unstaged rather than swept in with a broad `git add`, per the
  task's explicit instruction to stage only this feature's files.

## Known upstream note (not this branch's problem to fix)

`codex/backju-ontology-ai-gateway` had a separate Windows `core.autocrlf`
line-ending bug (broke the DDL-hash-guarded `0001_ontology`/`0002_exhibition`
migrations) already fixed there directly (commit `0d62e15` +
`.gitattributes`). This branch forked before that landed, so it is not
present here. It did not surface in this branch's pytest/alembic runs (the
DDL-hash guard did not trip), so no rebase was required to get a clean
verification pass - noted here only so a future rebase onto
`codex/backju-ontology-ai-gateway` (post-merge) isn't a surprise.

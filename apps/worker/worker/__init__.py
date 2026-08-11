"""apps/worker's import root.

Named `worker`, deliberately NOT `app` (the name the original two-track WAVE 2C/2D/2E
prototype used). This rename is mandatory, not cosmetic:

In the standalone worktree prototype, `apps/worker/app/...` and `apps/api/app/...` never
had to coexist on the same `sys.path` - the worker imported nothing from the API package,
so the name clash was survivable (merely confusing). In this unified repo it inverts: every
job under `worker.jobs` does its real work by reading/writing `apps/api`'s own ORM models
through `apps/api`'s own async DB session (see `worker.jobs.notification_outbox` for the
first fully-wired example), so `apps/worker` and `apps/api` sit on `sys.path` *simultaneously*
whenever this worker runs. Two top-level packages both named `app` on the same `sys.path`
resolve unpredictably depending on import order / entry point - a bug that reproduces under
one launcher and not another, which is exactly the failure mode this rename exists to
prevent (see the merge plan's "apps/worker package name and dependency policy" resolution).
"""

from __future__ import annotations

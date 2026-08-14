# apps/worker

Async worker jobs for the Backju AI matching service: notification-outbox delivery,
analytics aggregation, data-quality snapshots, document parsing, search-index
regeneration, and cache invalidation.

Import root is `worker` (package `backju-worker`), not `app` - the unified repo's
`apps/api` package already owns the `app` import root, and this worker writes against
`apps/api`'s own models/DB session, so both packages sit on `sys.path` at once. See
`worker/__init__.py` for the full rationale.

Run the tests from this directory:

```
pytest
```

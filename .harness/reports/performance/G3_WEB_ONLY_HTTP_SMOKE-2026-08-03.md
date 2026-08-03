# G3 WEB_ONLY HTTP Performance Smoke

Date: 2026-08-03

## Result

PASS for local HTTP smoke and strict target smoke. Formal load testing remains environment-dependent.

## Command

```bash
npm run perf:web-only
```

The command expects user-web and admin to be reachable at:

- `USER_WEB_BASE_URL`, default `http://127.0.0.1:3300`
- `ADMIN_BASE_URL`, default `http://127.0.0.1:3320`

## Measured Results

Local dev servers were started on ports 3300 and 3320 before running the smoke.

| Target | P95 | Max | Local threshold | Production target reference |
| --- | ---: | ---: | ---: | ---: |
| registered-web-home | 39.2ms | 39.2ms | 2500ms | 1000ms |
| registered-web-recommendations | 37.9ms | 37.9ms | 3500ms | 3000ms |
| guest-web-search | 22.0ms | 22.0ms | 3500ms | 2000ms |
| company-detail | 21.2ms | 21.2ms | 2500ms | 1000ms |
| admin-console | 28.0ms | 28.0ms | 3000ms | 1500ms |

## Notes

- This smoke measures WEB_ONLY HTTP page responses with fallback/dev data and no production traffic profile.
- `PERF_STRICT=1 npm run perf:web-only` switches thresholds to the production target references.
- Formal release performance still requires a CI/staging environment with representative backend, database, and concurrency.

## Strict Target Smoke

`PERF_STRICT=1 npm run perf:web-only` also passed against local dev servers.

| Target | P95 | Max | Strict threshold |
| --- | ---: | ---: | ---: |
| registered-web-home | 26.1ms | 26.1ms | 1000ms |
| registered-web-recommendations | 25.9ms | 25.9ms | 3000ms |
| guest-web-search | 19.6ms | 19.6ms | 2000ms |
| company-detail | 21.5ms | 21.5ms | 1000ms |
| admin-console | 32.2ms | 32.2ms | 1500ms |

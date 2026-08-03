# G3 WEB_ONLY Load Smoke

Date: 2026-08-03

## Result

PASS for local load smoke and strict target load smoke. Formal load testing remains environment-dependent.

## Command

```bash
npm run perf:web-only:load
```

Useful environment variables:

- `LOAD_DURATION_SECONDS`, default `15`
- `LOAD_CONCURRENCY`, default `4`
- `LOAD_STRICT=1` to use production target references as thresholds
- `USER_WEB_BASE_URL`, default `http://127.0.0.1:3300`
- `ADMIN_BASE_URL`, default `http://127.0.0.1:3320`

## Local Load Smoke

Local dev servers were started on ports 3300 and 3320. Command:

```bash
LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load
```

| Target | Requests | Errors | P95 | Max | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| registered-web-home | 218 | 0 | 84.7ms | 252.7ms | 2500ms |
| registered-web-recommendations | 154 | 0 | 137.5ms | 979.1ms | 3500ms |
| guest-web-search | 139 | 0 | 80.8ms | 110.9ms | 3500ms |
| company-detail | 105 | 0 | 83.0ms | 240.0ms | 2500ms |
| admin-console | 98 | 0 | 73.6ms | 75.9ms | 3000ms |

## Strict Target Load Smoke

Command:

```bash
LOAD_STRICT=1 LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load
```

| Target | Requests | Errors | P95 | Max | Strict threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| registered-web-home | 234 | 0 | 84.4ms | 238.8ms | 1000ms |
| registered-web-recommendations | 145 | 0 | 109.5ms | 537.6ms | 3000ms |
| guest-web-search | 163 | 0 | 84.5ms | 129.0ms | 2000ms |
| company-detail | 112 | 0 | 81.8ms | 244.4ms | 1000ms |
| admin-console | 104 | 0 | 75.9ms | 131.1ms | 1500ms |

## Notes

- This smoke uses local dev servers, fallback/dev data, and short duration.
- It is useful for regression detection and staging rehearsal.
- Formal release performance still requires representative backend, database, cache, network, and concurrency.

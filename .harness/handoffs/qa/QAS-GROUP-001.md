# QAS-GROUP-001 QA Handoff

상태: DONE

## 구현

- `playwright.config.ts`
  - CR-001 이후 WEB_ONLY 기준으로 E2E webServer를 user-web/admin만 사용하도록 정렬.
  - desktop Chromium + mobile Chromium 프로젝트로 실행.
- `tests/e2e/web-only-smoke.spec.ts`
  - 등록 웹: home -> recommendations -> favorites -> buyer matching.
  - 게스트 웹 모바일: `GUEST_WEB` 검색 -> 상세, 개인정보 입력 필드 부재 확인.
  - admin: 운영 콘솔의 live API forms와 contract-pending panels 확인.
- `tests/security/test_guest_web_privacy_static.py`
  - guest web entry/search/signup surface에 email/tel/password 등 직접식별 입력이 없는지 검사.
- `tests/security/test_event_payload_privacy.py`
  - event catalog payload_fields에 직접식별정보가 들어가지 않는지 검사.
- `tests/security/test_guest_session_lifecycle_static.py`
  - guest conversion 시 session expiry/code clear/visit detach와 temporary favorites active-session requirement 확인.
- `infra/scripts/scope-violation-check`
  - 기존 kiosk 개인정보 입력 검사에 더해 user-web guest entry/search/signup 검사 추가.
- `apps/user-web/app/(screens)/signup/SignupStubForm.tsx`
  - 비활성 email placeholder input 제거. 정식 전환 계약 전에는 개인정보 입력을 열지 않음.

## 검증

- user-web: `npm run lint && npm test && npm run build`
- admin: `npm run lint && npm run typecheck && npm test && npm run build`
- root: `npm run typecheck`
- E2E: `npm run e2e` -> 6 passed.
- security: `python -m pytest tests/security -q` -> 5 passed.
- backend: `ruff check .` + `pytest -q` -> 104 passed, 12 skipped.
- AI: gold set PASS, AI schema tests 60 passed, ruff PASS.
- Migration: 임시 PostgreSQL 17 + pgvector clean DB에서 `tests/api/test_db_migrations.py` 통과.
- Migration: 임시 PostgreSQL 17 + pgvector clean DB에서 `alembic upgrade head` -> `downgrade base` -> `upgrade head` 전체 왕복 통과.
- Performance: `npm run perf:web-only` 로컬 WEB_ONLY HTTP smoke 통과(home 39.2ms, recommendations 37.9ms, guest search 22.0ms, company detail 21.2ms, admin console 28.0ms p95).
- Performance: `npm run perf:web-only:load` 로컬/strict WEB_ONLY load smoke 통과. Strict 기준 p95는 home 84.4ms, recommendations 109.5ms, guest search 84.5ms, company detail 81.8ms, admin console 75.9ms, error 0.
- harness/scope/diff checks 통과.

## 남은 환경 의존 항목

- Docker unavailable로 `FND-004`의 Docker Compose 실제 기동 검증은 여전히 blocked.
- 정식 대표 부하 목표는 대표 DB/cache/network/동시성 환경이 필요.

## 추가 수정

- clean PostgreSQL 검증 중 `0013_search_web_only_indexes`의 pgvector HNSW index가 차원 미지정 `vector` 컬럼 때문에 실패했다.
- `embedding::vector(1536)` partial expression index(`active AND embedding_dimension = 1536`)로 보정해 roundtrip을 통과시켰다.

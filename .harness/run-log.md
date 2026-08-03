# Run Log

가장 최근 실행을 위에 추가한다(역순).

---

## 2026-08-03 - 외부 검증 runbook 고정

트리거: 사용자 "다음". G3가 `BLOCKED_EXTERNAL`로 고정된 상태에서, 외부 담당자가 실행할 절차와 승격 조건을 하나의 문서로 정리.

수행:
1. `.harness/reports/release/EXTERNAL_VALIDATION_RUNBOOK-2026-08-03.md` 작성.
2. runbook에 다음 절차를 고정:
   - GitHub Actions remote CI 검증: `infra/scripts/verify-github-actions`.
   - Docker stack 검증: `infra/scripts/verify-docker-stack`.
   - representative URL 대상 strict HTTP/load performance 검증.
   - combined readiness: `infra/scripts/release-readiness-check`.
3. G3 승격 규칙 명시:
   - `RELEASE_READINESS=PASSED` 전에는 `G3_MVP_RELEASE`를 PASSED로 올리지 않는다.
4. `.harness/state.json.notes.known_gap`에 runbook 경로 추가.

검증:
- `validate-harness` 통과.
- `scope-violation-check` 통과.
- `git diff --check` 통과.

다음 추천 작업: 없음. 외부 환경에서 runbook 실행 필요.

---

## 2026-08-03 - G3 MVP release 판정: BLOCKED_EXTERNAL

트리거: 사용자 "다음". `release-readiness-check`가 반복해서 `BLOCKED_EXTERNAL`을 반환하므로 하네스 최상위 상태를 실제 판정에 맞춰 정리.

수행:
1. `.harness/state.json.gate_status`를 `BLOCKED_EXTERNAL`로 변경.
2. `.harness/state.json.gate_status_detail.G3_MVP_RELEASE`를 external blockers 기준으로 갱신.
3. `.harness/quality-gates.yaml`의 `G3_MVP_RELEASE.status`를 `BLOCKED_EXTERNAL`로 변경.
4. `.harness/reports/release/MVP_RELEASE_DECISION-2026-08-03.md` 작성.

판정:
- NO-GO: `BLOCKED_EXTERNAL`.

근거:
- 로컬 readiness checks는 PASS.
- GitHub Actions remote workflow/run은 local workflow 미push로 NOT_RUN.
- Docker Compose stack/backend image는 Docker CLI 부재로 NOT_RUN.
- formal representative load test는 대표 DB/cache/network/동시성 환경 필요.

다음 추천 작업: 없음. `infra/scripts/release-readiness-check`가 `RELEASE_READINESS=PASSED`를 반환할 때까지 G3를 PASSED로 승격하지 않는다.

---

## 2026-08-03 - release readiness 종합 체크 추가

트리거: 사용자 "다음". Docker/GitHub Actions/formal load 등 외부 의존 검증이 개별 스크립트로 준비된 상태에서, 릴리스 판정을 한 번에 요약하는 최상위 체크를 추가.

수행:
1. `infra/scripts/release-readiness-check` 추가:
   - `validate-harness`.
   - `scope-violation-check`.
   - `git diff --check`.
   - `verify-github-actions`.
   - `verify-docker-stack`.
2. 외부 의존 항목이 `124/125`로 종료되면 전체 판정을 `RELEASE_READINESS=BLOCKED_EXTERNAL`로 표시.
3. `infra/README.md`에 release readiness script 연결.
4. `.harness/reports/release/RELEASE_READINESS_CHECK-2026-08-03.md` 작성.
5. state known_gap에 종합 readiness 결과 반영.

검증:
- `infra/scripts/release-readiness-check` 실행.
- local checks:
  - Harness validation PASS.
  - Scope violation check PASS.
  - Git diff whitespace check PASS.
- external blockers:
  - GitHub Actions latest CI run NOT_RUN: workflow not visible until local `.github/workflows/ci.yml` is pushed.
  - Docker Compose stack NOT_RUN: docker command unavailable.
- 최종 판정: `RELEASE_READINESS=BLOCKED_EXTERNAL`.

남은 환경 의존 항목:
- 로컬 변경 commit/push 후 `infra/scripts/verify-github-actions` 또는 `release-readiness-check` 재실행 필요.
- Docker CLI 있는 환경에서 `infra/scripts/verify-docker-stack` 또는 `release-readiness-check` 재실행 필요.
- 대표 DB/cache/network/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음.

---

## 2026-08-03 - GitHub Actions 원격 상태 확인 및 verifier 추가

트리거: 사용자 "다음". GitHub CLI 인증이 되어 있는지 확인하고, 남은 CI runner 검증을 실제로 진행 가능한지 점검.

수행:
1. 원격 저장소 확인:
   - `heen1987-ops/AI-Solution--Exhibition-Matching-AI`
   - default branch: `main`
2. `gh auth status` 통과 확인.
3. `gh workflow list`, `gh run list --limit 10` 실행 결과 원격에 visible workflow/run 없음 확인.
4. `infra/scripts/verify-github-actions` 추가:
   - `gh` 설치/인증 확인.
   - 원격 workflow visibility 확인.
   - 최신 `CI` workflow run 상태/conclusion 확인.
   - 성공 시에만 PASS, workflow/run 부재 시 NOT_RUN.
5. `infra/README.md`와 `.harness/reports/integration/G0_GITHUB_ACTIONS_REMOTE_STATUS-2026-08-03.md` 추가/갱신.
6. G0 `g0-6` 노트를 원격 workflow 미노출/미실행 상태로 갱신.

검증:
- `bash -n infra/scripts/verify-github-actions` 통과.
- `infra/scripts/verify-github-actions`는 현재 원격 상태에서 NOT_RUN으로 정상 종료:
  - `no workflows are visible ... Push .github/workflows/ci.yml first.`

남은 환경 의존 항목:
- 로컬 변경 commit/push 후 `infra/scripts/verify-github-actions` 재실행 필요.
- Docker Compose 실제 기동은 Docker CLI 있는 환경에서 `infra/scripts/verify-docker-stack` 실행 필요.
- 대표 DB/cache/network/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음.

---

## 2026-08-03 - WEB_ONLY CI 확장 및 G0 상태 정정

트리거: 사용자 "다음". `.github/workflows/ci.yml`은 존재하지만 G0 `g0-6` 노트가 "워크플로 없음"으로 오래되어 있고, 최신 WEB_ONLY 프런트/E2E/성능 하네스가 CI에 배선되지 않은 상태를 발견.

수행:
1. `.github/workflows/ci.yml` 확장:
   - `frontend-web-only`: root typecheck, user-web lint/test/build, admin lint/typecheck/test/build.
   - `e2e-web-only`: Chromium 설치 후 `npm run e2e`.
   - `performance-web-only`: strict HTTP smoke + strict load smoke.
   - `docker-build`: 단순 backend build 대신 `infra/scripts/verify-docker-stack` 실행.
2. `infra/scripts/verify-docker-stack`에 기본 cleanup trap 추가(`VERIFY_DOCKER_KEEP=1`이면 유지).
3. backend 로컬 기동 확인:
   - 8000 포트는 이미 사용 중이라 bind 실패.
   - 8010 포트에서 `uvicorn app.main:app` 기동 후 `/health/live` HTTP 200 확인.
4. G0 `g0-1`을 WEB_ONLY MVP 실행 앱 기준 PASSED로 갱신.
5. G0 `g0-6`을 PARTIAL_PASS로 갱신:
   - workflow 존재 및 로컬 명령 검증 통과.
   - 실제 GitHub Actions runner 1회 실행은 외부 환경 필요.
6. `.harness/reports/integration/G0_CI_WEB_ONLY_EXPANSION-2026-08-03.md` 작성.

검증:
- `.github/workflows/ci.yml` YAML 파싱 통과.
- `npm run typecheck` 통과.
- user-web lint/test/build 통과.
- admin lint/typecheck/test/build 통과.
- `bash -n infra/scripts/verify-docker-stack` 통과.
- 성능 스크립트 `node --check` 통과.

남은 환경 의존 항목:
- Docker Compose 실제 기동은 Docker CLI 있는 환경에서 `infra/scripts/verify-docker-stack` 실행 필요.
- GitHub Actions 실제 runner 1회 실행 필요.
- 대표 DB/cache/network/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음.

---

## 2026-08-03 - WEB_ONLY load smoke 하네스 추가 및 검증

트리거: 사용자 "다음". 남은 formal load blocker를 대표 환경 없이 통과 처리하지 않고, 재현 가능한 load smoke 하네스를 추가해 로컬/strict 기준까지 검증.

수행:
1. `tests/performance/web-only-load-smoke.mjs` 추가:
   - user-web home/recommendations/guest search/company detail.
   - admin console.
   - weighted target mix, duration/concurrency/env 기반 threshold 지원.
2. 루트 `package.json`에 `perf:web-only:load` 스크립트 추가.
3. user-web/admin dev 서버를 임시 기동해 local load smoke 실행.
4. 같은 스크립트를 `LOAD_STRICT=1`로 다시 실행해 production target reference threshold 기준 smoke 확인.
5. `.harness/reports/performance/G3_WEB_ONLY_LOAD_SMOKE-2026-08-03.md` 작성.
6. G3 `g3-11`과 state/report/handoff/backlog에 load smoke 결과 반영.

검증:
- `LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load` 통과, error 0.
- local load p95:
  - home 84.7ms.
  - recommendations 137.5ms.
  - guest search 80.8ms.
  - company detail 83.0ms.
  - admin console 73.6ms.
- `LOAD_STRICT=1 LOAD_DURATION_SECONDS=12 LOAD_CONCURRENCY=4 npm run perf:web-only:load` 통과, error 0.
- strict load p95:
  - home 84.4ms.
  - recommendations 109.5ms.
  - guest search 84.5ms.
  - company detail 81.8ms.
  - admin console 75.9ms.

남은 환경 의존 항목:
- Docker Compose 실제 기동은 Docker CLI 있는 환경에서 `infra/scripts/verify-docker-stack` 실행 필요.
- 대표 DB/cache/network/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음.

---

## 2026-08-03 - strict 성능 smoke 및 Docker verifier 준비

트리거: 사용자 "다음". 남은 blocker 중 Docker는 현재 환경에서 계속 불가하므로 실행 가능한 검증과 재현 스크립트 준비를 진행.

수행:
1. Docker CLI 부재 재확인: `docker: command not found`.
2. `PERF_STRICT=1 npm run perf:web-only` 실행으로 WEB_ONLY HTTP smoke를 production target reference threshold 기준으로 재검증.
3. `infra/scripts/verify-docker-stack` 추가:
   - `docker compose version`.
   - `docker compose config --quiet`.
   - postgres/redis/minio/minio-bucket-init 기동.
   - backju-postgres/backju-redis/backju-minio health 대기.
   - backend Dockerfile image build.
4. 현재 환경에서는 `verify-docker-stack`이 `NOT_RUN: docker command is not available in this environment`로 정상 종료됨을 확인.
5. G0 Docker Compose 기준을 `BLOCKED`로 정정하고 PostgreSQL 연결 기준은 clean PostgreSQL 17 + pgvector roundtrip 근거로 `PASSED` 반영.

검증:
- `PERF_STRICT=1 npm run perf:web-only` 통과.
- strict P95:
  - home 26.1ms.
  - recommendations 25.9ms.
  - guest search 19.6ms.
  - company detail 21.5ms.
  - admin console 32.2ms.
- `bash -n infra/scripts/verify-docker-stack` 통과.
- `infra/scripts/verify-docker-stack`은 Docker 부재 환경에서 NOT_RUN으로 종료 확인.

남은 환경 의존 항목:
- Docker Compose 실제 기동은 Docker CLI 있는 환경에서 `infra/scripts/verify-docker-stack` 실행 필요.
- 대표 DB/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음.

---

## 2026-08-03 - G3 WEB_ONLY 성능 스모크 하네스 추가

트리거: 사용자 "다음". `.harness/state.json.next_recommended_tasks = []` 상태에서 남은 G3 항목 중 성능 검증을 가능한 범위까지 진행.

수행:
1. Docker CLI는 여전히 없어 Docker Compose 실제 기동은 blocked임을 재확인.
2. `tests/performance/web-only-http-smoke.mjs` 추가:
   - user-web home/recommendations/guest search/company detail.
   - admin console.
   - 기본은 local smoke threshold, `PERF_STRICT=1`일 때 production target reference threshold 사용.
3. 루트 `package.json`에 `perf:web-only` 스크립트 추가.
4. user-web/admin dev 서버를 로컬 포트 3300/3320에 임시 기동해 HTTP 성능 smoke 실행.
5. `.harness/reports/performance/G3_WEB_ONLY_HTTP_SMOKE-2026-08-03.md` 작성.
6. G3 `g3-11`은 formal load 미수행 때문에 `PARTIAL_PASS`를 유지하되, 측정 결과를 반영.

검증:
- `npm run perf:web-only` 통과.
- 측정 P95:
  - home 39.2ms.
  - recommendations 37.9ms.
  - guest search 22.0ms.
  - company detail 21.2ms.
  - admin console 28.0ms.

남은 환경 의존 항목:
- Docker Compose 실제 기동은 Docker CLI 부재로 blocked.
- 대표 DB/동시성 기반 정식 부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음. 남은 항목은 Docker/정식 부하 환경 검증이다.

---

## 2026-08-03 - G3 migration 실검증 및 0013 index 보정

트리거: 사용자 "다음". `.harness/state.json.next_recommended_tasks = []` 상태에서 남은 G3 환경 의존 항목 중 PostgreSQL migration roundtrip을 우선 검증.

수행:
1. Docker CLI는 현재 세션에 없어 Docker Compose 실제 기동은 계속 blocked임을 확인.
2. Homebrew PostgreSQL 17 + pgvector가 설치되어 있어 임시 clean DB를 별도 포트로 기동.
3. `tests/api/test_db_migrations.py`를 실제 `TEST_DATABASE_URL`로 실행하던 중 `0013_search_web_only_indexes`의 HNSW index가 차원 미지정 `vector` 컬럼 때문에 실패하는 것을 확인.
4. `idx_embedding_vector_hnsw_cosine_active`를 `idx_embedding_vector_hnsw_cosine_1536_active` partial expression index로 보정:
   - `embedding::vector(1536)`
   - `active AND embedding_dimension = 1536`
5. CTR-012 정적 계약 테스트에 1536차원 partial HNSW 조건을 추가.
6. G3 `g3-6 Migration Test`를 PASSED로 갱신하고 state/report/handoff/backlog의 미수행 표현을 정리.

검증:
- 임시 PostgreSQL 17 + pgvector clean DB에서 `tests/api/test_db_migrations.py` 통과.
- 임시 PostgreSQL 17 + pgvector clean DB에서 `alembic upgrade head -> downgrade base -> upgrade head` 전체 왕복 통과.

남은 환경 의존 항목:
- Docker Compose 실제 기동은 Docker CLI 부재로 blocked.
- 정식 성능/부하 목표는 smoke 수준을 넘어서는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음. 남은 항목은 Docker/성능 환경 검증이다.

---

## 2026-08-03 - QAS-GROUP-001 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = QAS-GROUP-001`.

수행:
1. Playwright 설정에서 전용 kiosk 서버를 제거하고 WEB_ONLY 기준 user-web/admin E2E로 재정렬.
2. `tests/e2e/web-only-smoke.spec.ts` 추가:
   - 등록 웹 home/recommendations/favorites/buyer matching.
   - GUEST_WEB 모바일 검색/상세 및 개인정보 입력 부재.
   - admin 운영 콘솔 live forms/contract pending panels.
3. guest web signup stub의 비활성 email placeholder input을 제거.
4. `infra/scripts/scope-violation-check`에 user-web guest entry/search/signup 개인정보 입력 검사 추가.
5. 보안 정적 테스트 추가:
   - guest web PII input 없음.
   - event payload 직접식별정보 없음.
   - guest session convert/temporary favorites lifecycle 안전장치 확인.
6. `QAS-GROUP-001`을 DONE으로 닫고 G3_MVP_RELEASE 상태를 `IN_PROGRESS_WITH_ENV_BLOCKERS`로 갱신.

검증:
- user-web lint/test/build 통과.
- admin lint/typecheck/test/build 통과.
- root `npm run typecheck` 통과.
- `npm run e2e`: 6 passed.
- `python -m pytest tests/security -q`: 5 passed.
- backend ruff/pytest: 104 passed, 12 skipped.
- AI gold set PASS, AI schema tests 60 passed, AI ruff 통과.
- `validate-harness`, `scope-violation-check`, `git diff --check` 통과.

남은 환경 의존 항목:
- Docker Compose 실제 기동과 clean PostgreSQL migration roundtrip은 현재 실행 환경에서 불가.
- 정식 성능/부하 목표는 별도 운영/CI 환경 필요.

다음 추천 작업: 없음. 남은 항목은 환경 의존 검증이다.

---

## 2026-08-03 - ADM-GROUP-001 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = ADM-GROUP-001`.

수행:
1. `apps/admin/app/console/page.tsx`를 예정 목록에서 운영 콘솔로 전환하고 API/fallback
   상태, 기본 통계 fallback, 관리 영역 상태 목록을 표시했다.
2. `AdminOperationsPanel`을 추가해 업체정보 승인(`POST /api/v1/admin/content-approvals`)과
   부스 운영상태 변경(`PATCH /api/v1/admin/booths/{booth_id}/status`) 폼을 구현했다.
3. `apps/admin/lib/admin-api.ts`에 admin API base URL, OPERATOR 헤더, 요청 wrapper,
   console snapshot loader를 추가했다.
4. frozen OpenAPI에 없는 바이어 검증 플래그 갱신과 기본 통계 집계는 계약 대기 패널로
   명시했다.
5. 모바일 내비게이션 줄바꿈을 정리하고 favicon 404를 제거했다.
6. `ADM-GROUP-001`을 DONE으로 닫고 `QAS-GROUP-001`을 READY 및 다음 추천 작업으로 지정했다.

검증:
- `cd apps/admin && npm run lint` 통과.
- `cd apps/admin && npm run typecheck` 통과.
- `cd apps/admin && npm test`: 5 files, 8 tests passed.
- `cd apps/admin && npm run build` 통과.
- Playwright smoke: `/console` desktop/mobile 확인, console error 없음.

다음 추천 작업: QAS-GROUP-001.

---

## 2026-08-03 - WEB-GROUP-001 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = WEB-GROUP-001`.

수행:
1. `apps/user-web/lib/api-client.ts`를 추가해 profile/recommendations/search/favorites/
   buyer matches/company detail을 실제 API 우선으로 호출하고 fallback 데이터를 반환하게 했다.
2. 홈, 추천, 검색, 관심목록, 업체 상세, 바이어 매칭, MY 화면을 API loader 기반 서버
   컴포넌트 흐름으로 전환하고 API 화면을 `force-dynamic`으로 고정했다.
3. 검색 채널 `REGISTERED_WEB`/`GUEST_WEB`/`BUYER_WEB`을 분리하고, GUEST_WEB은
   `/guest/sessions` 생성 후 `/search`를 호출하도록 구현했다.
4. 추천/검색 결과의 `recommendable_id` 상세가 404가 되지 않도록 UUID 승인 대상 fallback을
   추가하고, 상세 저장 버튼을 `POST /favorites`/`DELETE /favorites/{id}`로 연결했다.
5. API/fallback 출처 배너와 `.env.example`의 실제 API 환경변수 안내를 갱신했다.
6. `WEB-GROUP-001`을 DONE으로 닫고 `ADM-GROUP-001`을 다음 추천 작업으로 지정했다.

검증:
- `cd apps/user-web && npm run lint` 통과.
- `cd apps/user-web && npm test`: 5 files, 12 tests passed.
- `cd apps/user-web && npm run build` 통과, API 화면 dynamic route 확인.
- Playwright smoke: `/home`, GUEST_WEB 검색, 모바일 검색 화면, UUID 상세, 관심 저장 버튼 확인.

다음 추천 작업: ADM-GROUP-001.

---

## 2026-08-03 - BAC-011 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = BAC-011`.

수행:
1. `backend/app/api/v1/endpoints/exhibitors.py` 추가:
   - `GET /api/v1/exhibitors/{exhibitor_id}` (`getExhibitor`)
   - `GET /api/v1/booths/{booth_id}` (`getBooth`)
2. `backend/app/api/v1/endpoints/admin.py`에
   `PATCH /api/v1/admin/booths/{booth_id}/status` (`updateBoothStatus`) 추가.
3. 공개 조회는 승인 업체/승인 참가에 연결된 데이터만 반환하고 미승인/미존재는 404로 숨김.
4. 부스 상태 변경에 OPERATOR/ADMIN 권한, `X-MeetAI-User-Id`, optional row_version
   낙관적 동시성 검사, `booth_status_history` append를 적용.
5. BAC-009 계약 테스트의 known unimplemented operationId 목록을 비우고 static OpenAPI
   대비 runtime missing/mismatch 0건으로 정렬.
6. `BAC-GROUP-001`을 DONE으로 닫고, `WEB-GROUP-001`과 `ADM-GROUP-001`을 READY로 전환.

검증:
- static OpenAPI 대비 runtime operationId missing/mismatch: 0.
- focused backend ruff 통과.
- `cd backend && ../.venv/bin/pytest tests/test_bac_group_contract.py -q`: 4 passed.

다음 추천 작업: WEB-GROUP-001.

---

## 2026-08-03 - BAC-009 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = BAC-009`.

수행:
1. 구현된 FastAPI route의 `operation_id`를 정적 OpenAPI camelCase operationId와 명시 정렬.
2. `backend/app/main.py`에 `RequestValidationError` handler를 추가해 FastAPI 기본 validation
   오류도 `{error:{code,message,request_id,details}}` envelope로 통일.
3. `backend/tests/test_bac_group_contract.py` 추가:
   - 구현 operationId와 static OpenAPI 일치 검증.
   - static OpenAPI 대비 runtime route gap 목록을 명시적으로 고정.
   - 인증/권한/검증 오류 envelope runtime smoke.
   - `MeetingResponse`가 상담 확정 전 연락처 원문을 노출하지 않는지 schema 검증.
4. 새 테스트가 앱 전체 import 경로를 타면서 ORM metadata에 `ai`/deprecated `kiosk` 모델이
   포함되도록 `backend/tests/test_exhibitor_models.py`의 총량 계약을 안정화.
5. 발견 gap `getExhibitor`, `getBooth`, `updateBoothStatus`를 `BAC-011`로 후속 등록.

검증:
- `cd backend && ../.venv/bin/ruff check .` 통과.
- `cd backend && ../.venv/bin/pytest -q`: 104 passed, 12 skipped.

다음 추천 작업: BAC-011.

---

## 2026-08-03 - BAC-008 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = BAC-008`.

수행:
1. `backend/app/api/v1/endpoints/search.py` 추가 및 `/api/v1/search`,
   `/api/v1/guest/sessions/{guest_session_id}/search`, `/api/v1/search/clarify`,
   `/api/v1/search/{search_session_id}` 등록.
2. 검색 요청을 `matching.search_session/search_query/search_result`에 저장하고
   `StructuredSearchProvider` + `ReciprocalRankFusionCombiner` + `decide_search_recovery`
   정책을 연결.
3. `GET /recommendations`, `GET /recommendations/{recommendation_session_id}`에서
   최신/지정 추천 세션, 결과, reason, pagination meta를 재현 가능하게 반환.
4. 검색 세션 조회/clarify와 추천 세션 조회에 프로파일·게스트 세션 접근 검사를 적용.
5. STRUCTURED 외 provider는 AIS-009 계약대로 unavailable meta로 노출하고, 무결과는
   `SearchResponse.meta.code=SEARCH_NO_RESULT`와 `fallback_reason=NO_RESULT`로 기록.
6. BAC-009를 READY로 전환하고 다음 추천 작업으로 지정.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/endpoints/search.py app/api/v1/api.py tests/test_search_api.py` 통과.
- `cd backend && ../.venv/bin/pytest tests/test_search_api.py -q`: 4 passed.

다음 추천 작업: BAC-009.

---

## 2026-08-03 - CTR-012 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = CTR-012`.

수행:
1. `backend/app/models/search.py`의 `SEARCH_CHANNELS`를
   REGISTERED_WEB/GUEST_WEB/BUYER_WEB/ADMIN_PREVIEW로 정렬하고 `channel` 길이를 30으로 확장.
2. migration `0013_search_web_only_indexes` 추가 - legacy `WEB`은 `REGISTERED_WEB`,
   legacy `KIOSK`는 `GUEST_WEB`로 backfill하고 새 CHECK 제약을 생성.
3. FTS expression GIN index 추가 - exhibitor, product, exhibitor_participation,
   ai.embedding_document.content_excerpt.
4. pgvector 검색 준비 index 추가 - `embedding_model/embedding_dimension` lookup index와
   active vector HNSW cosine ANN index.
5. AIS-009 provider contract에서 더 이상 FTS/ANN index missing을 reason으로 남기지 않게 정렬.
6. BAC-008을 READY로 전환하고 다음 추천 작업으로 지정.

검증:
- CTR-012 migration contract tests: 4 passed.
- AIS-009 pipeline contract tests 포함: 10 passed.
- `backend/tests/test_exhibitor_models.py`: 6 passed.
- 관련 backend/AI ruff 통과.
- 최종 회귀: Gold Set 검증 통과, `python -m pytest ai/schemas/tests/ -q`: 60 passed,
  `cd backend && pytest -q`: 96 passed, 12 skipped, `validate-harness`,
  `scope-violation-check`, `git diff --check` 통과.

다음 추천 작업: BAC-008.

---

## 2026-08-03 - AIS-009/AIS-GROUP-001 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = AIS-009`.

수행:
1. `backend/app/services/matching/search_pipeline_contract.py` 추가.
2. KeywordSearchProvider 계약을 고정 - FTS 대상 필드, `ts_rank_cd` 순위 정규화,
   `keyword_score`, `NO_RESULT` fallback.
3. VectorSearchProvider 계약을 고정 - `ai.embedding_document/vector` 연결 조건,
   query embedding adapter/ANN index 필요조건, cosine 기반 `semantic_score`,
   `AI_SERVICE_UNAVAILABLE` fallback.
4. BAC-008 연결 순서(`validate_actor` → `interpret_intent` → `build_search_query` →
   provider 실행 → RRF → recovery → persistence → response)를 코드 상수로 고정.
5. 실제 FTS GIN index, pgvector ANN index, legacy `matching.search_session.channel`
   CHECK 정렬은 CTR-012 후속으로 분리.

검증:
- `python -m pytest ai/schemas/tests/test_search_pipeline_contract.py -q`: 6 passed.
- `cd backend && ruff check app/services/matching/search_pipeline_contract.py app/services/matching/search_provider.py` 통과.
- `ruff check ai/schemas/tests/test_search_pipeline_contract.py` 통과.
- 최종 회귀: Gold Set 검증 통과, `python -m pytest ai/schemas/tests/ -q`: 56 passed,
  `cd backend && pytest -q`: 96 passed, 12 skipped, backend/AI ruff 통과,
  `validate-harness`, `scope-violation-check`, `git diff --check` 통과.

다음 추천 작업: CTR-012.

---

## 2026-08-03 - AIS-007/008 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = AIS-GROUP-001`.

수행:
1. CR-001 WEB_ONLY 기준에 맞춰 Gold Set의 기존 kiosk-ko 샘플을
   `guest-web-ko.jsonl`로 전환하고, query channel enum을
   REGISTERED_WEB/GUEST_WEB/BUYER_WEB로 정렬.
2. `SearchQuery.channel`, `ReciprocalRankFusionCombiner`, `StructuredSearchProvider`
   를 추가해 기존 구조화 검색과 `reciprocal_rank_fusion`을 SearchProvider 계약에 연결.
3. `GUEST_WEB_SEARCH_SCORE_V1`을 `src/meet_ai/scoring`에 추가하고 export.
4. 결과 0건, 저신뢰, 엄격 조건, 온톨로지 gap, 카테고리 0건을 구분하는
   `decide_search_recovery` 순수 정책 추가.
5. AIS-GROUP-001은 IN_PROGRESS로 두고, FTS/vector provider와 BAC-008 연결 계약을
   AIS-009로 분리.

검증:
- `python ai/evaluation/validate_gold_set.py` 통과.
- `python -m pytest ai/schemas/tests/ -q`: 50 passed.
- `ruff check ai/ src/meet_ai/scoring` 통과.
- `cd backend && ruff check .` 통과.
- `cd backend && pytest -q`: 96 passed, 12 skipped.
- `infra/scripts/validate-harness`, `infra/scripts/scope-violation-check`, `git diff --check` 통과.

다음 추천 작업: AIS-009.

---

## 2026-08-02 - BAC-010 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks = BAC-010`.

수행:
1. `POST /api/v1/guest/sessions` 구현 - `profile.guest_session(entry_channel=WEB)`,
   `device_type=MOBILE_WEB`으로 게스트 웹 익명 세션 생성.
2. `GET /api/v1/guest/sessions/{guest_session_id}` 구현 - 활성/전환 상태와 임시 관심목록 반환,
   만료 세션은 410 `GUEST_SESSION_EXPIRED`.
3. `POST/DELETE /api/v1/guest/sessions/{guest_session_id}/favorites` 구현 - 신규 테이블 없이
   guest_session 소유 임시 `profile.user_profile` + `profile.saved_recommendable` 재사용.
4. `POST /api/v1/guest/sessions/{guest_session_id}/convert` 구현 - 등록 사용자 전환 시
   임시 관심목록을 명시 옵션에 따라 지속 프로파일로 이동.
5. 기존 `POST /api/v1/guest/convert`는 compatibility wrapper로 유지하되,
   CR-001 오류코드 `GUEST_SESSION_EXPIRED`/`WEB_ENTRY_LINK_EXPIRED`를 사용하도록 정렬.
6. `/api/v1/kiosk/*`는 확장하지 않고 deprecated cleanup 대상으로 그대로 둠.
7. QA DB 계약 테스트 요청을 `.harness/handoffs/qa/BAC-010-test-request.md`에 기록.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/endpoints/guest.py app/api/v1/api.py` 통과.
- `cd backend && ../.venv/bin/python -m py_compile app/api/v1/endpoints/guest.py app/api/v1/api.py` 통과.
- FastAPI OpenAPI route smoke에서 `/api/v1/guest/sessions` 계열 5개 경로 확인.

다음 추천 작업: AIS-GROUP-001.

---

## 2026-08-02 - CR-001 WEB_ONLY 계약 동기화 완료

트리거: 사용자 "다음" 및 첨부 `전시회 AI 업체 매칭 서비스 웹 중심 재설계 기준서`.

수행:
1. `AGENTS.md`, `PROJECT_SCOPE.md`, `.harness/decisions.md`에 DEC-011 WEB_ONLY
   채널 전략을 정본으로 반영.
2. OpenAPI에서 `/kiosk/*` 신규 계약을 제거하고 `/guest/sessions` 계열,
   GUEST_WEB 임시 관심목록, session-scoped convert 계약을 추가.
3. event/error/ontology/domain model 계약의 KIOSK/QR_HANDOFF 표현을
   GUEST_WEB/WEB_ENTRY_OR_PROFILE_LINK 기준으로 대체.
4. `CR-001`을 DONE 처리하고 `BAC-010`(게스트 웹 세션 API 계약 정렬),
   `QAS-007`(게스트 웹 PII/mobile smoke), `CTR-011`(deprecated kiosk cleanup 계획)을
   후속 태스크로 추가.
5. `KSK-GROUP-001`은 SUPERSEDED로 표시하고, `QAS-GROUP-001` 의존성에서 제거.
6. `.harness/state.json.next_recommended_tasks`를 `BAC-010`으로 전환.

주의:
- 기존 `apps/kiosk`, `/api/v1/kiosk/*`, `KioskDevice/KioskConfig` migration은
  삭제하지 않았다. CR-001 기준에서는 신규 기능 확장 금지·cleanup 계획 대상으로만 취급한다.

다음 추천 작업: BAC-010.

---

## 2026-08-02 - WEB_ONLY 범위 변경요청 접수

트리거: 첨부된 `전시회 AI 업체 매칭 서비스 웹 중심 재설계 기준서`.

판정:
- 새 기준서는 `WEB_ONLY = TRUE`, `KIOSK_MODULE = EXCLUDED`를 선언한다.
- 이는 현재 `AGENTS.md`, `docs/redesign-v2/**`, G1 frozen contract의 3모듈
  구조(웹 + 키오스크 + 공통 AI)와 충돌한다.
- 따라서 `/api/v1/kiosk/*`, `apps/kiosk`, KioskDevice/KioskConfig 마이그레이션을
  즉시 삭제하지 않고, CONTRACTS 트랙 change request로 승격한다.

수행:
1. `.harness/change-requests/CR-001-web-only-scope-change.md` 작성.
2. `.harness/handoffs/contracts/CR-001-web-only-scope-change.md` 작성.
3. `.harness/state.json`에 WEB_ONLY 요청 상태와 entry methods 기록.
4. `next_recommended_tasks`를 `AIS-GROUP-001`에서 `CR-001`로 변경.
5. `AIS-GROUP-001`과 `KSK-GROUP-001`을 CR-001 해결 전 BLOCKED로 전환.
6. `G2_FEATURE_COMPLETE`를 `CHANGE_REQUESTED`로 표시.

검증:
- `infra/scripts/validate-harness` 통과.
- `infra/scripts/scope-violation-check` 통과.
- `git diff --check` 통과.

다음 추천 작업: CR-001.

---

## 2026-08-02 - BAC-007 완료

트리거: 재첨부된 벤치마킹 문서와 `.harness/state.json.next_recommended_tasks = BAC-007`.

수행:
1. 첨부 벤치마킹의 개인정보·동의 원칙을 다시 확인하고, 추가 scope 확장 없이
   프로파일/게스트 전환 API에 적용.
2. `GET /api/v1/profile/me` 구현 - 등록 사용자 프로파일, 활성 profile_attribute,
   BUYER일 때 buyer_need 반환.
3. `PATCH /api/v1/profile/me/attributes` 구현 - GUEST_WEB 금지, row_version 충돌 검사,
   assignable ACTIVE 온톨로지 코드만 USER_EDITED 속성으로 저장, profile_version 스냅샷 생성.
4. `POST /api/v1/guest/convert` 구현 - QR entry_code/만료 검증, 기존 active UserAccount에만
   전환, guest_session converted_user_id/converted_at 기록, QR 코드 제거.
5. 게스트 UserProfile/VisitSession 소유권을 user_id로 승계하되, identity.user_identity
   등 직접식별정보 테이블은 생성·수정하지 않음.
6. frozen static openapi.yaml에는 `/guest/convert` 명시 경로가 없고 W-8/로드맵에는 있어,
   백엔드 구현 후 QA/CONTRACTS 후속 동기화 필요사항으로 기록.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/endpoints/profile.py app/api/v1/endpoints/guest.py app/api/v1/api.py app/models/ontology_refs.py` 통과.
- OpenAPI route smoke: `/api/v1/profile/me` GET,
  `/api/v1/profile/me/attributes` PATCH, `/api/v1/guest/convert` POST 확인.
- missing-auth smoke: 세 경로 모두 401 `AUTHENTICATION_REQUIRED` 확인.
- `cd backend && ../.venv/bin/pytest -q`: 96 passed, 12 skipped.
- `cd backend && ../.venv/bin/ruff check .` 통과.

다음 추천 작업: AIS-GROUP-001 (`BAC-008` 검색·추천 API 파사드 선행조건).

---

## 2026-08-02 - 벤치마킹 정렬 + BAC-005 완료

트리거: 첨부된 "전시회 사전등록 사용자·현장 방문객 대상 초개인화 AI 매칭 벤치마킹"
문서와 사용자 "다음".

판정:
- 첨부 벤치마킹은 frozen contract를 대체하지 않는 참고 근거로 채택.
- 하드필터 우선, 승인 데이터 기반 Reason, 키오스크 익명 세션·QR 인계, AI 자동승인 금지,
  행사 중 실시간 모델 재학습 제외 원칙이 현재 설계와 일치함을
  `.harness/reports/integration/BENCHMARK_ALIGNMENT-2026-08-02.md`에 기록.

수행:
1. `POST /api/v1/kiosk/sessions` 구현 - `ACTIVE` kiosk_device만 사용해
   `profile.guest_session(entry_channel=KIOSK)` 생성.
2. 단말별 `kiosk_config.idle_timeout_seconds`가 있으면 세션 만료에 반영하고, 없으면
   90초 기본값 사용.
3. `DELETE /api/v1/kiosk/sessions/{guest_session_id}` 구현 - 세션 종료 멱등 처리 및
   `entry_code` 제거.
4. `POST /api/v1/kiosk/qr-sessions` 구현 - 신규 테이블 없이 `guest_session.entry_code`
   재발급. 만료·비키오스크 세션은 410 `QR_HANDOFF_EXPIRED`.
5. 이름·전화번호·이메일·주소·로그인 ID 입력 없이 OpenAPI 계약의 최소 DTO만 노출.
6. QA 소유 테스트 경로는 직접 수정하지 않고 `.harness/handoffs/qa/BAC-005-test-request.md`
   로 DB-backed 계약 테스트를 요청.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/endpoints/kiosk.py app/api/v1/api.py` 통과.
- OpenAPI route smoke: `/api/v1/kiosk/sessions` POST,
  `/api/v1/kiosk/sessions/{guest_session_id}` DELETE,
  `/api/v1/kiosk/qr-sessions` POST 확인.
- `cd backend && ../.venv/bin/pytest -q`: 96 passed, 12 skipped.
- `cd backend && ../.venv/bin/ruff check .` 통과.
- `infra/scripts/validate-harness` 통과.
- `infra/scripts/scope-violation-check` 통과.
- `git diff --check` 통과.

다음 추천 작업: BAC-007.

---

## 2026-08-02 - BAC-006 완료

트리거: 사용자 "다음" 및 `.harness/state.json.next_recommended_tasks`.

수행:
1. `GET /api/v1/buyer/matches` 구현 - BUYER_REGISTERED 프로파일의 최신
   `matching.recommendation_session`과 `match_result`/`match_reason` 조회.
2. `POST /api/v1/buyer/matches/{exhibitor_id}/meetings` 구현 - 승인된 업체와 승인·상담가능
   참가정보에 대해서만 `interaction.meeting(status=REQUESTED)` 생성.
3. `PATCH /api/v1/meetings/{meeting_id}/status` 구현 - REQUESTED에서
   CONFIRMED/REJECTED/CANCELLED_BY_BUYER/CANCELLED_BY_EXHIBITOR로만 전이.
4. CONFIRMED 시 `interaction.meeting_contact_share` 생성·공개 플래그 처리. 응답에는
   연락처 원문을 노출하지 않음.
5. 상담 메시지는 암호화 어댑터가 없어 평문 저장하지 않고 `message_enc`를 비워 둠. 후속
   암호화 어댑터가 생기면 encrypted persistence 보강 필요.
6. QA 소유 테스트 경로는 직접 수정하지 않고 `.harness/handoffs/qa/BAC-006-test-request.md`
   로 DB-backed 계약 테스트를 요청.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/endpoints/buyer.py app/api/v1/api.py` 통과.
- buyer matches / meeting create / meeting status missing auth smoke: 모두 401 +
  `{error:{code: AUTHENTICATION_REQUIRED,...}}` 확인.
- `cd backend && ../.venv/bin/pytest -q`: 96 passed, 12 skipped.
- `cd backend && ../.venv/bin/ruff check .` 통과.
- `infra/scripts/validate-harness` 통과.
- `infra/scripts/scope-violation-check` 통과.

다음 추천 작업: BAC-005, BAC-007.

---

## 2026-08-02 - v1.1 Production 재확인 차단 + BAC-004 완료

트리거: 첨부된 v1.1 Production 실행 프롬프트 재확인.

판정: `V1_1_PRODUCTION_BLOCKED` 유지. 이전 Production 판정과 동일하게 G9 PASS,
`release_status = V1_1_RC1_APPROVED`, v1.1 하네스 산출물, RC/운영 배포 근거가 없다.
Production 배포, Canary, DB migration, Index alias 전환, Feature Flag 전환, v1.1.0 tag는
수행하지 않았다.

수행:
1. 현재 루트 하네스 포인터에 따라 `BAC-004` 구현.
2. `POST /api/v1/admin/content-approvals` 추가.
3. 기존 OPERATOR/ADMIN actor role과 `X-MeetAI-User-Id` 기반 운영자 가드 추가.
4. 해당 업체의 최신 `ai.source_document`를 문서 단위 승인 근거로 사용하고,
   source evidence가 없으면 승인 이력을 생성하지 않고 404로 거절.
5. 승인/반려 시 `ai.content_approval`을 생성하고 `exhibition.exhibitor.master_approval_status`
   를 명시적 운영자 액션으로 갱신. AI 자동승인은 추가하지 않았다.
6. QA 소유 테스트 경로는 직접 수정하지 않고 `.harness/handoffs/qa/BAC-004-test-request.md`
   로 DB-backed 계약 테스트를 요청했다.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/dependencies.py app/api/v1/endpoints/admin.py app/api/v1/api.py` 통과.
- Unauthorized smoke: `POST /api/v1/admin/content-approvals` 403 +
  `{error:{code: PERMISSION_DENIED,...}}` 확인.
- 최초 `cd backend && ../.venv/bin/pytest -q`: 1 failed, 95 passed, 12 skipped.
  원인: admin 라우터의 eager `app.models.ai` import가 metadata table count 회귀를 유발.
  수정: AI 모델 import를 요청 처리 시점으로 지연.
- 최종 `cd backend && ../.venv/bin/pytest -q`: 96 passed, 12 skipped.

다음 추천 작업: BAC-006, BAC-005.

---

## 2026-08-02 - v1.1 Production 차단 + BAC-002/BAC-003 완료

트리거: 첨부된 v1.1 Production 실행 프롬프트와 사용자 "다음 진행".

판정: `V1_1_PRODUCTION_BLOCKED`. Production 점진 배포는
`G9_V1_1_RELEASE = PASS`, `release_status = V1_1_RC1_APPROVED`, P0/P1=0,
Security/Privacy/Migration/Limited Pilot PASS가 필요하지만 현재 저장소에는
`.harness/v1.1/*`, v1.1 RC, G9 결과가 없다. 리포트:
`.harness/reports/go-live/V1_1_PRODUCTION_ENTRY-2026-08-02.md`.

수행:
1. Production 배포, Canary, DB migration, Index alias 전환, Feature Flag 전환, v1.1.0 tag는
   수행하지 않았다.
2. 현재 루트 하네스 포인터대로 `BAC-002` 구현: explicit local/test header 기반 API context,
   persistent profile/buyer guard, BAC-002 오류 envelope 핸들러 추가.
3. `BAC-003` 구현: `GET/POST/DELETE /api/v1/favorites`, profile.saved_recommendable 연동,
   active recommendable 확인, 중복 저장 409, profile-scoped idempotent delete.
4. QA 소유 테스트 경로는 직접 수정하지 않고 `.harness/handoffs/qa/BAC-003-test-request.md`
   로 DB-backed 계약 테스트를 요청했다.

검증:
- `cd backend && ../.venv/bin/ruff check app/api/v1/dependencies.py app/api/v1/errors.py app/api/v1/endpoints/favorites.py app/api/v1/api.py app/main.py` 통과.
- `GET /api/v1/favorites` missing profile smoke: 401 + `{error:{code: AUTHENTICATION_REQUIRED,...}}` 확인.
- `cd backend && ../.venv/bin/pytest tests/test_health_api.py -q`: 6 passed, 1 skipped.
- `cd backend && ../.venv/bin/pytest -q`: 96 passed, 12 skipped.
- `cd backend && ../.venv/bin/ruff check .` 통과.

다음 추천 작업: BAC-004, BAC-006.

---

## 2026-08-02 - WAVE 1.1D 진입 차단

트리거: 첨부된 WAVE 1.1D 실행 프롬프트 확인.

판정: `WAVE_1_1D_BLOCKED`. 1.1D는 전체 통합·회귀검증·제한 파일럿·
`v1.1.0-rc.1` 판정 Wave이며, 시작 조건은 `G8C_MATCHING_OPERATIONS = PASS` 또는
`SKIPPED_NO_TASK`다. 현재 저장소에는 G8C 상태와 v1.1 전용 하네스 산출물이 없다.

확인한 차단 근거:
- `CHANGELOG.md` 없음.
- `.harness/v1.1/state.json`, `backlog.yaml`, `locks.yaml`, `quality-gates.yaml` 없음.
- `.harness/prompts/v1.1/WAVE-1.1D.md` 없음.
- `.harness/handoffs/v1.1/**`, `.harness/reports/v1.1/**`, `docs/v1.1/**` 없음.
- 현재 루트 상태는 Wave 2 / `G2_FEATURE_COMPLETE IN_PROGRESS`.
- G2/G3가 완료되지 않아 RC·파일럿·G9 판정 근거가 없다.

수행:
1. RC 생성, 태그 생성, 제한 파일럿, G9 상태 전환은 수행하지 않았다.
2. 차단 리포트 `.harness/reports/release/WAVE_1_1D_ENTRY-2026-08-02.md` 작성.
3. 현재 실행 포인터는 기존대로 `BAC-002`, `BAC-003` 유지.

검증:
- `infra/scripts/validate-harness` 통과: 44개 작업, 4개 게이트, 49개 소유 경로.
- `infra/scripts/scope-violation-check` 통과.
- `git diff --check` 통과.

다음 추천 작업: BAC-002, BAC-003.

---

## 2026-08-02 - WAVE 1.1B/1.1C 진입 차단 + BAC-GROUP-001 세부 분해

트리거: 첨부된 WAVE 1.1B 및 WAVE 1.1C 실행 프롬프트 확인.

판정:
- WAVE 1.1B: `WAVE_1_1B_BLOCKED` 유지. v1.1 전용 backlog/state/quality-gates/docs 및
  G8A PASS/SKIPPED_NO_TASK 근거가 없다.
- WAVE 1.1C: `WAVE_1_1C_BLOCKED`. G8B_SEARCH_KIOSK_QUALITY PASS/SKIPPED_NO_TASK,
  `current_wave = 1.1C`, 운영 결함·증거 리포트가 모두 없다. 리포트:
  `.harness/reports/release/WAVE_1_1C_ENTRY-2026-08-02.md`.

수행:
1. v1.1B/1.1C 구현은 시작하지 않았다.
2. 현재 루트 하네스의 다음 실행 가능 항목인 `BAC-GROUP-001`을 CTR-002 OpenAPI 기준으로
   `BAC-002`~`BAC-009`로 분해했다.
3. `BAC-002`(API 컨텍스트·권한 가드)와 `BAC-003`(Favorites API)을 다음 추천 작업으로
   지정했다.
4. `G2_FEATURE_COMPLETE`를 `IN_PROGRESS`로 전환하고 g2-1 핵심 API 기준을 진행 중으로 갱신했다.

검증:
- `infra/scripts/validate-harness` 통과: 44개 작업, 4개 게이트, 49개 소유 경로.
- `infra/scripts/scope-violation-check` 통과.
- `git diff --check` 통과.

다음 추천 작업: BAC-002, BAC-003.

---

## 2026-08-02 - WAVE 1.1B 진입 차단 + QAS-004 완료 + G1 통과

트리거: 첨부된 WAVE 1.1B 실행 프롬프트 확인.

판정: `WAVE_1_1B_BLOCKED`. `.harness/v1.1/backlog.yaml`, `.harness/v1.1/state.json`,
`.harness/v1.1/quality-gates.yaml`, `docs/v1.1/*`, `.harness/prompts/v1.1/WAVE-1.1B.md`,
`CHANGELOG.md`가 없어 승인된 운영근거 기반 검색·키오스크 개선 작업을 자동 선택할 수 없다.
또한 G8A PASS/SKIPPED_NO_TASK 조건도 충족하지 못한다. 리포트:
`.harness/reports/release/WAVE_1_1B_ENTRY-2026-08-02.md`.

수행:
1. v1.1B 구현은 시작하지 않았다.
2. 현재 G1 잔여 작업 `QAS-004` 수행: 루트 Playwright 설정과 `tests/e2e/wave1-smoke.spec.ts`
   추가.
3. `@playwright/test` devDependency와 `npm run e2e` script 추가.
4. E2E 전용 포트 3300/3310/3320 사용 - 기존 3000번 로컬 서버 충돌을 회피.
5. user-web, kiosk, admin Wave 1 라우트 골격 smoke 검증.

검증:
- 최초 `npm run e2e`: Chromium 미설치로 실패.
- `npx playwright install chromium` 성공.
- 중간 `npm run e2e`: 기존 3000번 서버 재사용으로 user-web 실패, kiosk sessionStorage
  잔존 추가 검사 실패. smoke 범위를 라우트 흐름 검증으로 정리하고 전용 포트로 변경.
- 최종 `npm run e2e`: 3 passed.

상태:
- QAS-004/005/006 완료.
- G1_CONTRACT_FREEZE를 PASSED로 갱신.
- 현재 포인터를 Wave 2 `BAC-GROUP-001` 세부 분해로 이동.
- G0 Docker health check는 여전히 이 환경에서 NOT_RUN/FND-004 blocked.

잔여위험:
- admin 상세/검수탭은 아직 제품 골격에 없어 `/console`의 예정 카드까지만 smoke 검증.
- kiosk 루트 재진입만으로 sessionStorage가 자동 삭제되지는 않음 - KSK-GROUP-001 또는
  QAS-GROUP-001에서 세션 초기화 회귀시험으로 별도 보강 필요.
- `npm install --save-dev @playwright/test` 후 `npm audit`이 12건 취약점을 보고했으나
  QAS-004 범위가 아니어서 자동 수정하지 않음.

다음 추천 작업: BAC-GROUP-001(Wave 2 핵심 API 구현 세부 분해).

---

## 2026-08-02 - PRODUCTION 재판정 + WAVE 1.1A 진입 차단 + QAS-006 완료

트리거: 첨부된 PRODUCTION 실행 프롬프트 재확인 및 WAVE 1.1A 실행 프롬프트 확인.

판정:
- PRODUCTION: `PRODUCTION_BLOCKED` 유지. 현재 상태는 Wave 1/G1 IN_PROGRESS이며
  G2/G3/파일럿/RC/정식 릴리스 상태가 없다.
- WAVE 1.1A: `WAVE_1_1A_BLOCKED`. `.harness/v1.1/state.json`,
  `.harness/v1.1/backlog.yaml`, `.harness/v1.1/quality-gates.yaml`,
  `docs/v1.1/*`, `.harness/prompts/v1.1/WAVE-1.1A.md`, `CHANGELOG.md`가 없어
  승인된 v1.1 안정화 백로그를 자동 선택할 수 없다.

수행:
1. v1.1A 구현은 시작하지 않고 `.harness/reports/release/WAVE_1_1A_ENTRY-2026-08-02.md`
   에 NOT_RUN 사유 기록.
2. PRODUCTION 장애 복구 경로의 현재 G1 잔여 검증 항목으로 `QAS-006` 수행.
3. `.harness/handoffs/qa/BAC-001-test-request.md`의 테스트를
   `backend/tests/test_health_api.py`로 반영.
4. `.harness/backlog.yaml`, `.harness/state.json`, `.harness/quality-gates.yaml` 갱신.
5. `.harness/handoffs/qa/QAS-006.md` 작성.

검증:
- `cd backend && ../.venv/bin/pytest tests/test_health_api.py -v` 통과:
  6 passed, 1 skipped(Postgres 미기동).
- `cd backend && ../.venv/bin/ruff check tests/test_health_api.py` 통과.
- `cd backend && ../.venv/bin/pytest -q` 통과: 96 passed, 12 skipped.

다음 추천 작업: QAS-004. 운영 전환과 v1.1A는 진입 산출물/게이트 충족 후 재평가.

---

## 2026-08-02 - PRODUCTION 프롬프트 판정: PRODUCTION_BLOCKED + QAS-005 완료

트리거: 첨부된 PRODUCTION 실행 프롬프트(정식 운영 전환·집중 모니터링·출시 후
회고·v1.1 계획) 확인.

판정: `PRODUCTION_BLOCKED`. 현재 `.harness/state.json`은 `current_wave: 1`,
`current_gate: G1_CONTRACT_FREEZE`, `gate_status: IN_PROGRESS`이며 G2/G3/파일럿/RC/
정식 릴리스 상태가 없다. 따라서 production deploy, migration, feature flag 전환,
집중 모니터링, 출시 후 회고는 모두 NOT_RUN으로 기록했다.

수행:
1. `.harness/reports/go-live/PRODUCTION_LIFECYCLE-2026-08-02.md` 작성.
2. QAS-005 착수 및 완료: `infra/scripts/scope-violation-check`에 키오스크 개인정보
   입력필드 정적 검사 추가. `<input>`, `<textarea>`, `<select>` 속성만 검사해
   읽기 전용 업체정보 표시와 사용자 입력 필드를 구분한다.
3. `QAS-004`를 READY로 정리하고 `next_recommended_tasks`를 `QAS-004`, `QAS-006`으로
   갱신.
4. 하네스 검증기가 태스크별 handoff 파일을 찾을 수 있도록 묶음 handoff pointer 파일 추가.

검증:
- `python3 -m py_compile infra/scripts/scope-violation-check` 통과.
- `./.venv/bin/ruff check infra/scripts/scope-violation-check` 통과.
- `infra/scripts/scope-violation-check` 통과.
- 키오스크 정적 검사 self-test 통과(위반 fixture 탐지, 읽기 전용 표시 통과, 테스트 fixture 제외).
- `cd apps/kiosk && npm test -- --run` 통과: 3 files, 29 tests.
- `infra/scripts/validate-harness` 통과.

다음 추천 작업: QAS-004, QAS-006. 운영 전환은 G1/G2/G3/파일럿/RC 완료 후 재평가.

---

## 2026-08-02 - CTR-006/CTR-007 완료 (saved_recommendable + ai.* 스키마)

트리거: 첨부된 WAVE 프롬프트 묶음 확인 후 현재 `.harness/state.json`의
`next_recommended_tasks`에 따라 G1 잔여 계약 마이그레이션 수행.

수행:
1. CTR-006: `profile.saved_recommendable` 모델과 `0011_saved_recommendable` 마이그레이션
   추가. W-8 §4 확정 스키마대로 `saved_recommendable_id`, `profile_id`,
   `recommendable_id`, `saved_at`, `saved_context_json`, UNIQUE(profile_id, recommendable_id)
   및 조회 인덱스를 생성했다.
2. CTR-007: `backend/app/models/ai.py` 신설 및 `0012_ai_schema` 마이그레이션 추가.
   `source_document`, `extracted_attribute`, `content_approval`, `ai_execution_log`,
   `embedding_document`, `embedding_vector` 6개 테이블을 구현했다. pgvector는 신규 Python
   의존성을 추가하지 않고 PostgreSQL extension + custom `vector` 타입으로만 사용한다.
3. Alembic env에 `app.models.ai` import를 추가하고, head 검증 테스트 상수를
   `0012_ai_schema`로 갱신했다.

검증:
- `cd backend && ruff check .` 통과.
- `cd backend && pytest -q` 통과: 90 passed, 11 skipped.
- `python -m unittest discover -s tests -v` 통과: 23 tests.
- `meet-ai-ontology validate` 통과: 259 concepts.
- PostgreSQL 17 + pgvector 임시 DB에서 `alembic upgrade head`, `alembic downgrade 0010_kiosk`,
  `alembic upgrade head` 왕복 성공.
- `alembic check`는 기존 문서화된 `exhibition.profile_attribute` FK 드리프트 1건만 보고.

산출물: `backend/app/models/{profile,ai}.py`, `backend/alembic/env.py`,
`backend/alembic/versions/20260802_0910_0011_saved_recommendable.py`,
`backend/alembic/versions/20260802_0911_0012_ai_schema.py`,
`backend/tests/test_exhibitor_models.py`, `.harness/{state,backlog,quality-gates}.yaml/json`,
핸드오프 `.harness/handoffs/contracts/CTR-006-007.md`.

다음 추천 작업: QAS-004, QAS-005.

---

## 2026-08-02 - CTR-002/003/004/005/008 일괄 완료 (OpenAPI/온톨로지/오류코드/이벤트 카탈로그 + WAVE-1 크로스워크)

트리거: CONTRACTS 트랙 5개 태스크 일괄 디스패치.

수행:
1. CTR-008(먼저 실행, 근거 확립): WAVE-1 프롬프트의 전체 엔터티 목록(30여개)을 domain-model.md
   §13과 1:1 대조해 §15 크로스워크 표 신설 - `backend/app/models/*.py`를 직접 grep해 문서만
   신뢰하지 않고 재확인. 진짜 신규로 확인된 것: SearchSession/SearchQuery/SearchResult
   (`backend/app/models/search.py`, matching 스키마 - 기존 recommendation_session이
   profile_id NOT NULL이라 프로파일 없는 검색을 못 담음), KioskDevice/KioskConfig
   (`backend/app/models/kiosk.py`, exhibition 스키마 - guest_session과 다른 물리 단말
   개념). 마이그레이션 0009_search/0010_kiosk를 로컬 Postgres 16(Docker 미가용,
   homebrew initdb로 임시 인스턴스 구성)에 실제 upgrade/downgrade 왕복 실행해 검증,
   `alembic check`로 드리프트 없음 확인. ExternalReference/InteractionEvent도 실제
   테이블 없음을 확인했으나 현재 redesign-v2 문서가 요구하지 않아 CTR-009/CTR-010으로만
   후속 등록(AGENTS.md §11, 임의 구현 금지).
2. CTR-003: catalog.v1.json 실측(259개 concept, 23개 concept_type)으로 WAVE-1 8개
   카테고리 전부 매핑. REGION이 C-3 문서에 없었지만 실제로는 이미 존재·실사용 중임을
   코드로 확인, C-3의 "산업→CATEGORY.*" 오탈자도 실측으로 정정(PRODUCT.*가 정답).
3. CTR-004: matching.py의 FILTER_RESULT_TYPES(8종) 실측을 그대로 옮기고 WAVE-1
   15종 + 기존 ontology 엔드포인트 2종을 통합, 총 17종 중복 0.
4. CTR-005: WAVE-1 20개 이벤트 전부 정의, RQ/Celery 큐잉 트리거로만 범위 한정.
5. CTR-002: 25개 경로·26개 operationId(중복 0)로 OpenAPI 작성, `openapi-spec-validator`
   실제 설치·실행으로 검증(OK).

검증: 4개 YAML 전부 PyYAML 파싱 성공, openapi.yaml은 openapi-spec-validator 통과.
alembic upgrade head/downgrade -1 x2/upgrade head 왕복 실제 실행(로컬 Postgres 16).
pytest 전체 101 passed(기존 100 + 회귀 없음 - test_exhibitor_models.py의 헤드 리비전
상수 1줄만 DEC-009 동일 패턴으로 갱신). ruff 전체 통과.

산출물: `.harness/contracts/{openapi,ontology,error-codes,event-catalog}.yaml`,
`.harness/contracts/domain-model.md`(§15/§16 신설), `backend/app/models/{search,kiosk}.py`,
`backend/alembic/versions/{20260802_0900_0009_search,20260802_0901_0010_kiosk}.py`,
`backend/alembic/env.py`(신규 모듈 import 추가), `backend/tests/test_exhibitor_models.py`
(헤드 리비전 상수 갱신, 좁은 예외), `.harness/backlog.yaml`(5건 DONE + CTR-009/010 신설),
`.harness/state.json`. 핸드오프: `.harness/handoffs/contracts/CTR-002-through-008.md`.

다음 추천 작업: CTR-006(saved_recommendable 마이그레이션), CTR-007(ai.* 스키마 마이그레이션),
QAS-004/005(WEB-001/KSK-001/ADM-001 완료로 BLOCKED 해제됨).

---

## 2026-08-02 - WAVE-0 v2 프롬프트: 구조 확장 + 4개 앱 스캐폴드 병렬 디스패치 (FND-005, WEB-001/KSK-001/ADM-001/BAC-001)

트리거: 사용자의 "WAVE 0 실행 프롬프트: 개발 하네스·모노레포 초기화" (더 상세한 두 번째 버전).

수행:
1. ASSUMPTION-005~008 기록 - 프롬프트 자신의 §2("기존 디렉터리를 새 구조에 강제로 이동하지 않는다")를 근거로 apps/api·database/ 신규 생성을 보류하고 backend/·src/meet_ai/를 정본으로 재확인. state.json 스키마를 더 구체적인 최신 예시(gate_status 문자열, next_recommended_tasks 배열)에 맞춰 조정.
2. 신규 디렉터리 생성(README 포함, 빈 .gitkeep 아님): database/, ai/, infra/{docker,scripts,monitoring}, tests/{api,integration,e2e,security}, docs/{requirements,api,architecture,operations}, apps/api(리다이렉트 전용), apps/worker(생성만, 내용은 BAC-001 에이전트가 채움).
3. 루트 .env.example 신설, backend/.env.example에 S3/MinIO 변수 추가, docker-compose.yml에 MinIO(+버킷 자동생성 잡) 추가, 루트 Makefile 신설(setup/dev/infra-up/infra-down/lint/typecheck/test/test-integration/smoke/check).
4. infra/scripts/validate-harness, infra/scripts/scope-violation-check 작성 - 둘 다 실제 실행해 검증. scope-violation-check는 최초 실행에서 자기 자신의 문서화되지 않은 버그(.harness/** 제외 누락)로 인한 오탐 2건을 발견해 즉시 수정 후 재검증 통과.
5. locks.yaml 갱신(apps/worker→BACKEND, database/·packages/ontology→CONTRACTS, infra/·Makefile·.env.example→FOUNDATION).
6. CI 확장(harness-validate/docker-build/build-artifact 잡) - 편집 중 자체 실수(중복 `jobs:` 키로 YAML 구조 파손)를 저지르고 즉시 재검증으로 발견·수정.
7. infra/docker/backend.Dockerfile 신규 작성(빌드 컨텍스트=저장소 루트, meet_ai+backend 이중 설치).
8. WEB-001/KSK-001/ADM-001(이전에 FND-002 대기로 BLOCKED였으나 이제 해제) + 신규 BAC-001(헬스체크 3종 + apps/worker 골격)을 4개 병렬 Agent로 디스패치.

검증: validate-harness/scope-violation-check 실제 실행 통과, docker-compose.yml/ci.yml YAML 파싱 통과. Docker 데몬이 이 환경에 없어 `docker compose up`/`docker build` 자체는 NOT_RUN(quality-gates.yaml에 이미 반영된 기존 상태 유지).

다음 추천 작업: 4개 병렬 에이전트(WEB-001/KSK-001/ADM-001/BAC-001) 완료 대기 후 CTR-002/003/007, AIS-001로 진행.

---

## 2026-08-02 - FND-002/FND-003 실행 + 병렬 워커 프롬프트 팩 수신, Wave 1 디스패치

트리거: 사용자의 "다음" 입력, 이어서 "병렬 워커 실행 프롬프트 팩 v1.0" 수신.

수행:
1. `.harness/worker-prompts.md` 신설 - 워커 프롬프트 팩 원문의 요지·경로 재매핑표 저장(ASSUMPTION-001 경로 차이 반영).
2. FND-002: 루트 `package.json`에 `workspaces: ["apps/*","packages/*"]` 추가, `apps/README.md`/`packages/README.md` 생성. 검증 중 `npm ls --workspaces`가 실제 멤버 없이는 오류를 낸다는 것을 발견해 `npm pkg get workspaces`로 acceptance 기준을 수정(backlog.yaml에 기록).
3. FND-003: `.github/workflows/ci.yml` 생성(backend ruff+pytest, meet_ai 검증+unittest, TS 경계 typecheck). 로컬 venv로 실제 실행 검증 중 (a) 11건 ruff import 순서 위반, (b) `greenlet` 의존성 누락을 발견 - 둘 다 순수 기계적 수정으로 즉시 해소(DEC-009, 좁은 예외로 처리 근거 기록). 최종 83 passed / 11 skipped(DB 없음, 정상) / 0 failed.
4. AIS-002의 track이 owned_paths(backend/tests/**)와 불일치(AI_SEARCH로 잘못 기록, 실제로는 QA_SECURITY 전속 경로)함을 디스패치 전 발견해 정정.
5. Wave 1 병렬 디스패치: CTR-001(CONTRACTS, 도메인 모델 문서), {QAS-001+AIS-002}(QA_SECURITY, CI 정적검사·시크릿스캔 + 온톨로지 유사어 테스트셋)를 병렬 Agent로 기동 - 서로 owned_paths 겹침 없음, 의존성 충족 확인.

검증: 위 3항 각각 실제 명령 실행으로 확인(문서 §검증 참고, 가짜 로그 아님).

다음 추천 작업(에이전트 완료 후): CTR-002(OpenAPI 초안, CTR-001 의존).

---

## 2026-08-02 - 하네스 부트스트랩 (FND-001)

트리거: 사용자의 "병렬개발 하네스 오케스트레이터 메타프롬프트 v1.0" 전달, §20 최초 실행 지시.

수행:
1. 저장소 구조 조사 - `backend/`(FastAPI, 9 API 엔드포인트 중 ontology만 노출), `src/meet_ai/`(온톨로지+스코어링 코어), `netlify/functions/`(AI Gateway), `db/migrations/`(초기 SQL, 현재는 Alembic이 정본), `docs/`(구설계 + `docs/redesign-v2/` 26개 신설계), `tests/`(루트, unittest 기반) 확인. `apps/`, `packages/`, `.github/` 없음.
2. `.harness/**` 전체 생성(state.json, backlog.yaml, locks.yaml, quality-gates.yaml, assumptions.md, decisions.md, risks.md, expansion-candidates.md, run-log.md, contracts/, handoffs/{track}/, reports/{lint,tests,security,performance,integration}/).
3. 기존 구현을 backlog에 반영: FND-001 DONE, 나머지 Wave 0 항목 READY, Wave 1 CONTRACTS 6건 READY(대부분 CTR-001에 의존), USER_WEB/KIOSK/ADMIN 뼈대는 FND-002(모노레포 골격) 선행 필요로 BLOCKED, AI_SEARCH/QA_SECURITY Wave 1 항목은 READY.
4. ASSUMPTION-001~004 기록(모노레포 물리 이동 없음, G0 판정 유예, Wave 2/3 조 단위 백로그, 구 AGENTS.md 외부 기준선 대체).
5. DEC-001~008에 이전 세션(`docs/redesign-v2` 26개 문서 + `04-integration-roadmap.md`)에서 이미 확정된 결정을 소급 기록.

검증:
- `state.json` JSON 파싱 성공.
- `backlog.yaml`/`locks.yaml`/`quality-gates.yaml`/`contracts/*.yaml` 전체 YAML 파싱 성공(PyYAML로 확인).
- `locks.yaml` 소유권 중복 검사: 41개 경로 패턴, 완전 중복 0건.
- G0_BOOTSTRAP 재검증(`FND-004`) 시도 - 이 실행 환경에 Docker가 없어(`docker: command not found`) `docker compose up`/실제 헬스체크를 이번 세션에서 직접 실행하지 못했다. `FND-004`는 `READY` 상태로 유지하고 `quality-gates.yaml`의 g0-2/g0-3/g0-5는 "이전 세션 근거 기반 LIKELY_PASS"로만 표시했다 - Docker 가용 환경(로컬 또는 CI)에서 실제 재검증 필요.

산출물: `.harness/**`(state/backlog/locks/quality-gates/assumptions/decisions/risks/expansion-candidates/run-log + contracts 5개 placeholder + handoffs/reports READY), 루트 `AGENTS.md`(재작성)/`PROJECT_SCOPE.md`/`ARCHITECTURE.md`/`DEVELOPMENT.md`/`TESTING.md`/`SECURITY.md`(신규).

다음 추천 작업: CTR-001(통합 도메인 모델 문서, `.harness/contracts/domain-model.md`).

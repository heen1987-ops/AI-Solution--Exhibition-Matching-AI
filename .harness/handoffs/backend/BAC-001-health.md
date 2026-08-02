# BAC-001 (Part A) - Health Check API + /api/v1/system/info

## 완료 내용

`backend/app/main.py`, `backend/app/api/**`에 세 엔드포인트를 구현했다.

- `GET /health/live` - 의존성 체크 없음, 항상 즉시 `{"status": "alive"}`(200).
- `GET /health/ready` - PostgreSQL(기존 `app.db.session.get_engine()` 재사용, `SELECT 1`)과
  Redis(`redis.asyncio.Redis.from_url(settings.REDIS_URL)`, `PING`)를 실제로 확인한다.
  S3(MinIO)는 boto3 등 새 SDK 없이 표준 `socket` 모듈로 host:port TCP 연결만 확인한다(버킷
  권한까지는 확인하지 않음 - 헬스체크 목적상 "도달 가능한가"면 충분하다고 판단).
  응답 스키마:
  ```json
  {"status": "ready"|"degraded"|"not_ready", "checks": {"postgres": "ok"|"error", "redis": "ok"|"error", "s3": "ok"|"error"|"warning"}}
  ```
  분기 로직:
  - Postgres 또는 Redis가 `error`면 무조건 `status="not_ready"`(HTTP 503).
  - S3가 죽어 있을 때: `READY_CHECK_FAILS_ON_S3_DOWN=false`(기본값)면 `checks.s3="warning"`만
    남기고 `status="degraded"`(HTTP 200 유지) - `true`면 `checks.s3="error"`이자
    `status="not_ready"`(HTTP 503)로 번진다.
  - 전부 정상이면 `status="ready"`(HTTP 200).
- `GET /api/v1/system/info` - 정확히
  `{"service": "backju-ai-matching-api", "version": "0.1.0", "environment": "<settings.ENV>", "contract_version": "draft"}`
  만 반환한다(개인정보 없음).

`backend/app/core/config.py`(BACKEND 트랙 소유 - `.harness/locks.yaml` 확인)에
`S3_ENDPOINT`/`S3_BUCKET`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`/`READY_CHECK_FAILS_ON_S3_DOWN`
필드를 추가했다 - `backend/.env.example`에는 이미 있었지만 `Settings` 클래스에는 아직
반영되지 않았었다.

**기존 `/healthz`는 그대로 유지했다** - 삭제 전 확인해보니 `README.md`,
`DEVELOPMENT.md`, `backend/README.md`, `.harness/quality-gates.yaml`(g0-5 기준)이 전부
`/healthz`를 참조하고 있어 제거하면 그 문서/게이트 근거가 깨진다. 새 모니터링·통합은
`/health/live`, `/health/ready`를 쓰고 `/healthz`는 레거시로 문서화(`main.py` docstring)만
해뒀다.

## 변경 파일

- `backend/app/main.py` (수정 - `/healthz` 유지 + `/health/*` 라우터 마운트)
- `backend/app/api/v1/api.py` (수정 - `system` 라우터 등록)
- `backend/app/core/config.py` (수정 - S3/READY_CHECK_FAILS_ON_S3_DOWN 설정 추가)
- `backend/app/api/health.py` (신규 - `/health/live`, `/health/ready`)
- `backend/app/api/v1/endpoints/system.py` (신규 - `/api/v1/system/info`)

## 공개 인터페이스

위 4개 엔드포인트가 신규(`/healthz`는 기존 유지, 변경 없음). `openapi.yaml` 등 공유 계약
파일은 건드리지 않았다(G1_CONTRACT_FREEZE 이후 CONTRACTS 트랙 전속 - `AGENTS.md` §7).
CONTRACTS 트랙이 계약을 확정할 때 이 4개 엔드포인트를 반영해줘야 한다(NEXT DEPENDENCY 참고).

## DB 변경

없음. `/health/ready`가 기존 `get_engine()`으로 연결 시도만 할 뿐 스키마를 건드리지 않는다.

## 테스트

**중요(트랙 경계 문제 - AIS-002와 동일 선례)**: `.harness/locks.yaml`상 `backend/tests/**`는
QA_SECURITY 전속 경로다(BAC-001 dispatch 프롬프트의 "owned_paths"에는 이 사실이 반영돼
있지 않았다 - `.harness/worker-prompts.md` 경로 재매핑표와 `locks.yaml`을 대조해 뒤늦게
발견). 그래서 테스트 파일을 `backend/tests/`에 직접 커밋하지 않았다. 대신:

1. 실제 테스트 코드를 작성해 **scratch 환경(`/private/tmp/.../scratchpad/test_health_api.py`)에서
   backend venv로 직접 실행해 통과를 확인**했다(아래 실제 결과).
2. QA_SECURITY에게 이 파일을 `backend/tests/test_health_api.py`로 반영해달라는 요청을
   `.harness/handoffs/qa/BAC-001-test-request.md`에 남겼다(테스트 전문 포함).

실행 결과(Python 3.12 venv, `backend/pyproject.toml[dev]` 설치 후,
`PYTHONPATH=backend pytest <scratch>/test_health_api.py -v`):

```
test_health_live_always_succeeds_without_dependencies PASSED
test_health_ready_returns_error_shape_when_redis_down PASSED
test_health_ready_s3_down_is_warning_by_default PASSED
test_health_ready_s3_down_fails_when_flag_enabled PASSED
test_health_ready_postgres_ok_when_reachable SKIPPED (이 환경에 실제 Postgres 없음 - 기존 conftest.py 관례와 동일하게 자동 skip)
test_system_info_matches_exact_contract_schema PASSED
test_healthz_legacy_endpoint_still_works PASSED

6 passed, 1 skipped
```

**테스트 작성 중 실제 버그를 하나 발견해 고쳤다**: 처음 작성한 테스트는
`monkeypatch.setenv(...)` 이후 `get_settings()`의 `lru_cache`를 다시 비우지 않아, 환경변수를
바꿔도 이전에 캐시된 `Settings` 객체가 계속 쓰이는 문제가 있었다(캐시를 비우는 시점이
`setenv` "이전"이면 그 다음 `get_settings()` 호출이 setenv 이전 상태를 다시 캐싱해버림).
`READY_CHECK_FAILS_ON_S3_DOWN=true` 테스트가 처음엔 `checks.s3="warning"`을 반환해
실패했는데(기대는 `"error"`), 원인이 앱 코드가 아니라 테스트의 캐시 비우기 타이밍
버그였음을 확인하고 각 테스트에서 `monkeypatch.setenv(...)` **직후**
`get_settings.cache_clear()`를 호출하도록 고쳤다 - 앱 코드(`health.py`)는 처음부터 정상
동작이었다.

또한 전체 backend 스위트 회귀 확인: `cd backend && pytest -q` → **90 passed, 11 skipped**
(작업 전 베이스라인과 동일 - 신규 코드가 기존 테스트를 깨지 않음). `ruff check
app/api/health.py app/api/v1/endpoints/system.py app/api/v1/api.py app/main.py
app/core/config.py` → All checks passed.

## 알려진 제한

- S3(MinIO) 체크는 TCP 연결 가능 여부만 확인한다(실제 버킷 read/write 권한 검증 없음) -
  boto3/minio SDK를 새 의존성으로 추가하지 않기 위한 의도적 트레이드오프. 버킷 접근
  권한까지 검증이 필요해지면 별도 태스크로 SDK 추가를 검토해야 한다(현재는
  `EXPANSION` 후보로 보지 않음 - health check 범위 내 정상적 구현 선택으로 판단).
- `.harness/contracts/error-codes.yaml`이 아직 DRAFT(CTR-004 대기)라 `/health/ready`
  실패 응답에 공통 오류코드를 매핑하지 않았다 - 지금은 `status`/`checks` 필드만으로
  구조화했다. CTR-004 완료 후 필요하면 오류코드 필드를 추가하는 후속 변경이 필요할 수
  있다(하위 호환 추가이므로 Breaking Change 아님, 다만 계약 확정 후이므로 CONTRACTS
  트랙의 Change Request 절차를 거쳐야 한다).
- `backend/tests/test_health_api.py`가 아직 저장소에 커밋되지 않았다(위 테스트 섹션 참고)
  - QA_SECURITY가 반영하기 전까지는 CI의 `pytest` 실행 대상에 이 테스트가 포함되지
    않는다는 뜻이다.

## 다른 트랙이 해야 할 일

- **QA_SECURITY**: `.harness/handoffs/qa/BAC-001-test-request.md`의 테스트 전문을
  `backend/tests/test_health_api.py`로 반영(그대로 복사해도 통과 확인됨 - 위 실행 결과 참고).
- **CONTRACTS**: `openapi.yaml` 등 계약 문서에 `/health/live`, `/health/ready`,
  `/api/v1/system/info` 3개 엔드포인트를 반영. 특히 `/health/ready`의 `status`/`checks`
  응답 스키마를 계약에 고정해달라 - 지금은 이 파일이 사실상의 유일한 스키마 정의다.
- **FOUNDATION/QA_SECURITY**: `.harness/quality-gates.yaml`의 `g0-5`("Health Check 성공")
  항목이 아직 `/healthz` 기준으로 적혀 있다 - `/health/live`, `/health/ready` 추가를
  반영해 갱신을 검토해달라(단, `.harness/**`는 FOUNDATION 소유라 BACKEND가 직접 고치지
  않았다).

## 되돌리는 방법

이번 변경은 5개 파일(수정 3 + 신규 2)로 국한된다:
```
git checkout -- backend/app/main.py backend/app/api/v1/api.py backend/app/core/config.py
rm backend/app/api/health.py backend/app/api/v1/endpoints/system.py
```
`/healthz`는 건드리지 않았으므로 되돌려도 기존 기능에 부수효과가 없다.

## 다음 권장 작업

- QA_SECURITY가 `backend/tests/test_health_api.py` 반영(위 참고).
- CONTRACTS가 `/health/*`, `/api/v1/system/info`를 openapi 계약에 반영.
- 실제 Postgres/Redis/MinIO가 있는 CI 환경에서 `/health/ready`가 `status="ready"`를
  반환하는지 통합 확인(현재는 로컬 sandbox에 Postgres/MinIO가 없어 `not_ready`/`degraded`
  경로만 검증됨 - Redis는 `docker-compose.yml`의 서비스가 뜬 CI에서 재검증 권장).

# BAC-001 (Part B) - apps/worker 골격

## 완료 내용

`apps/worker/`(BACKEND 트랙 소유, 이전에는 완전히 비어 있던 신규 디렉터리)에 최소
백그라운드 잡 워커 골격을 만들었다.

**아키텍처 결정: RQ(Redis Queue) 선택, Celery 아님.**
이유:
- Celery는 브로커(보통 RabbitMQ/Redis)와 별도의 result backend 설정이 필요하고,
  워커 실행 모델(prefork/eventlet/gevent)도 별도로 결정해야 한다. RQ는 Redis 하나로
  큐+결과 저장을 겸하고, `Worker`/`SimpleWorker` 하나로 최소 골격이 끝난다 -
  "이 웨이브는 스캐폴딩만"이라는 BAC-001 범위에 더 맞는다.
- `backend/pyproject.toml`이 이미 `redis>=5.0.0`을 쓰고 있어 워커도 같은 Redis
  인스턴스·라이브러리 계열을 그대로 재사용할 수 있다(추가 인프라 없음,
  `docker-compose.yml`의 기존 Redis 서비스로 충분).
- `AGENTS.md` §3("비동기: RQ 또는 Celery 중 하나(Kafka 금지)")이 이미 RQ를 허용된
  선택지로 명시하고 있어 ADR 없이 바로 채택 가능.

구성:
- `apps/worker/pyproject.toml` - 독립 패키지(`backju-worker`). `redis>=5.0.0`,
  `rq>=1.16.0` 의존. `backend/pyproject.toml`을 재사용하지 않고 별도로 둔 이유: 워커는
  FastAPI/SQLAlchemy 등 백엔드 전용 의존성이 전혀 필요 없어 배포 이미지를 가볍게
  분리할 수 있게 하기 위함(이후 Docker화 시 `apps/worker/Dockerfile`이 이 pyproject만
  설치하면 됨).
- `apps/worker/worker/config.py` - `REDIS_URL`(기본 `redis://localhost:6379/0`,
  `backend/.env.example`과 동일 관례), `WORKER_QUEUE_NAME`(기본 `backju-worker`) 환경변수.
- `apps/worker/worker/queue.py` - `get_redis_connection()`/`get_queue()` 헬퍼. 의도적으로
  전역 캐시하지 않는다(이유는 코드 docstring 참고 - health API 쪽 lru_cache 버그를 겪고
  나서 같은 함정을 피하려고 내린 선택).
- `apps/worker/worker/tasks.py` - 샘플 작업 2개:
  - `heartbeat_task()` - 항상 `"ok"`를 반환하는 성공 샘플.
  - `always_fails_task(payload=None)` - 재시도 테스트 전용, 항상 `IntentionalFailure`를
    던진다. payload의 **키 이름만** 로그하고 값은 절대 로그하지 않는다(민감정보 규칙).
- `apps/worker/worker/retry_policy.py` - RQ 내장 `Retry` 객체를 그대로 쓰는 기본 정책:
  최대 3회 재시도, backoff 1s/5s/10s(`Retry(max=3, interval=[1, 5, 10])`). 커스텀
  재시도 시스템을 직접 만들지 않았다(BAC-001 지시사항 그대로 따름).
- `apps/worker/worker/logging_utils.py` - `print()` 없이 표준 `logging` + 커스텀
  `JsonFormatter`로 구조화(JSON) 로그 한 줄씩 출력. 새 로깅 라이브러리(structlog 등)
  의존성을 추가하지 않았다 - 이 정도 요구사항엔 표준 라이브러리로 충분하다고 판단.
- `apps/worker/worker/run_worker.py` - 실제 워커 프로세스 진입점
  (`python -m worker.run_worker`). Redis 접속 URL을 로그에 남길 때 `user:password@`
  구간을 마스킹한다(민감정보 미노출 규칙을 connection string에도 적용).
- `apps/worker/worker/smoke.py` - 로컬 스모크 스크립트(`python -m worker.smoke`):
  `heartbeat_task`를 enqueue하고 `SimpleWorker(...).work(burst=True)`로 즉시 실행해
  결과를 출력한다.
- `apps/worker/tests/test_worker.py` - 아래 "테스트" 참고.

## 변경 파일

전부 신규(이전에 `apps/worker/`는 빈 디렉터리였다):
- `apps/worker/pyproject.toml`
- `apps/worker/worker/__init__.py`
- `apps/worker/worker/config.py`
- `apps/worker/worker/queue.py`
- `apps/worker/worker/tasks.py`
- `apps/worker/worker/retry_policy.py`
- `apps/worker/worker/logging_utils.py`
- `apps/worker/worker/run_worker.py`
- `apps/worker/worker/smoke.py`
- `apps/worker/tests/__init__.py`
- `apps/worker/tests/test_worker.py`

## 공개 인터페이스

새 프로세스 진입점 2개(`python -m worker.run_worker`, `python -m worker.smoke`) - REST
API 계약과는 무관하다(내부 인프라). 다른 트랙이 실제 도메인 작업(예: 업체자료 AI
구조화 잡)을 큐에 태우려면 `worker/tasks.py` 옆에 새 태스크 함수를 추가하고
`get_queue().enqueue(그_함수, retry=default_retry())` 패턴을 따르면 된다.

## DB 변경

없음.

## 테스트

**이 디렉터리는 전부 BACKEND 소유(`apps/worker/**`)라 테스트를 직접 커밋했다** - Part A와
달리 트랙 경계 문제가 없다.

실제 Redis가 필요한 통합 테스트 2건은 Redis 연결 불가 시 자동 skip되도록
`backend/tests/conftest.py`와 같은 관례(`pytest.mark.skipif` + 연결 프로브)를 적용했다.
로컬에 Redis가 전혀 없어서(이 sandbox 환경 기본 상태) `brew install redis`로 설치 후
`redis-server --port 16379 --daemonize yes`로 임시 인스턴스를 띄워 실제로 검증했다.

실행 결과(`WORKER_TEST_REDIS_URL=redis://localhost:16379/0 pytest -v`, Python 3.12,
`apps/worker/pyproject.toml[dev]` 설치):

```
test_default_retry_policy_is_bounded PASSED
test_always_fails_task_raises_intentional_failure PASSED
test_task_failure_never_logs_sensitive_payload_values PASSED
test_heartbeat_task_runs_successfully PASSED
test_failing_task_retries_a_bounded_number_of_times PASSED

5 passed
```

Redis 없이(`WORKER_TEST_REDIS_URL=redis://127.0.0.1:1/0`, 즉 아무도 안 듣는 포트) 재실행:

```
test_default_retry_policy_is_bounded PASSED
test_always_fails_task_raises_intentional_failure PASSED
test_task_failure_never_logs_sensitive_payload_values PASSED
test_heartbeat_task_runs_successfully SKIPPED
test_failing_task_retries_a_bounded_number_of_times SKIPPED

3 passed, 2 skipped
```

각 테스트가 검증하는 것:
- `test_default_retry_policy_is_bounded` - 재시도 정책이 **유한**(`max=3`)함을 설정값
  수준에서 고정(무한 재시도 방지의 근거).
- `test_always_fails_task_raises_intentional_failure` - 샘플 실패 태스크가 실제로
  예외를 던지는지(큐 밖에서 직접 호출).
- `test_task_failure_never_logs_sensitive_payload_values` - `payload`에 심어둔 가짜
  시크릿 문자열(`sk-test-EXTREMELY-SENSITIVE-...`)이 `JsonFormatter`로 직렬화한 로그
  라인 어디에도 등장하지 않고, 키 이름(`api_key`, `payload_keys`)만 남는지 확인.
- `test_heartbeat_task_runs_successfully` - 실제 Redis에 enqueue하고
  `SimpleWorker(burst=True)`로 실행해 `status="finished"`, `return_value()=="ok"` 확인
  (스모크 스크립트와 동일 경로를 pytest로 재현).
- `test_failing_task_retries_a_bounded_number_of_times` - `Retry(max=2, interval=0)`로
  enqueue한 항상-실패 태스크가 Redis 카운터 기준 **정확히 3번**(최초 1 + 재시도
  2)만 실행되고 `status="failed"`로 끝나는지 확인 - "무한 재시도가 아니다"를 실제
  큐 실행으로 증명한다. (참고: 프로덕션 기본 정책의 backoff `[1, 5, 10]`초까지 그대로
  기다리면 테스트가 느려지므로, 이 테스트만 `interval=0`으로 속도를 냈다 - backoff
  간격 자체는 `test_default_retry_policy_is_bounded`가 별도로 검증한다.)

`ruff check .`(apps/worker 안에서) → All checks passed.

`python -m worker.smoke`(REDIS_URL=redis://localhost:16379/0) 실제 실행 로그로
enqueue -> worker 실행 -> 결과(`status=JobStatus.FINISHED result='ok'`)까지 end-to-end
확인.

## 알려진 제한

- 실제 AI 문서처리·임베딩 생성 태스크는 구현하지 않았다(PROJECT_SCOPE.md 제외범위,
  BAC-001 acceptance에 명시) - `heartbeat_task`/`always_fails_task`는 순수 스캐폴딩
  샘플이다.
- Docker화(전용 Dockerfile, docker-compose 서비스 등록)는 이번 태스크 범위 밖이다 -
  `docker-compose.yml`은 FOUNDATION 소유라 직접 추가하지 않았다. 필요하면
  FOUNDATION에 handoff 필요(아래 참고).
- `run_worker.py`는 로컬 실행 진입점일 뿐 systemd/supervisor 등 프로세스 매니저 설정은
  포함하지 않는다 - 배포 방식은 다음 웨이브에서 결정.
- 재시도 백오프 간격(`[1, 5, 10]`초)은 임의로 정한 값이다 - 실제 운영 SLA가 정해지면
  조정이 필요할 수 있다.

## 다른 트랙이 해야 할 일

- **FOUNDATION**: `docker-compose.yml`에 `apps/worker` 서비스를 추가할지 결정(현재는
  백엔드와 같은 Redis를 로컬 프로세스로 붙여 쓰는 것을 전제로 함). 필요하면
  `.harness/handoffs/foundation/`에 별도 요청.
- **AI_SEARCH / CONTRACTS**: 실제 도메인 잡(업체자료 AI 구조화, 임베딩 생성 등)을
  구현할 때 `apps/worker/worker/tasks.py` 옆에 새 태스크 모듈을 추가하고
  `worker/retry_policy.py::default_retry()`를 재사용하기를 권장(새 재시도 시스템을
  다시 만들지 말 것).

## 되돌리는 방법

`apps/worker/`가 이번 태스크 전에 완전히 빈 디렉터리였으므로:
```
rm -rf apps/worker/worker apps/worker/tests apps/worker/pyproject.toml
```
`apps/worker/`가 다시 빈 디렉터리로 돌아간다(다른 파일에 대한 부수효과 없음).

## 다음 권장 작업

- FOUNDATION이 `docker-compose.yml`에 워커 서비스를 등록할지 결정.
- Wave 2에서 AI_SEARCH/CONTRACTS가 실제 도메인 태스크(업체자료 처리 등)를
  `apps/worker/worker/tasks.py` 패턴을 따라 추가.
- CI(`FND-003`)가 `apps/worker`의 `pytest`/`ruff`도 백엔드와 함께 실행하도록
  파이프라인에 반영할지 검토(현재 CI 설정은 FOUNDATION 소유라 직접 건드리지 않음).

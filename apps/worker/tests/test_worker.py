"""apps/worker (BAC-001) 유닛·통합 테스트.

Redis에 연결할 수 없으면(이 저장소 기본 상태) 큐가 필요한 테스트만 자동으로 건너뛴다 -
`backend/tests/conftest.py`가 Postgres에 대해 쓰는 것과 같은 관례다. Redis가 필요 없는
순수 유닛 테스트(재시도 정책 설정값 검증, 태스크가 예외를 던지는지, 로그에 민감정보가
남지 않는지)는 항상 실행된다.

WORKER_TEST_REDIS_URL(또는 REDIS_URL) 환경변수로 테스트용 Redis를 가리킬 수 있다.
"""

from __future__ import annotations

import logging
import os

import pytest
from redis import Redis
from redis.exceptions import RedisError
from rq import Retry, SimpleWorker

from worker.logging_utils import JsonFormatter
from worker.queue import get_queue, get_redis_connection
from worker.retry_policy import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_INTERVALS_SECONDS,
    default_retry,
)
from worker.tasks import IntentionalFailure, always_fails_task, heartbeat_task

_TEST_REDIS_URL = os.environ.get(
    "WORKER_TEST_REDIS_URL", os.environ.get("REDIS_URL", "redis://localhost:6379/0")
)
_ATTEMPT_COUNTER_KEY = "backju-worker-test:retry-attempt-counter"


def _redis_reachable(url: str) -> bool:
    client = Redis.from_url(url, socket_connect_timeout=1)
    try:
        return bool(client.ping())
    except RedisError:
        return False
    finally:
        client.close()


requires_redis = pytest.mark.skipif(
    not _redis_reachable(_TEST_REDIS_URL),
    reason=(
        f"Redis({_TEST_REDIS_URL})에 연결할 수 없어 큐 통합 테스트를 건너뜁니다. "
        "로컬에서 `docker compose up -d` 또는 redis-server를 띄우고 필요하면 "
        "WORKER_TEST_REDIS_URL을 지정하세요."
    ),
)


def _counting_always_fails() -> None:
    """`test_failing_task_retries_a_bounded_number_of_times` 전용 헬퍼.

    RQ가 job 함수를 모듈 경로 문자열로 저장·재조회하므로 최상위(module-level) 함수여야
    한다(테스트 함수 안의 클로저는 쓸 수 없다). 실행될 때마다 Redis 카운터를 하나
    증가시키고 항상 실패한다 - "무한 재시도가 아니라 정확히 max+1번만 실행되고
    멈춘다"를 검증하기 위한 시도 횟수 계측용이다.
    """

    connection = get_redis_connection(_TEST_REDIS_URL)
    connection.incr(_ATTEMPT_COUNTER_KEY)
    raise IntentionalFailure("retry-bound 테스트를 위한 계측용 항상-실패")


@pytest.fixture()
def redis_connection() -> Redis:
    return get_redis_connection(_TEST_REDIS_URL)


@pytest.fixture()
def queue(redis_connection: Redis):
    q = get_queue(name="test-backju-worker", connection=redis_connection)
    q.empty()
    redis_connection.delete(_ATTEMPT_COUNTER_KEY)
    yield q
    q.empty()
    redis_connection.delete(_ATTEMPT_COUNTER_KEY)


# --- Redis 없이도 항상 도는 순수 유닛 테스트 ---------------------------------


def test_default_retry_policy_is_bounded() -> None:
    """기본 재시도 정책이 유한(3회)하고 backoff가 점점 벌어지는지 확인한다.

    RQ 내장 Retry 객체를 그대로 쓰므로(커스텀 재시도 시스템 없음) 여기서는 "설정값"만
    검증한다 - `max`가 유한한 정수라는 사실 자체가 "무한 재시도가 아님"의 근거다.
    """

    retry = default_retry()

    assert retry.max == DEFAULT_MAX_RETRIES == 3
    assert retry.intervals == DEFAULT_RETRY_INTERVALS_SECONDS
    assert all(isinstance(n, int) and n >= 0 for n in retry.intervals)


def test_always_fails_task_raises_intentional_failure() -> None:
    with pytest.raises(IntentionalFailure):
        always_fails_task({"note": "no secrets here"})


def test_task_failure_never_logs_sensitive_payload_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """payload에 심어둔 가짜 시크릿 문자열이 로그 라인 어디에도 등장하지 않아야 한다."""

    fake_secret = "sk-test-EXTREMELY-SENSITIVE-1234567890"

    with (
        caplog.at_level(logging.WARNING, logger="worker.tasks"),
        pytest.raises(IntentionalFailure),
    ):
        always_fails_task({"api_key": fake_secret, "note": "ok"})

    formatter = JsonFormatter()
    serialized_lines = [formatter.format(record) for record in caplog.records]
    serialized = "\n".join(serialized_lines)
    raw_messages = "\n".join(record.getMessage() for record in caplog.records)

    assert fake_secret not in serialized
    assert fake_secret not in raw_messages
    assert "api_key" in serialized  # 키 이름은 로그에 남되
    assert "payload_keys" in serialized  # 값은 절대 남지 않는다(위 assert로 확인)


# --- 실제 Redis가 필요한 통합 테스트 -----------------------------------------


@requires_redis
def test_heartbeat_task_runs_successfully(queue) -> None:
    job = queue.enqueue(heartbeat_task)

    worker = SimpleWorker([queue], connection=queue.connection)
    worker.work(burst=True)

    job.refresh()
    assert job.get_status() == "finished"
    assert job.return_value() == "ok"


@requires_redis
def test_failing_task_retries_a_bounded_number_of_times(queue) -> None:
    """항상 실패하는 태스크가 무한 재시도가 아니라 max+1번(최초 시도 + 재시도)만
    실행되고 최종적으로 failed 상태로 끝나는지 확인한다.

    실제 운영 backoff(1s/5s/10s)까지 기다리면 테스트가 느려지므로 여기서는
    interval=0인 Retry로 "유한 횟수로 끝난다"는 성질만 빠르게 검증한다 - backoff
    간격 자체의 설정값은 `test_default_retry_policy_is_bounded`가 검증한다.
    """

    max_retries = 2
    job = queue.enqueue(
        _counting_always_fails,
        job_id="retry-bounded-test-job",
        retry=Retry(max=max_retries, interval=0),
    )

    worker = SimpleWorker([queue], connection=queue.connection)
    # burst 모드는 큐가 완전히 빌 때까지(재시도로 재적재된 job 포함) job을 계속
    # 처리한다. max_jobs 상한을 넉넉히 줘서 "무한 재시도였다면 훨씬 더 많이 돌았을
    # 것"과 구분되게 한다.
    worker.work(burst=True, max_jobs=max_retries + 10)

    job.refresh()
    assert job.get_status() == "failed"

    attempts = int(queue.connection.get(_ATTEMPT_COUNTER_KEY) or 0)
    # 최초 시도 1회 + 재시도 max_retries회 = 정확히 max_retries + 1번.
    assert attempts == max_retries + 1

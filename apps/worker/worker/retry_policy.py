"""기본 실패·재시도 정책.

RQ 내장 `Retry` 메커니즘을 그대로 쓴다 - 커스텀 재시도 시스템을 직접 만들지 않는다
(BAC-001 지시사항). 기본값: 최대 3회 재시도, 재시도 사이 backoff는 1초/5초/10초로
점점 벌어진다. 무한 재시도가 아님을 `tests/test_worker.py::test_failing_task_retries_a_bounded_number_of_times`가
검증한다.
"""

from __future__ import annotations

from rq import Retry

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_INTERVALS_SECONDS = [1, 5, 10]


def default_retry() -> Retry:
    return Retry(max=DEFAULT_MAX_RETRIES, interval=DEFAULT_RETRY_INTERVALS_SECONDS)

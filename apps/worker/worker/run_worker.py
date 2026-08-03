"""RQ 워커 프로세스 진입점.

사용법:
    cd apps/worker && python -m worker.run_worker

REDIS_URL(기본 redis://localhost:6379/0)이 가리키는 Redis에 연결해 `backju-worker`
큐를 계속 폴링하며 job을 처리한다. Ctrl+C로 정지한다.
"""

from __future__ import annotations

from rq import Worker

from worker.config import get_queue_name, get_redis_url
from worker.logging_utils import get_logger
from worker.queue import get_queue, get_redis_connection

logger = get_logger(__name__)


def main() -> None:
    connection = get_redis_connection()
    queue = get_queue(connection=connection)
    logger.info(
        "worker.start",
        extra={
            "event": "worker_start",
            "queue": get_queue_name(),
            "redis_url": _redact_redis_url(get_redis_url()),
        },
    )
    worker = Worker([queue], connection=connection)
    worker.work()


def _redact_redis_url(url: str) -> str:
    """로그에 Redis 접속 URL의 비밀번호가 그대로 남지 않게 한다.

    `redis://:password@host:port/db` 형식에서 `user:password@` 구간을 통째로
    마스킹한다 - 민감정보를 로그에 남기지 않는다는 규칙(BAC-001 acceptance)을
    connection URL에도 적용한다.
    """

    if "@" not in url:
        return url
    scheme_and_creds, _, rest = url.partition("@")
    scheme = scheme_and_creds.split("://", 1)[0]
    return f"{scheme}://***@{rest}"


if __name__ == "__main__":
    main()

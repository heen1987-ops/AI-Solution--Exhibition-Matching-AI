"""로컬 스모크 테스트 스크립트.

큐에 heartbeat 샘플 작업을 넣고(enqueue) burst 모드 `SimpleWorker`로 즉시 실행한 뒤
결과를 출력한다 - 별도 워커 프로세스를 띄우지 않고 "큐 연결 + enqueue + 실행"이 실제로
동작하는지 한 번에 확인하는 용도다.

사용법:
    docker compose up -d   # 또는 로컬 redis-server 기동
    cd apps/worker && python -m worker.smoke
"""

from __future__ import annotations

from rq import SimpleWorker

from worker.logging_utils import get_logger
from worker.queue import get_queue, get_redis_connection
from worker.tasks import heartbeat_task

logger = get_logger(__name__)


def main() -> None:
    connection = get_redis_connection()
    queue = get_queue(connection=connection)

    job = queue.enqueue(heartbeat_task)
    logger.info("smoke.enqueued", extra={"event": "smoke_enqueued", "job_id": job.id})

    worker = SimpleWorker([queue], connection=connection)
    worker.work(burst=True)

    result = job.return_value(refresh=True)
    logger.info(
        "smoke.result",
        extra={
            "event": "smoke_result",
            "job_id": job.id,
            "status": job.get_status(),
            "result": result,
        },
    )
    print(f"job {job.id}: status={job.get_status()} result={result!r}")


if __name__ == "__main__":
    main()

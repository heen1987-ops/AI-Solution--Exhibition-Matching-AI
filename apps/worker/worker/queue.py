"""RQ 큐/연결 헬퍼.

의도적으로 연결 객체를 프로세스 전역으로 캐시하지 않는다 - `REDIS_URL`을 환경변수마다
새로 읽어야 하는 테스트(예: 서로 다른 REDIS_URL을 쓰는 테스트 격리)에서 캐시가 stale한
값을 반환하는 문제를 피하기 위함이다(backend 쪽 `get_settings()` lru_cache에서 실제로
겪은 문제 - BAC-001-health.md 핸드오프의 "발견한 버그" 참고). 워커 프로세스 자체는
`run_worker.py`에서 한 번만 만들어 재사용하므로 성능상 문제되지 않는다.
"""

from __future__ import annotations

from redis import Redis
from rq import Queue

from worker.config import get_queue_name, get_redis_url


def get_redis_connection(redis_url: str | None = None) -> Redis:
    return Redis.from_url(redis_url or get_redis_url())


def get_queue(name: str | None = None, connection: Redis | None = None) -> Queue:
    return Queue(name or get_queue_name(), connection=connection or get_redis_connection())

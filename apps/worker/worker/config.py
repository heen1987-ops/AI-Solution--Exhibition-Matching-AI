"""워커 큐 연결 설정.

`backend/.env.example`과 동일한 관례로 `REDIS_URL` 환경변수를 읽는다(백엔드와 워커가
같은 Redis 인스턴스를 공유하는 배포를 전제로 한다 - docker-compose.yml 참고). 새 설정
프레임워크(pydantic-settings 등)를 끌어오지 않고 표준 `os.environ` 조회만으로 충분한
범위다.
"""

from __future__ import annotations

import os

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_QUEUE_NAME = "backju-worker"


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)


def get_queue_name() -> str:
    return os.environ.get("WORKER_QUEUE_NAME", DEFAULT_QUEUE_NAME)

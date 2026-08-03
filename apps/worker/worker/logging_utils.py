"""구조화(JSON) 로그 골격.

`print()` 대신 표준 `logging` 모듈 + 커스텀 JSON `Formatter`만 사용한다 - 이 정도
구조화 로그를 위해 structlog 등 새 의존성을 추가하지 않기로 했다(표준 라이브러리로
충분하다고 판단, `apps/worker/pyproject.toml`에 로깅 전용 의존성 없음).

로그 라인은 항상 하나의 JSON 객체다. `logger.info(msg, extra={...})`로 넘긴 커스텀
필드(event, job_id 등)가 그대로 최상위 키로 병합된다.

민감정보 규칙: 이 모듈 자체는 필드를 걸러내지 않는다 - "로그에 시크릿을 넘기지 않는다"는
책임은 호출자(worker/tasks.py)에 있다. tasks.py는 태스크 payload의 값을 그대로 로그하지
않고 키 이름만 남기는 방식으로 이 규칙을 지킨다(test_worker.py의
`test_task_failure_never_logs_sensitive_payload_values`가 회귀를 잡는다).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_RESERVED_LOGRECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """한 로그 레코드를 한 줄짜리 JSON으로 직렬화한다."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_ATTRS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logger(name: str) -> logging.Logger:
    """모듈별 구조화 로거를 하나 만들어(또는 재사용해) 반환한다."""

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

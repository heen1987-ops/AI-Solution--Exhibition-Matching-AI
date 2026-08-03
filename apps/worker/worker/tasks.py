"""샘플 태스크 (BAC-001 스캐폴딩).

여기 있는 두 태스크는 큐 연결·재시도 정책·구조화 로그가 실제로 동작함을 보여주는
용도일 뿐이다. 실제 AI 문서처리·임베딩 생성 태스크는 이 웨이브에서 구현하지 않는다
(PROJECT_SCOPE.md 제외범위) - 다음 웨이브에서 AI_SEARCH/CONTRACTS 트랙이 실제 도메인
태스크를 이 파일 옆에 추가한다.
"""

from __future__ import annotations

from worker.logging_utils import get_logger

logger = get_logger(__name__)


def heartbeat_task() -> str:
    """가장 단순한 샘플 작업: 큐가 살아서 실제로 job을 처리하는지 확인한다."""

    logger.info("worker.heartbeat", extra={"event": "heartbeat"})
    return "ok"


class IntentionalFailure(RuntimeError):
    """테스트 전용: 재시도 정책을 검증하기 위해 항상 실패하는 태스크가 던지는 예외."""


def always_fails_task(payload: dict[str, object] | None = None) -> None:
    """재시도 정책 검증용 항상-실패 샘플 작업.

    민감정보 미노출 규칙: `payload`의 값(value)은 절대 로그에 남기지 않는다 - 키
    이름만 남긴다. 호출자가 시크릿을 payload에 실수로 넣더라도 로그 라인에는 등장하지
    않아야 한다(테스트로 고정 - test_task_failure_never_logs_sensitive_payload_values).
    """

    keys = sorted((payload or {}).keys())
    logger.warning(
        "worker.always_fails.attempt",
        extra={"event": "always_fails_attempt", "payload_keys": keys},
    )
    raise IntentionalFailure("이 작업은 재시도 정책 테스트를 위해 항상 실패하도록 설계됐다")

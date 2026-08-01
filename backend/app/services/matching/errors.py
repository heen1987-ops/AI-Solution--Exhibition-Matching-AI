"""매칭 파이프라인 공용 예외.

docs/frontend-backend-ai-interface-spec.md 4.4절 오류 응답 봉투와 19절 오류 코드표를 따른다.
``code``는 19절 표에 있는 값을 우선 쓰고, 표에 없는 좀 더 구체적인 사유가 필요하면(19절 마지막
문단: "`CONSENT_REQUIRED`라는 단일 오류로 모든 목적을 묶지 않는다") 표의 HTTP 상태·UI 처리
의도를 그대로 유지하면서 이 모듈에서 세분화한 코드를 추가로 정의한다(각 정의부에 근거 표기).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FieldErrorDetail:
    field: str
    reason: str


class RecommendationError(Exception):
    """파이프라인 어느 단계에서든 요청을 계속 처리할 수 없을 때 던진다.

    라우터가 이 예외를 잡아 인터페이스 명세 4.4절 오류 봉투로 직렬화한다
    (app/api/v1/routers/recommendations.py의 예외 핸들러 참고).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        field_errors: list[FieldErrorDetail] | None = None,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.field_errors = field_errors or []
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def validation_failed(message: str, *, field_errors: list[FieldErrorDetail] | None = None) -> RecommendationError:
    """19절: 400 VALIDATION_FAILED."""

    return RecommendationError(
        "VALIDATION_FAILED", message, http_status=400, field_errors=field_errors
    )


def auth_required(message: str = "인증 또는 세션 정보가 필요합니다.") -> RecommendationError:
    """19절: 401 AUTH_REQUIRED."""

    return RecommendationError("AUTH_REQUIRED", message, http_status=401)


def age_confirmation_required(
    message: str = "연령확인이 필요한 추천입니다.",
) -> RecommendationError:
    """19절: 403 AGE_CONFIRMATION_REQUIRED."""

    return RecommendationError("AGE_CONFIRMATION_REQUIRED", message, http_status=403)


def personalization_disabled(
    message: str = "개인화 추천에 동의하지 않아 일반 탐색만 이용할 수 있습니다.",
) -> RecommendationError:
    """19절: 403 PERSONALIZATION_DISABLED."""

    return RecommendationError("PERSONALIZATION_DISABLED", message, http_status=403)


def profile_incomplete(
    message: str, *, field_errors: list[FieldErrorDetail] | None = None
) -> RecommendationError:
    """19절: 422 PROFILE_INCOMPLETE."""

    return RecommendationError(
        "PROFILE_INCOMPLETE", message, http_status=422, field_errors=field_errors
    )


def no_candidate(message: str = "조건에 맞는 추천 후보가 없습니다.") -> RecommendationError:
    """19절: 422 NO_CANDIDATE."""

    return RecommendationError("NO_CANDIDATE", message, http_status=422, retryable=True)


def resource_forbidden(message: str = "이 리소스에 접근할 권한이 없습니다.") -> RecommendationError:
    """19절: 403 RESOURCE_FORBIDDEN."""

    return RecommendationError("RESOURCE_FORBIDDEN", message, http_status=403)


def idempotency_key_reused(
    message: str = "같은 Idempotency-Key로 다른 요청 본문이 재사용되었습니다.",
) -> RecommendationError:
    """19절: 409 IDEMPOTENCY_KEY_REUSED."""

    return RecommendationError("IDEMPOTENCY_KEY_REUSED", message, http_status=409)


def service_temporarily_unavailable(
    message: str = "행사가 아직 운영 중이 아니거나 일시적으로 추천을 제공할 수 없습니다.",
) -> RecommendationError:
    """19절: 503 SERVICE_TEMPORARILY_UNAVAILABLE."""

    return RecommendationError(
        "SERVICE_TEMPORARILY_UNAVAILABLE", message, http_status=503, retryable=True
    )

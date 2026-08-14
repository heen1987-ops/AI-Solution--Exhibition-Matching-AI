"""HMAC 기반 보안 유틸리티 - 웹훅 서명 검증, 식별정보 조회용 HMAC, 재전송 방지 지문.

근거 문서
---------
- docs/2026-backju-ai-matching-service-design.md
    5.2절: "전화번호·이메일 매칭용 값은 단순 SHA-256이 아니라 서버 비밀키 기반 HMAC을
    사용한다."
    8.2절: "HMAC 서명, 타임스탬프 허용범위, 재전송 방지 ID, 지수 백오프 재시도를 적용한다",
    "웹훅 비밀키는 이벤트·연동처별로 분리하고 순환 가능해야 한다."
- docs/frontend-backend-ai-interface-spec.md 18.2절: 웹훅 요청 헤더 계약.
    ```http
    X-Webhook-ID: wh_001
    X-Webhook-Timestamp: 1785480000
    X-Webhook-Signature: v1=hex-hmac
    ```
    서명은 `v1=` 접두사를 가진 HMAC-SHA256 hex 다이제스트다.

키 관리에 대한 TODO
--------------------
이 모듈의 `_derive_key`는 `Settings.SECRET_KEY` 하나로부터 목적(purpose)별 파생키를
만드는 임시 방편이다. 설계문서 21절("키는 애플리케이션 DB와 분리된 키 관리 서비스에서
관리한다")과 8.2절("웹훅 비밀키는 이벤트·연동처별로 분리하고 순환 가능해야 한다")이 요구하는
실제 KMS/Vault 연동, 원천 시스템별 개별 비밀키 발급·순환은 후속 작업이다. 지금은 단일
SECRET_KEY에서 목적·연동처 코드별로 결정적으로 파생시켜 "같은 입력이면 항상 같은 키"라는
성질만 보장한다. 운영 전환 시 `derive_webhook_secret`을 실제 비밀 저장소 조회로 교체해야 한다.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import time
from dataclasses import dataclass

from app.core.config import get_settings

# HMAC 파생에 쓰는 목적 태그. 서로 다른 태그는 서로 다른 키를 만들어 용도 간 키 재사용을 막는다.
_IDENTITY_LOOKUP_INFO = b"backju-ai-sepha:identity-lookup-hmac:v1"
_WEBHOOK_SECRET_INFO_PREFIX = b"backju-ai-sepha:webhook-secret:v1:"
_PRINCIPAL_FINGERPRINT_INFO = b"backju-ai-sepha:principal-fingerprint:v1"

WEBHOOK_SIGNATURE_SCHEME = "v1"
_WEBHOOK_SIGNATURE_PREFIX = f"{WEBHOOK_SIGNATURE_SCHEME}="

#: 설계문서 8.2절 "타임스탬프 허용범위"의 기본값. 확정 수치는 운영 정책 결정 대상이라
#: TODO로 남기고, 우선 웹훅 재전송 공격을 막을 수 있는 보수적인 값(5분)을 기본값으로 둔다.
DEFAULT_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300


def _derive_key(info: bytes, *, secret: str | None = None) -> bytes:
    """SECRET_KEY(또는 전달된 secret)로부터 목적별 32바이트 키를 파생한다.

    RFC 5869 HKDF의 단순화 버전(HMAC 1회 적용)이다. 진짜 HKDF나 KMS 연동이 필요해지면
    이 함수만 교체하면 되도록 다른 모든 함수는 이 함수를 거쳐서만 키를 얻는다.
    """

    base_secret = (
        secret if secret is not None else get_settings().SECRET_KEY
    ).encode("utf-8")
    return _hmac.new(base_secret, info, hashlib.sha256).digest()


def compute_lookup_hmac(
    value: str, *, purpose: bytes = _IDENTITY_LOOKUP_INFO, secret: str | None = None
) -> bytes:
    """전화번호·이메일 등 조회용(HMAC-SHA256) 다이제스트를 계산한다.

    identity.user_identity.phone_hmac/email_hmac처럼 원문을 복호화하지 않고 동등성 조회만
    할 수 있어야 하는 컬럼에 사용한다. 값은 호출부가 미리 정규화(trim, 하이픈 제거, 국가
    코드 통일 등)해서 넘겨야 한다 - 정규화 규칙은 이 함수의 책임이 아니다.
    """

    key = _derive_key(purpose, secret=secret)
    return _hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def derive_webhook_secret(source_system_code: str, *, secret: str | None = None) -> str:
    """연동처(source_system_code)별 웹훅 공유비밀을 결정적으로 파생한다.

    실제 운영에서는 각 연동처에 개별 발급·순환 가능한 비밀키를 안전한 저장소에 두어야 한다
    (모듈 docstring TODO 참고). 지금은 "연동처마다 다른 키"라는 8.2절의 최소 요건만 만족시키는
    임시 구현이다.
    """

    info = _WEBHOOK_SECRET_INFO_PREFIX + source_system_code.encode("utf-8")
    return _derive_key(info, secret=secret).hex()


def compute_principal_fingerprint(principal_id: str, *, secret: str | None = None) -> bytes:
    """integration.idempotency_record.principal_fingerprint용 HMAC 지문을 계산한다."""

    return _hmac.new(
        _derive_key(_PRINCIPAL_FINGERPRINT_INFO, secret=secret),
        principal_id.encode("utf-8"),
        hashlib.sha256,
    ).digest()


@dataclass(frozen=True)
class SignatureVerification:
    """웹훅 서명·타임스탬프 검증 결과. `valid=False`일 때 `reason`은 안전하게 사용자에게
    노출 가능한 오류 코드다 (원문 예외 메시지가 아니다)."""

    valid: bool
    reason: str | None = None


def compute_webhook_signature(payload: bytes, *, secret: str) -> str:
    """`X-Webhook-Signature` 헤더 전체 값("v1=hex")을 계산한다.

    발신측(원천 시스템 또는 이 값을 검증용으로 재현하는 테스트 코드)이 사용한다.
    """

    digest = _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{_WEBHOOK_SIGNATURE_PREFIX}{digest}"


def verify_webhook_signature(
    payload: bytes, signature_header: str | None, *, secret: str
) -> SignatureVerification:
    """`X-Webhook-Signature: v1=hex-hmac` 헤더를 검증한다 (인터페이스 명세 18.2절).

    - payload는 서명을 계산했을 때와 완전히 동일한 raw 바이트여야 한다 (JSON 재직렬화 금지 -
      키 순서·공백 차이로도 서명이 어긋난다). 호출부는 FastAPI Request.body()의 원문 바이트를
      그대로 넘겨야 한다.
    - 상수시간 비교(hmac.compare_digest)로 타이밍 공격을 방지한다.
    """

    if not signature_header:
        return SignatureVerification(False, "MISSING_SIGNATURE")
    if not signature_header.startswith(_WEBHOOK_SIGNATURE_PREFIX):
        return SignatureVerification(False, "UNSUPPORTED_SIGNATURE_SCHEME")

    provided_hex = signature_header[len(_WEBHOOK_SIGNATURE_PREFIX) :]
    expected_hex = _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(provided_hex, expected_hex):
        return SignatureVerification(False, "SIGNATURE_MISMATCH")
    return SignatureVerification(True)


def verify_webhook_timestamp(
    timestamp_header: str | None,
    *,
    tolerance_seconds: int = DEFAULT_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS,
    now: float | None = None,
) -> SignatureVerification:
    """`X-Webhook-Timestamp`(Unix epoch seconds)가 허용범위 안에 있는지 검사한다.

    허용범위를 벗어난 요청은 재전송 공격이거나 시계 오차로 간주해 거부한다 (설계문서 8.2절
    "타임스탬프 허용범위").
    """

    if not timestamp_header:
        return SignatureVerification(False, "MISSING_TIMESTAMP")
    try:
        sent_at = int(timestamp_header)
    except ValueError:
        return SignatureVerification(False, "INVALID_TIMESTAMP")

    current = now if now is not None else time.time()
    if abs(current - sent_at) > tolerance_seconds:
        return SignatureVerification(False, "TIMESTAMP_OUT_OF_RANGE")
    return SignatureVerification(True)

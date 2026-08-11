"""단기 서명 다운로드 토큰 - "서명된 URL"의 대체물.

작업 지시: "raw storage path나 서명되지 않은 URL을 절대 반환하지 않는다 - 다운로드용으로는
짧은 시간 유효한 서명 토큰만 반환한다." 이 모듈이 그 토큰의 발급/검증을 전담한다.

app/core/security.py를 재사용하지 않고 독립 구현한 이유
----------------------------------------------------------
core/security.py는 이미 여러 동시 작업 에이전트(웹훅/키오스크 등)가 사용 중인 공유 모듈이다.
그 파일의 `_derive_key` 패턴(목적 태그로 SECRET_KEY를 결정적으로 파생)을 그대로 흉내내되,
이 파일 안에 독립적으로 구현해 공유 파일에 대한 동시편집 충돌 위험 없이 문서 다운로드 토큰만의
목적 태그로 키를 파생한다. 두 모듈은 같은 SECRET_KEY 원천에서 파생하지만 목적 태그가 달라
서로 다른 키를 낸다(키 재사용 금지 원칙 - core/security.py 모듈 docstring 참고).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

_TOKEN_KEY_INFO = b"backju-ai-sepha:document-download-token:v1"


def _derive_token_key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), _TOKEN_KEY_INFO, hashlib.sha256).digest()


@dataclass(frozen=True)
class DownloadTokenClaims:
    document_id: UUID
    file_id: UUID
    exhibitor_id: UUID
    expires_at: datetime


def issue_download_token(
    *, document_id: UUID, file_id: UUID, exhibitor_id: UUID, expires_at: datetime, secret: str,
) -> str:
    """document_id/file_id/exhibitor_id/만료시각을 서명해 하나의 불투명 토큰 문자열로 만든다.

    저장소 경로(storage_key)는 이 토큰 어디에도 들어가지 않는다 - 토큰은 "누가 무엇을
    다운로드할 권한이 있는지"만 증명하고, 실제 바이트 조회는 서버가 document_id/file_id로
    DB를 다시 조회해 storage_key를 얻은 뒤 수행한다(app/services/document/service.py의
    resolve_download 참고).
    """

    payload = "|".join(
        [str(document_id), str(file_id), str(exhibitor_id), str(int(expires_at.timestamp()))]
    )
    signature = hmac.new(
        _derive_token_key(secret), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def verify_download_token(
    token: str, *, secret: str, now: float | None = None,
) -> DownloadTokenClaims | None:
    """토큰을 검증한다. 서명이 틀리거나 형식이 잘못됐거나 만료됐으면 None을 반환한다.

    호출부가 None을 404/401 등 안전한 오류로 변환해야 한다 - 이 함수 자체는 "왜" 실패했는지
    구분해 알려주지 않는다(토큰 위조 시도자에게 힌트를 주지 않기 위함 - 타이밍/오라클 공격
    표면을 줄인다).
    """

    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        document_id_s, file_id_s, exhibitor_id_s, expires_s, signature = raw.split("|")
    except (ValueError, UnicodeDecodeError):
        return None

    payload = f"{document_id_s}|{file_id_s}|{exhibitor_id_s}|{expires_s}"
    expected_signature = hmac.new(
        _derive_token_key(secret), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        document_id = UUID(document_id_s)
        file_id = UUID(file_id_s)
        exhibitor_id = UUID(exhibitor_id_s)
        expires_epoch = int(expires_s)
    except ValueError:
        return None

    current = now if now is not None else time.time()
    if current > expires_epoch:
        return None

    return DownloadTokenClaims(
        document_id=document_id,
        file_id=file_id,
        exhibitor_id=exhibitor_id,
        expires_at=datetime.fromtimestamp(expires_epoch, tz=UTC),
    )

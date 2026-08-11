"""콘텐츠 해시 유틸리티 - 중복탐지 근거값(sha256 hex)을 계산한다."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    """업로드 바이트 전체의 sha256 hex digest를 반환한다.

    document.document_file.content_hash와 document.source_document.content_hash에 그대로
    저장되는 값이다. 같은 업체(exhibitor_id) 안에서 이 값이 겹치면 중복 업로드로 간주한다
    (app/services/document/service.py의 find_duplicate 참고).
    """

    return hashlib.sha256(data).hexdigest()

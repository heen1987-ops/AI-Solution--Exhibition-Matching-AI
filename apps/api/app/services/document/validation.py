"""업로드 파일 검증 - 허용 형식, MIME/확장자 일치, 매직바이트 스니핑, 크기 상한.

이 모듈의 모든 함수는 순수 함수다(DB, 스토리지, 네트워크 접근 없음) - 라우터/서비스 계층과
분리해 단위테스트로 충분히 커버할 수 있도록 의도적으로 얇게 유지한다.

방어 계층을 두 겹으로 두는 이유
--------------------------------
1. 확장자 허용목록 (파일명만 보고 즉시 거부 가능 - exe/스크립트/압축파일을 빠르게 차단)
2. 매직바이트 스니핑 (실제 바이트 내용을 보고 "확장자가 주장하는 종류"와 일치하는지 확인)

클라이언트가 보내는 HTTP Content-Type 헤더는 참고용으로만 기록하고 신뢰의 근거로 쓰지
않는다 - 공격자가 완전히 통제할 수 있는 값이라 "MIME 위조"(확장자는 .pdf인데 실제 내용은
다른 것) 탐지에는 무의미하다. 실제 판정은 항상 바이트 내용 스니핑으로 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 작업 지시가 명시한 허용 형식. app/models/document.py DOCUMENT_TYPES(업무 분류)와는 다른
#: 축이다 - 이것은 "파일 확장자" 허용목록이다.
ALLOWED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({"pdf", "docx", "xlsx", "csv", "txt"})

#: 확장자별로 클라이언트가 보내는 Content-Type 헤더가 그나마 그럴듯하다고 인정할 값들
#: (참고 기록용 - 아래 설명대로 신뢰의 근거로는 쓰지 않는다. text/plain은 csv에도 흔히 온다).
_EXTENSION_DECLARED_MIME_HINTS: dict[str, frozenset[str]] = {
    "pdf": frozenset({"application/pdf"}),
    "docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    "xlsx": frozenset(
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ),
    "csv": frozenset({"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"}),
    "txt": frozenset({"text/plain"}),
}

#: 확장자가 명시적으로 금지된 것으로 알려진 위험 형식(실행파일/스크립트/압축파일). 확장자
#: 허용목록에 없으므로 자동으로 걸러지긴 하지만, 오류 메시지를 더 명확히 하기 위해 별도로 든다.
_EXPLICITLY_BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "exe", "bat", "cmd", "sh", "ps1", "msi", "com", "scr", "js", "vbs",
        "zip", "rar", "7z", "tar", "gz", "jar", "apk",
    }
)


class DocumentValidationError(Exception):
    """검증 실패 - 라우터가 안전한 오류코드/메시지로 HTTPException을 만들 때 사용한다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def split_extension(filename: str) -> str:
    """파일명에서 소문자 확장자를 뽑는다(점 제외). 확장자가 없으면 빈 문자열."""

    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].strip().lower()


def check_extension_allowed(filename: str) -> str:
    """확장자가 허용목록에 있는지 확인하고, 있으면 소문자 확장자를 반환한다.

    exe/스크립트/압축파일 등은 허용목록에 없으므로 이 시점에서 이미 거부된다
    (작업 지시 "exe/스크립트/압축파일은 그 자체로 즉시 거부한다").
    """

    extension = split_extension(filename)
    if not extension:
        raise DocumentValidationError(
            "EXTENSION_MISSING", "파일 확장자를 확인할 수 없습니다."
        )
    if extension in _EXPLICITLY_BLOCKED_EXTENSIONS:
        raise DocumentValidationError(
            "EXTENSION_NOT_ALLOWED",
            f"'.{extension}' 형식은 실행파일/스크립트/압축파일로 분류되어 업로드할 수 없습니다.",
        )
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentValidationError(
            "EXTENSION_NOT_ALLOWED",
            f"'.{extension}' 형식은 허용되지 않습니다. "
            f"허용 형식: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}.",
        )
    return extension


def check_size(size_bytes: int, *, max_bytes: int) -> None:
    if size_bytes <= 0:
        raise DocumentValidationError("EMPTY_FILE", "빈 파일은 업로드할 수 없습니다.")
    if size_bytes > max_bytes:
        raise DocumentValidationError(
            "FILE_TOO_LARGE",
            f"파일 크기({size_bytes} bytes)가 최대 허용치({max_bytes} bytes)를 초과했습니다.",
        )


# ---------------------------------------------------------------------------
# 매직바이트 스니핑
# ---------------------------------------------------------------------------

_SNIFF_PREFIX_LEN = 32

# (매직바이트, 종류이름) - 순서가 중요하다(더 구체적인 서명을 먼저 검사).
_BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "pdf"),
    (b"MZ", "exe"),
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),  # JPEG
    (b"GIF87a", "image"),
    (b"GIF89a", "image"),
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),  # empty zip
    (b"PK\x07\x08", "zip"),
)

#: 스니핑 결과 이 종류들은 확장자와 무관하게 항상 거부한다(실행파일/압축/이미지 등 문서
#: 업로드 목적에 맞지 않는 콘텐츠 - 작업 지시 "exe/스크립트/압축파일은 즉시 거부한다"를
#: "확장자를 속여도" 막기 위한 두 번째 방어선).
_ALWAYS_BLOCKED_KINDS: frozenset[str] = frozenset({"exe", "rar", "7z", "gzip", "bzip2", "image"})

#: 확장자별로 허용되는 스니핑 종류. "zip"은 docx/xlsx(둘 다 OOXML = zip 컨테이너)에서만
#: 허용된다 - csv/txt인데 실제로는 zip이면 위장된 압축파일이므로 거부한다.
_EXTENSION_EXPECTED_KINDS: dict[str, frozenset[str]] = {
    "pdf": frozenset({"pdf"}),
    "docx": frozenset({"zip"}),
    "xlsx": frozenset({"zip"}),
    "csv": frozenset({"text"}),
    "txt": frozenset({"text"}),
}


def _looks_like_text(data: bytes) -> bool:
    """앞부분 청크가 사람이 읽을 수 있는 텍스트로 그럴듯한지 대략 판정한다.

    완전한 인코딩 검증이 아니라 "이진 데이터가 아니다"를 걸러내는 휴리스틱이다: NUL 바이트가
    있으면 이진 데이터로 간주하고, UTF-8로 디코드할 수 없어도 이진 데이터로 간주한다.
    """

    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff_content_kind(data: bytes) -> str:
    """업로드 바이트의 앞부분을 검사해 대략적인 콘텐츠 종류를 추정한다.

    반환값은 "pdf" / "zip" / "exe" / "rar" / "7z" / "gzip" / "bzip2" / "image" / "text" /
    "binary_unknown" 중 하나다.
    """

    prefix = data[:_SNIFF_PREFIX_LEN]
    for signature, kind in _BINARY_SIGNATURES:
        if prefix.startswith(signature):
            return kind
    if _looks_like_text(data[:4096]):
        return "text"
    return "binary_unknown"


def check_content_matches_extension(data: bytes, *, extension: str) -> str:
    """스니핑한 콘텐츠 종류가 확장자와 일치하는지 확인한다 (MIME/확장자 일치 검사의 핵심).

    통과 시 스니핑된 kind 문자열을 반환한다(호출부가 로깅/저장에 참고용으로 쓸 수 있게).
    """

    kind = sniff_content_kind(data)
    if kind in _ALWAYS_BLOCKED_KINDS:
        raise DocumentValidationError(
            "CONTENT_NOT_ALLOWED",
            f"파일 내용이 허용되지 않는 형식({kind})으로 감지되었습니다.",
        )
    expected = _EXTENSION_EXPECTED_KINDS.get(extension, frozenset())
    if kind not in expected:
        raise DocumentValidationError(
            "MIME_EXTENSION_MISMATCH",
            f"'.{extension}' 확장자와 실제 파일 내용({kind})이 일치하지 않습니다.",
        )
    return kind


@dataclass(frozen=True)
class ValidatedUpload:
    extension: str
    sniffed_kind: str
    declared_content_type_recognized: bool


def validate_upload(
    *, filename: str, size_bytes: int, data: bytes, declared_content_type: str | None,
    max_bytes: int,
) -> ValidatedUpload:
    """업로드 한 건에 대해 확장자/크기/콘텐츠 검사를 모두 수행한다.

    실패 시 DocumentValidationError를 던진다(가장 먼저 걸리는 검사 기준 - 확장자 -> 크기 ->
    콘텐츠 순서). 통과하면 라우터/서비스가 저장에 사용할 정규화된 정보를 반환한다.
    """

    extension = check_extension_allowed(filename)
    check_size(size_bytes, max_bytes=max_bytes)
    sniffed_kind = check_content_matches_extension(data, extension=extension)

    hints = _EXTENSION_DECLARED_MIME_HINTS.get(extension, frozenset())
    declared_recognized = declared_content_type is not None and declared_content_type in hints

    return ValidatedUpload(
        extension=extension,
        sniffed_kind=sniffed_kind,
        declared_content_type_recognized=declared_recognized,
    )

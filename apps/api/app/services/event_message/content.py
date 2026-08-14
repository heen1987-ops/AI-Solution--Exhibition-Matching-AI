"""Content restriction: markdown or a small safe HTML subset only (task spec).

No arbitrary tags, no script execution, no external tracking pixels, no arbitrary external
links beyond an allowlist (internal routes are always fine).

Implementation notes
---------------------
No HTML-sanitizer dependency (bleach/nh3) is installed in ``apps/api/pyproject.toml`` and this
track does not own that file (BACKEND-owned per ``.harness/locks.yaml``), so this module is
written on the Python standard library's ``html.parser.HTMLParser`` only - no new dependency.

Body text is treated as markdown by default (plain text, `**bold**`, `- list`, etc. all pass
through untouched - a parser never even sees a "tag" in that text because there is no `<`). The
validator only inspects the small subset of literal HTML tags this domain explicitly allows
(``ALLOWED_TAGS``); anything else - ``<script>``, ``<img>`` (this is *why* there is no external
tracking pixel path: ``<img>`` is not in ``ALLOWED_TAGS`` at all, so no image, tracking or
otherwise, can ever appear in a message body), ``<iframe>``, ``<style>``, ``<object>``,
``<embed>``, ``<form>``, ``<svg>``, ``<link>``, ``<meta>``, any ``on*=`` event-handler
attribute, a ``style`` attribute, or a ``javascript:``/``data:`` URL - is rejected outright with
a typed error rather than silently stripped, so an operator always sees exactly why their draft
was rejected instead of a silently mutated body.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

#: The only HTML tags this domain's content editor may emit. Deliberately excludes <img> (the
#: module docstring's tracking-pixel guarantee), <script>/<style>/<iframe>/<object>/<embed>/
#: <form>/<svg>/<link>/<meta>, and anything else not needed for a short operational notice.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {"p", "br", "b", "strong", "i", "em", "ul", "ol", "li", "a", "span"}
)

#: Per-tag allowed attributes. Every other attribute (style, id, class, any on*, ...) is
#: rejected. Only <a> takes an attribute at all (href).
ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {"a": frozenset({"href"})}

#: Hosts external links may point to, beyond always-allowed internal routes ("/..."). Empty by
#: default (Blocker Score < 7 safest-reversible-default per AGENTS.md/task instructions: no
#: canonical public domain for this event exists yet in any harness doc, so the safe default is
#: "no external links at all" rather than guessing a domain). Extend this tuple, not the
#: validator logic, once an operator-facing configuration surface exists.
ALLOWED_EXTERNAL_HOSTS: frozenset[str] = frozenset()

_DANGEROUS_URL_SCHEMES = ("javascript:", "data:", "vbscript:")


class ContentValidationError(ValueError):
    """Raised when message body content violates the safe-subset content policy."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass
class _Violation:
    reason_code: str
    message: str


class _SafeSubsetParser(HTMLParser):
    """Walks the body and records every policy violation (does not mutate/strip anything -
    this validator never "cleans" content, it only accepts or rejects it wholesale, so an
    operator is never surprised by silently-removed content reaching a real audience)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[_Violation] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)

    def _check_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower not in ALLOWED_TAGS:
            self.violations.append(
                _Violation("TAG_NOT_ALLOWED", f"허용되지 않은 태그입니다: <{tag}>")
            )
            return

        allowed_attrs = ALLOWED_ATTRIBUTES.get(tag_lower, frozenset())
        for attr_name, attr_value in attrs:
            attr_lower = attr_name.lower()
            if attr_lower.startswith("on"):
                self.violations.append(
                    _Violation(
                        "EVENT_HANDLER_ATTRIBUTE",
                        f"이벤트 핸들러 속성은 허용되지 않습니다: {attr_name}",
                    )
                )
                continue
            if attr_lower not in allowed_attrs:
                self.violations.append(
                    _Violation(
                        "ATTRIBUTE_NOT_ALLOWED",
                        f"<{tag}> 태그에서 허용되지 않은 속성입니다: {attr_name}",
                    )
                )
                continue
            if attr_lower == "href":
                self._check_href(attr_value or "")

    def _check_href(self, href: str) -> None:
        normalized = href.strip().lower()
        if any(normalized.startswith(scheme) for scheme in _DANGEROUS_URL_SCHEMES):
            self.violations.append(
                _Violation("DANGEROUS_URL_SCHEME", f"허용되지 않은 링크 스킴입니다: {href}")
            )
            return
        if normalized.startswith("/") and not normalized.startswith("//"):
            return  # internal route - always allowed (task spec). "//host" (protocol-relative)
            # is deliberately NOT treated as internal - it resolves to an external origin in a
            # browser exactly like "https://host" does.
        if "://" in normalized:
            host = normalized.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
            if host not in ALLOWED_EXTERNAL_HOSTS:
                self.violations.append(
                    _Violation(
                        "EXTERNAL_URL_NOT_ALLOWLISTED",
                        f"허용 목록에 없는 외부 링크입니다: {href}",
                    )
                )
            return
        # Relative-but-not-rooted (e.g. "foo/bar") or a bare "//host" protocol-relative URL -
        # neither is a recognizable internal route, treat conservatively as external/unknown.
        self.violations.append(
            _Violation("EXTERNAL_URL_NOT_ALLOWLISTED", f"허용 목록에 없는 외부 링크입니다: {href}")
        )


def validate_content(body: str) -> None:
    """Raise ``ContentValidationError`` on the first policy violation found in ``body``.

    Plain markdown/text with no HTML tags always passes (there is nothing for the parser to
    reject). This is intentionally whole-document validation, not per-field - callers must
    call it on the final body exactly as it will be stored/rendered.
    """

    parser = _SafeSubsetParser()
    parser.feed(body)
    parser.close()
    if parser.violations:
        first = parser.violations[0]
        raise ContentValidationError(first.reason_code, first.message)


def validate_destination_screen(destination_screen: str) -> None:
    """Task spec: destination screen is always an internal route. Mirrors the DB CHECK
    (``destination_screen_is_internal_route`` in app/models/event_message.py) so the same rule
    fails fast with a typed error before ever reaching the database."""

    if (
        not destination_screen.startswith("/")
        or destination_screen.startswith("//")
        or "://" in destination_screen
    ):
        raise ContentValidationError(
            "DESTINATION_SCREEN_NOT_INTERNAL",
            "대상 화면은 내부 경로(/로 시작, //로 시작하는 프로토콜 상대 URL은 제외)만 허용됩니다.",
        )

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUEST_WEB_ENTRY_PATHS = [
    ROOT / "apps/user-web/app/(screens)/search",
    ROOT / "apps/user-web/app/(screens)/signup",
]
PERSONAL_INPUT = re.compile(
    r"<input\b[^>]*(type=[\"']?(email|tel|password)[\"']?|"
    r"(name|id|placeholder|aria-label)=[\"'][^\"']*"
    r"(email|phone|tel|address|password|이메일|전화|연락처|주소|비밀번호|성명|실명)"
    r"[^\"']*[\"'])",
    re.IGNORECASE | re.DOTALL,
)


def test_guest_web_entry_surfaces_do_not_collect_personal_data() -> None:
    violations: list[str] = []
    for root in GUEST_WEB_ENTRY_PATHS:
        for path in root.rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            for match in PERSONAL_INPUT.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(ROOT)}:{line}")

    assert violations == []

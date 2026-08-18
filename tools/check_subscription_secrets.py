from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (PROJECT_ROOT / "app", PROJECT_ROOT / "config", PROJECT_ROOT / "docs")
SKIP = {Path(__file__).resolve()}
PATTERNS = (
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"whsec_[A-Za-z0-9]{16,}"),
    re.compile(r"re_[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def find_issues() -> list[str]:
    issues: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.resolve() in SKIP or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(pattern.search(text) for pattern in PATTERNS):
                issues.append(str(path.relative_to(PROJECT_ROOT)))
    return sorted(set(issues))


def main() -> int:
    issues = find_issues()
    if issues:
        print("SECRET_SCAN: NG")
        for issue in issues:
            print("-", issue)
        return 1
    print("SECRET_SCAN: OK")
    print("- Stripe/Resend private values: not embedded")
    print("- Private keys: not embedded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

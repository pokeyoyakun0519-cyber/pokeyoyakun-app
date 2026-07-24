from __future__ import annotations

import json
import sys
from pathlib import Path

from core.gmail_result_service import GmailResultService


def main() -> int:
    output_path = Path(sys.argv[1])
    missing = GmailResultService.missing_dependencies()
    output_path.write_text(
        json.dumps(
            {
                "ok": not missing,
                "missing": missing,
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

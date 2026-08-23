from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "release" / "user_dist_rc5"


def isolated_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["LOCALAPPDATA"] = str(root)
    environment["POKEYOYA_DATA_ROOT"] = str(root / "PokeyoyaKun")
    return environment


def main() -> None:
    user_exe = DIST_DIR / "ポケヨヤ君.exe"
    settings_exe = DIST_DIR / "ポケヨヤ君_設定.exe"
    if not user_exe.is_file() or not settings_exe.is_file():
        raise SystemExit("Frozen User/Settings EXEが見つかりません。")

    with tempfile.TemporaryDirectory(prefix="pokeyoya_navigation_smoke_") as directory:
        root = Path(directory)
        result_path = root / "navigation_result.json"
        environment = isolated_environment(root)
        environment["POKEYOYA_NAVIGATION_SMOKE_RESULT"] = str(result_path)
        subprocess.run(
            [str(user_exe), "--navigation-smoke-test"],
            env=environment, cwd=PROJECT_ROOT, timeout=60, check=True,
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("rounds") != 3 or result.get("page_count") != 8:
            raise SystemExit(f"Frozen navigation smokeが未完了です: {result}")
        if result.get("child_process_count") or result.get("visible_auxiliary_window_count"):
            raise SystemExit(f"画面遷移中に小窓候補を検出しました: {result}")
        subprocess.run(
            [str(settings_exe), "--smoke-test"],
            env=isolated_environment(root / "settings"),
            cwd=PROJECT_ROOT, timeout=60, check=True,
        )
        print("FROZEN_NAVIGATION_SMOKE: OK")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        print("FROZEN_SETTINGS_SMOKE: OK")


if __name__ == "__main__":
    main()

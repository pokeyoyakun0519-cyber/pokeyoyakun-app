from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "installer" / "PokeyoyaKun_Owner_Setup.iss"
OUTPUT = (
    PROJECT_ROOT
    / "release"
    / "owner_installer_rc3"
    / "PokeyoyaKun_Owner_Setup_Ver1.25.0_RC3.exe"
)


def find_iscc() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe"
        )
    for path in candidates:
        if path.exists():
            return path
    value = shutil.which("ISCC.exe")
    return Path(value) if value else None


def main() -> None:
    if "github_assets" in {part.lower() for part in OUTPUT.parts}:
        raise SystemExit("Owner Editionを公開用フォルダーへ出力できません。")
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Inno Setup 6が見つかりません。")
    completed = subprocess.run([str(iscc), str(SCRIPT)])
    if completed.returncode != 0:
        raise SystemExit("Owner Editionインストーラー作成に失敗しました。")
    print("Owner Editionインストーラーを作成しました（配布禁止）。")
    print(OUTPUT)


if __name__ == "__main__":
    main()

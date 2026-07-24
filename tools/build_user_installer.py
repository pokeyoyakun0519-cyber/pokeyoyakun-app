from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PROJECT_ROOT
    / "installer"
    / "PokeyoyaKun_User_Setup.iss"
)
OUTPUT_DIR = PROJECT_ROOT / "release" / "user_installer_rc4_vps_key"
OUTPUT_BASENAME = "PokeyoyaKun_User_Setup_Ver1.25.0_RC4_VPSKey"


def find_iscc() -> Path | None:
    candidates = [
        Path(
            r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        ),
        Path(
            r"C:\Program Files\Inno Setup 6\ISCC.exe"
        ),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data)
            / "Programs"
            / "Inno Setup 6"
            / "ISCC.exe"
        )
    for path in candidates:
        if path.exists():
            return path

    value = shutil.which("ISCC.exe")
    return (
        Path(value)
        if value
        else None
    )


def main() -> None:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit(
            "Inno Setup 6が見つかりません。"
            "公式サイトからインストール後、もう一度実行してください。"
        )

    completed = subprocess.run([
        str(iscc),
        f"/DBuildOutputDir={OUTPUT_DIR}",
        f"/DBuildOutputBaseFilename={OUTPUT_BASENAME}",
        str(SCRIPT),
    ])
    if completed.returncode != 0:
        raise SystemExit(
            "User Editionインストーラー作成に失敗しました。"
        )

    print(
        "User Editionインストーラーを作成しました。"
    )
    print(
        OUTPUT_DIR / f"{OUTPUT_BASENAME}.exe"
    )


if __name__ == "__main__":
    main()

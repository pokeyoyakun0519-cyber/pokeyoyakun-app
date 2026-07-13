from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
ASSETS_DIR = PROJECT_ROOT / "assets"
INSTALLER_DIR = PROJECT_ROOT / "installer"
DIST_DIR = PROJECT_ROOT / "release" / "user_dist"
TEMP_BUILD_ROOT = (
    Path(tempfile.gettempdir())
    / "PokeyoyaKun_UserEdition_Ver1.24.0_RC"
)
BUILD_DIR = TEMP_BUILD_ROOT / "build"
SPEC_DIR = TEMP_BUILD_ROOT / "spec"

ICON_PATH = ASSETS_DIR / "pokeyoya_icon.ico"
VERSION_FILE = INSTALLER_DIR / "version_info.txt"

TARGETS = (
    {
        "name": "ポケヨヤ君_Updater",
        "script": PROJECT_ROOT / "tools" / "apply_update.py",
    },
    {
        "name": "ポケヨヤ君",
        "script": APP_DIR / "monitor_main.py",
    },
    {
        "name": "ポケヨヤ君_設定",
        "script": APP_DIR / "settings_main.py",
    },
)


def run(command: list[str]) -> None:
    print("\n>", " ".join(command))
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(
            f"コマンドに失敗しました。終了コード: {completed.returncode}"
        )


def ensure_dependencies() -> None:
    packages = (
        "pyinstaller",
        "PySide6",
        "google-api-python-client",
        "google-auth-oauthlib",
        "google-auth-httplib2",
    )
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        *packages,
    ])


def clean() -> None:
    for folder in (
        BUILD_DIR,
        SPEC_DIR,
    ):
        if folder.exists():
            shutil.rmtree(folder)

    # OneDrive配下の空フォルダーはクラウド用ReparsePointとなり、
    # shutil.rmtreeでアクセス拒否になることがある。配布フォルダー
    # 自体は残し、前回生成したファイルだけを削除する。
    DIST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    for path in DIST_DIR.iterdir():
        if path.is_file():
            path.unlink()

    BUILD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    SPEC_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def build_target(
    target: dict[str, Path | str],
) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        str(target["name"]),
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(
            BUILD_DIR
            / str(target["name"])
        ),
        "--specpath",
        str(SPEC_DIR),
        "--paths",
        str(APP_DIR),
        "--icon",
        str(ICON_PATH),
        "--version-file",
        str(VERSION_FILE),
        "--add-data",
        f"{ASSETS_DIR};assets",
        "--collect-all",
        "googleapiclient",
        "--collect-all",
        "google_auth_oauthlib",
        "--collect-all",
        "google.oauth2",
        str(target["script"]),
    ]
    run(command)


def verify_user_edition() -> None:
    required = (
        "ポケヨヤ君.exe",
        "ポケヨヤ君_設定.exe",
        "ポケヨヤ君_Updater.exe",
    )
    missing = [
        name
        for name in required
        if not (
            DIST_DIR
            / name
        ).exists()
    ]
    if missing:
        raise SystemExit(
            "利用者版EXEが不足しています: "
            + ", ".join(missing)
        )

    forbidden_names = (
        "admin",
        "administrator",
        "license_server",
        "plugin_server",
        "update_server",
        "release_check",
        "admin_cli",
    )
    for path in DIST_DIR.rglob("*"):
        lowered = path.name.lower()
        if any(
            token in lowered
            for token in forbidden_names
        ):
            raise SystemExit(
                "利用者版へ管理用ファイルが混入しました: "
                + str(path)
            )


def main() -> None:
    print("ポケヨヤ君 User Editionをビルドします。")
    print("管理サーバー・管理CLI・開発ツールは含めません。")
    ensure_dependencies()
    clean()

    for target in TARGETS:
        build_target(target)

    for folder in (
        "config",
        "data",
        "logs",
        "backup",
        "temp",
    ):
        (
            DIST_DIR
            / folder
        ).mkdir(
            parents=True,
            exist_ok=True,
        )

    for file_name in (
        "README.txt",
        "使用方法.txt",
    ):
        source = (
            PROJECT_ROOT
            / file_name
        )
        if source.exists():
            shutil.copy2(
                source,
                DIST_DIR
                / file_name,
            )

    icon_png = (
        ASSETS_DIR
        / "pokeyoya_icon.png"
    )
    if icon_png.exists():
        shutil.copy2(
            icon_png,
            DIST_DIR
            / icon_png.name,
        )

    verify_user_edition()

    print("\nUser Edition EXEビルド完了")
    print(DIST_DIR)
    print(
        "通常権限で動作し、設定は"
        "%LOCALAPPDATA%\\PokeyoyaKunへ保存されます。"
    )


if __name__ == "__main__":
    main()

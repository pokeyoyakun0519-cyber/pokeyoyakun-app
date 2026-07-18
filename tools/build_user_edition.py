from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_security import (
    scan_repository,
    verify_public_license_endpoint,
    verify_distribution,
    write_integrity_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_OWNER_EDITION = False
APP_DIR = PROJECT_ROOT / "app"
ASSETS_DIR = PROJECT_ROOT / "assets"
INSTALLER_DIR = PROJECT_ROOT / "installer"
DIST_DIR = PROJECT_ROOT / "release" / "user_dist_rc4"
TEMP_BUILD_ROOT = (
    Path(tempfile.gettempdir())
    / "PokeyoyaKun_UserEdition_Ver1.25.0_RC4"
)
BUILD_DIR = TEMP_BUILD_ROOT / "build"
SPEC_DIR = TEMP_BUILD_ROOT / "spec"

ICON_PATH = ASSETS_DIR / "pokeyoya_icon.ico"
VERSION_FILE = INSTALLER_DIR / "version_info.txt"

TARGETS = (
    {
        "name": "PokeyoyaKunUpdater",
        "script": PROJECT_ROOT / "tools" / "user_updater_main.py",
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
        "certifi",
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
        "--optimize",
        "2",
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
        "--add-data",
        f"{APP_DIR / 'core' / 'online_license_endpoint.json'};core",
        "--collect-all",
        "googleapiclient",
        "--collect-all",
        "google_auth_oauthlib",
        "--collect-all",
        "google.oauth2",
        "--hidden-import",
        "google.auth.transport.requests",
        "--hidden-import",
        "google.oauth2.credentials",
        "--hidden-import",
        "google_auth_oauthlib.flow",
        "--hidden-import",
        "googleapiclient.discovery",
        "--collect-data",
        "certifi",
        "--exclude-module",
        "tests",
        "--exclude-module",
        "unittest",
        "--exclude-module",
        "pdb",
        "--exclude-module",
        "core.admin_auth",
        "--exclude-module",
        "core.license_crypto",
        "--exclude-module",
        "core.owner_update_manager",
        "--exclude-module",
        "core.owner_update_profile",
        str(target["script"]),
    ]
    run(command)


def verify_user_edition() -> None:
    required = (
        "ポケヨヤ君.exe",
        "ポケヨヤ君_設定.exe",
        "PokeyoyaKunUpdater.exe",
        "release-integrity.json",
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

    errors = verify_distribution(DIST_DIR)
    if errors:
        raise SystemExit("\n".join(errors))


def main() -> None:
    print("ポケヨヤ君 User Editionをビルドします。")
    print("管理サーバー・管理CLI・開発ツールは含めません。")
    verify_public_license_endpoint(PROJECT_ROOT)
    findings = scan_repository(PROJECT_ROOT)
    if findings:
        raise SystemExit(
            "秘密情報の可能性があるためビルドを中止しました:\n- "
            + "\n- ".join(findings)
        )
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

    public_files = (
        ("USER_EDITION_README.txt", "README.txt"),
        ("使用方法.txt", "使用方法.txt"),
    )
    for source_name, destination_name in public_files:
        source = PROJECT_ROOT / source_name
        if source.exists():
            shutil.copy2(
                source,
                DIST_DIR / destination_name,
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

    write_integrity_manifest(
        DIST_DIR,
        [f"{target['name']}.exe" for target in TARGETS],
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

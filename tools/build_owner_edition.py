from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_security import (
    scan_repository,
    verify_distribution,
    write_integrity_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_OWNER_EDITION = True
APP_DIR = PROJECT_ROOT / "app"
ASSETS_DIR = PROJECT_ROOT / "assets"
INSTALLER_DIR = PROJECT_ROOT / "installer"
DIST_DIR = PROJECT_ROOT / "release" / "owner_dist_rc3"
TEMP_BUILD_ROOT = Path(tempfile.gettempdir()) / "PokeyoyaKun_Owner_Ver1.25.0_RC3"
BUILD_DIR = TEMP_BUILD_ROOT / "build"
SPEC_DIR = TEMP_BUILD_ROOT / "spec"
ICON_PATH = ASSETS_DIR / "pokeyoya_icon.ico"
VERSION_FILE = INSTALLER_DIR / "owner_version_info.txt"

TARGETS = (
    {
        "name": "PokeyoyaKunOwnerUpdater",
        "script": PROJECT_ROOT / "tools" / "owner_updater_main.py",
    },
    {
        "name": "PokeyoyaKun_OwnerEdition",
        "script": APP_DIR / "owner_main.py",
    },
    {
        "name": "PokeyoyaKun_Owner_Settings",
        "script": APP_DIR / "settings_main.py",
    },
)

LICENSE_MODULE_EXCLUSIONS = (
    "ui.license_dialog",
    "ui.online_license_page",
    "core.license_manager",
    "core.online_license_client",
    "core.online_license_config",
    "core.offline_license",
    "core.update_manager",
    "core.user_update_profile",
)


def run(command: list[str]) -> None:
    print("\n>", " ".join(command))
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise SystemExit(
            f"コマンドに失敗しました。終了コード: {completed.returncode}"
        )


def ensure_dependencies() -> None:
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "pyinstaller",
        "PySide6",
        "certifi",
        "google-api-python-client",
        "google-auth-oauthlib",
        "google-auth-httplib2",
        "keyring",
    ])


def clean() -> None:
    for folder in (BUILD_DIR, SPEC_DIR):
        if folder.exists():
            shutil.rmtree(folder)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    for path in DIST_DIR.iterdir():
        if path.is_file():
            path.unlink()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)


def build_target(target: dict[str, Path | str]) -> None:
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
        str(BUILD_DIR / str(target["name"])),
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
        f"{APP_DIR / 'resources'};resources",
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
        "--collect-all",
        "keyring",
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
    ]
    for module in LICENSE_MODULE_EXCLUSIONS:
        command.extend(("--exclude-module", module))
    command.append(str(target["script"]))
    run(command)


def verify_owner_edition() -> None:
    required = (
        "PokeyoyaKun_OwnerEdition.exe",
        "PokeyoyaKun_Owner_Settings.exe",
        "release-integrity.json",
        "OWNER_EDITION_README.txt",
    )
    missing = [name for name in required if not (DIST_DIR / name).exists()]
    if missing:
        raise SystemExit("Owner Edition成果物が不足しています: " + ", ".join(missing))

    if "github_assets" in {part.lower() for part in DIST_DIR.parts}:
        raise SystemExit("Owner Editionを公開用フォルダーへ出力できません。")

    errors = verify_distribution(DIST_DIR)
    if errors:
        raise SystemExit("\n".join(errors))

    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(DIST_DIR / "PokeyoyaKun_OwnerEdition.exe"))
    if "certifi\\cacert.pem" not in archive.toc:
        raise SystemExit("Owner Edition EXEにcertifi/cacert.pemがありません。")
    pyz = archive.open_embedded_archive("PYZ.pyz")
    module_names = {name.lower() for name in pyz.toc}
    forbidden_modules = {
        module.lower()
        for module in LICENSE_MODULE_EXCLUSIONS
    }
    included_forbidden = sorted(module_names & forbidden_modules)
    if included_forbidden:
        raise SystemExit(
            "Owner Edition EXEにライセンスモジュールが混入しました: "
            + ", ".join(included_forbidden)
        )
    required_tls_modules = {
        "core.secure_https",
        "core.feedback_api",
        "core.public_roadmap",
    }
    missing_tls = sorted(required_tls_modules - module_names)
    if missing_tls:
        raise SystemExit(
            "Owner Edition EXEに必要なHTTPSモジュールがありません: "
            + ", ".join(missing_tls)
        )


def main() -> None:
    if not BUILD_OWNER_EDITION:
        raise SystemExit("Owner Edition専用ビルドフラグが無効です。")
    print("警告: Owner Edition（開発者専用・配布禁止）をビルドします。")
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

    shutil.copy2(
        PROJECT_ROOT / "OWNER_EDITION_README.txt",
        DIST_DIR / "OWNER_EDITION_README.txt",
    )
    icon_png = ASSETS_DIR / "pokeyoya_icon.png"
    if icon_png.exists():
        shutil.copy2(icon_png, DIST_DIR / icon_png.name)

    write_integrity_manifest(
        DIST_DIR,
        [f"{target['name']}.exe" for target in TARGETS],
    )
    verify_owner_edition()
    print("\nOwner Edition EXEビルド完了（公開・配布禁止）")
    print(DIST_DIR)


if __name__ == "__main__":
    main()

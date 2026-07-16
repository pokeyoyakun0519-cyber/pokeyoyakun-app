from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_security import scan_repository, verify_distribution, write_integrity_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
ASSETS_DIR = PROJECT_ROOT / "assets"
DIST_DIR = PROJECT_ROOT / "release" / "user_dist_nuitka"
BUILD_ROOT = Path(tempfile.gettempdir()) / "PokeyoyaKun_Nuitka_Ver1.25.0_RC2"
ICON_PATH = ASSETS_DIR / "pokeyoya_icon.ico"

TARGETS = (
    ("ポケヨヤ君_Updater", PROJECT_ROOT / "tools" / "apply_update.py"),
    ("ポケヨヤ君", APP_DIR / "monitor_main.py"),
    ("ポケヨヤ君_設定", APP_DIR / "settings_main.py"),
)


def run(command: list[str]) -> None:
    print("\n>", " ".join(command))
    completed = subprocess.run(command)
    if completed.returncode:
        raise SystemExit(f"コマンドに失敗しました。終了コード: {completed.returncode}")


def ensure_dependencies() -> None:
    run([
        sys.executable, "-m", "pip", "install",
        "nuitka", "ordered-set", "zstandard", "PySide6",
        "google-api-python-client", "google-auth-oauthlib", "google-auth-httplib2",
    ])


def clean() -> None:
    for folder in (DIST_DIR, BUILD_ROOT):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)


def build_target(name: str, script: Path) -> None:
    output_dir = BUILD_ROOT / name
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "nuitka",
        "--mode=onefile",
        "--assume-yes-for-downloads",
        "--remove-output",
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={ICON_PATH}",
        "--company-name=PokeyoyaKun Project",
        "--product-name=ポケヨヤ君 User Edition",
        "--file-version=1.25.0.2",
        "--product-version=1.25.0.2",
        f"--output-dir={output_dir}",
        f"--output-filename={name}.exe",
        f"--include-data-dir={ASSETS_DIR}=assets",
        (
            "--include-data-files="
            f"{APP_DIR / 'core' / 'online_license_endpoint.json'}="
            "core/online_license_endpoint.json"
        ),
        "--include-package=googleapiclient",
        "--include-package=google_auth_oauthlib",
        "--include-package=google.oauth2",
        "--nofollow-import-to=tests,unittest,pdb,core.admin_auth,core.license_crypto",
        str(script),
    ]
    run(command)
    built = output_dir / f"{name}.exe"
    if not built.is_file():
        raise SystemExit(f"Nuitka出力が見つかりません: {built}")
    shutil.move(str(built), DIST_DIR / built.name)


def copy_public_files() -> None:
    for source_name, destination_name in (
        ("USER_EDITION_README.txt", "README.txt"),
        ("使用方法.txt", "使用方法.txt"),
    ):
        source = PROJECT_ROOT / source_name
        if source.is_file():
            shutil.copy2(source, DIST_DIR / destination_name)
    icon = ASSETS_DIR / "pokeyoya_icon.png"
    if icon.is_file():
        shutil.copy2(icon, DIST_DIR / icon.name)


def main() -> None:
    print("NuitkaによるUser Editionネイティブビルドを開始します。")
    findings = scan_repository(PROJECT_ROOT)
    if findings:
        raise SystemExit("秘密情報の可能性があります:\n- " + "\n- ".join(findings))
    ensure_dependencies()
    clean()
    for name, script in TARGETS:
        build_target(name, script)
    copy_public_files()
    write_integrity_manifest(DIST_DIR, [f"{name}.exe" for name, _ in TARGETS])
    errors = verify_distribution(DIST_DIR)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"\nNuitka User Editionビルド完了: {DIST_DIR}")


if __name__ == "__main__":
    main()

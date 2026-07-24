import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
ASSETS_DIR = PROJECT_ROOT / "assets"
INSTALLER_DIR = PROJECT_ROOT / "installer"
DIST_DIR = PROJECT_ROOT / "release" / "dist"
BUILD_DIR = PROJECT_ROOT / "release" / "build"
SPEC_DIR = PROJECT_ROOT / "release" / "spec"

ICON_PATH = ASSETS_DIR / "pokeyoya_icon.ico"
VERSION_FILE = INSTALLER_DIR / "version_info.txt"


TARGETS = [

{
    "name": "ポケヨヤ君_Updater",
    "script": PROJECT_ROOT / "tools" / "apply_update.py",
    "console": False,
},
    {
        "name": "ポケヨヤ君",
        "script": APP_DIR / "monitor_main.py",
        "console": False,
    },
    {
        "name": "ポケヨヤ君_設定",
        "script": APP_DIR / "settings_main.py",
        "console": False,
    },
]


def run(command: list[str]) -> None:
    print("\n>", " ".join(command))
    completed = subprocess.run(command)

    if completed.returncode != 0:
        raise SystemExit(
            f"コマンドに失敗しました。終了コード: {completed.returncode}"
        )


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstallerをインストールします。")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "pyinstaller",
        ])



def ensure_gmail_dependencies() -> None:
    required = [
        "google-api-python-client",
        "google-auth-oauthlib",
        "google-auth-httplib2",
    ]

    try:
        import googleapiclient.discovery  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
    except ImportError:
        print("Gmail連携ライブラリをインストールします。")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            *required,
        ])


def clean() -> None:
    for folder in [DIST_DIR, BUILD_DIR, SPEC_DIR]:
        if folder.exists():
            shutil.rmtree(folder)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)


def build_target(target: dict) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        target["name"],
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / target["name"]),
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
        "--add-data",
        f"{APP_DIR / 'core' / 'online_license_public_keys.json'};core",
        "--collect-all",
        "googleapiclient",
        "--collect-all",
        "google_auth_oauthlib",
        "--collect-all",
        "google.oauth2",
    ]

    command.append(
        "--console" if target["console"] else "--windowed"
    )
    command.append(str(target["script"]))
    run(command)


def copy_runtime_folders() -> None:
    for folder_name in [
        "config",
        "data",
        "logs",
        "temp",
        "backup",
    ]:
        (DIST_DIR / folder_name).mkdir(
            parents=True,
            exist_ok=True,
        )

    readme = PROJECT_ROOT / "README.txt"
    if readme.exists():
        shutil.copy2(
            readme,
            DIST_DIR / "README.txt",
        )

    icon_png = ASSETS_DIR / "pokeyoya_icon.png"
    if icon_png.exists():
        shutil.copy2(
            icon_png,
            DIST_DIR / "pokeyoya_icon.png",
        )





def cleanup_runtime_data() -> None:
    cleanup_script = (
        PROJECT_ROOT
        / "tools"
        / "cleanup_runtime_files.py"
    )
    run([
        sys.executable,
        str(cleanup_script),
    ])


def run_release_check() -> None:
    check_script = PROJECT_ROOT / "tools" / "release_check.py"
    run([sys.executable, str(check_script)])


def run_project_check() -> None:
    check_script = PROJECT_ROOT / "tools" / "check_project.py"
    run([sys.executable, str(check_script)])


def run_source_smoke_test() -> None:
    smoke_script = (
        PROJECT_ROOT
        / "tools"
        / "run_smoke_test.py"
    )
    run([
        sys.executable,
        str(smoke_script),
    ])


def main() -> None:
    print("ポケヨヤ君 RC EXEビルドを開始します。")
    cleanup_runtime_data()
    run_release_check()
    run_project_check()
    run_source_smoke_test()
    ensure_pyinstaller()
    ensure_gmail_dependencies()
    clean()

    for target in TARGETS:
        build_target(target)

    copy_runtime_folders()

    print("\nビルドが完了しました。")
    print(f"出力先: {DIST_DIR}")
    print("EXEへアイコンとバージョン情報を埋め込みました。")
    print("Administrator版は友達へ配布しないでください。")


if __name__ == "__main__":
    main()

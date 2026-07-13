from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
DIST_DIR = PROJECT_ROOT / "release" / "dist"


def run_command(
    command: list[str],
    *,
    timeout: int,
    env: dict[str, str],
) -> None:
    print(">", " ".join(command))

    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            "スモークテストがタイムアウトしました。"
        )

    if completed.returncode != 0:
        raise SystemExit(
            "スモークテストに失敗しました。"
            f"終了コード: {completed.returncode}"
        )


def build_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(APP_DIR)

    # 画面を実際に表示せず、Qtの画面生成だけ確認する。
    env.setdefault(
        "QT_QPA_PLATFORM",
        "offscreen",
    )

    # テスト中のログや設定を専用の一時フォルダーへ分離する。
    temp_root = Path(
        tempfile.mkdtemp(
            prefix="pokeyoya_smoke_",
        )
    )
    env["LOCALAPPDATA"] = str(temp_root)

    return env


def run_source_test() -> None:
    env = build_environment()
    run_command(
        [
            sys.executable,
            str(APP_DIR / "monitor_main.py"),
            "--smoke-test",
        ],
        timeout=30,
        env=env,
    )


def run_exe_test() -> None:
    exe = DIST_DIR / "ポケヨヤ君.exe"

    if not exe.exists():
        raise SystemExit(
            f"EXEが見つかりません: {exe}"
        )

    env = build_environment()
    run_command(
        [
            str(exe),
            "--smoke-test",
        ],
        timeout=45,
        env=env,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe",
        action="store_true",
        help="ビルド済みEXEをテストします。",
    )
    args = parser.parse_args()

    if args.exe:
        run_exe_test()
        print("EXEスモークテスト: OK")
    else:
        run_source_test()
        print("ソース起動スモークテスト: OK")


if __name__ == "__main__":
    main()

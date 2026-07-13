import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PRESERVE_FOLDERS = {
    "config",
    "data",
    "logs",
    "backup",
    "temp",
}

PRESERVE_FILES = {
    "README.txt",
}


def wait_for_process(pid: int, timeout_seconds: int = 60) -> None:
    if pid <= 0:
        return

    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return

        time.sleep(0.5)

    raise RuntimeError(
        "ポケヨヤ君が終了しなかったため、更新を中止しました。"
    )


def copy_tree(source: Path, target: Path) -> None:
    for item in source.iterdir():
        if item.name in PRESERVE_FOLDERS:
            continue

        destination = target / item.name

        if item.is_dir():
            shutil.copytree(
                item,
                destination,
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(item, destination)


def create_program_backup(target: Path) -> Path:
    backup_root = target / "backup" / "program"
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = backup_root / timestamp
    destination.mkdir(parents=True, exist_ok=True)

    for item in target.iterdir():
        if item.name in PRESERVE_FOLDERS:
            continue

        if item.name in PRESERVE_FILES:
            continue

        backup_item = destination / item.name

        if item.is_dir():
            shutil.copytree(item, backup_item)
        else:
            shutil.copy2(item, backup_item)

    return destination


def restore_backup(backup: Path, target: Path) -> None:
    if not backup.exists():
        return

    for item in target.iterdir():
        if item.name in PRESERVE_FOLDERS:
            continue

        if item.name in PRESERVE_FILES:
            continue

        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)

    for item in backup.iterdir():
        destination = target / item.name

        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)


def launch(command: list[str], cwd: Path) -> None:
    if not command:
        return

    subprocess.Popen(
        command,
        cwd=str(cwd),
        close_fds=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--launch-json", default="[]")
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    status_file = Path(args.status_file).resolve()

    status_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        launch_command = json.loads(args.launch_json)
        if not isinstance(launch_command, list):
            launch_command = []
    except json.JSONDecodeError:
        launch_command = []

    result = {
        "success": False,
        "message": "",
        "backup_path": "",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    backup_path = None

    try:
        wait_for_process(args.pid)

        if not source.exists():
            raise FileNotFoundError(
                f"更新元フォルダーが見つかりません: {source}"
            )

        if not target.exists():
            raise FileNotFoundError(
                f"更新先フォルダーが見つかりません: {target}"
            )

        backup_path = create_program_backup(target)
        result["backup_path"] = str(backup_path)

        copy_tree(source, target)

        result["success"] = True
        result["message"] = "更新を適用しました。"

    except Exception as error:
        result["message"] = str(error)

        if backup_path is not None:
            try:
                restore_backup(backup_path, target)
                result["message"] += "\n旧バージョンへ復元しました。"
            except Exception as restore_error:
                result["message"] += (
                    "\n復元にも失敗しました: "
                    + str(restore_error)
                )

    status_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if result["success"]:
        launch(launch_command, target)

    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

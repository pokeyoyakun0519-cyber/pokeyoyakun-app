from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


EDITION_RULES = {
    "user": re.compile(
        r"^PokeyoyaKun_User_Setup_Ver\d+\.\d+\.\d+"
        r"(?:_RC\d+(?:\.\d+)?)?\.exe$"
    ),
    "owner": re.compile(
        r"^PokeyoyaKun_Owner_Setup_Ver\d+\.\d+\.\d+"
        r"(?:_RC\d+(?:\.\d+)?)?\.exe$"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_for_process(pid: int, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while pid > 0 and time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)
    if pid > 0:
        raise RuntimeError("アプリを終了できないため更新を中止しました。")


def run(expected_edition: str) -> int:
    if expected_edition not in EDITION_RULES:
        raise SystemExit("invalid updater edition")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--setup", required=True)
    parser.add_argument("--sha-file", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--launch-json", default="[]")
    parser.add_argument("--status-file", required=True)
    args = parser.parse_args()
    setup = Path(args.setup).resolve()
    sha_file = Path(args.sha_file).resolve()
    target = Path(args.target).resolve()
    status_file = Path(args.status_file).resolve()
    status_file.parent.mkdir(parents=True, exist_ok=True)
    result = {"success": False, "message": "", "updated_at": datetime.now().isoformat(timespec="seconds")}
    try:
        if not setup.is_file() or not EDITION_RULES[expected_edition].fullmatch(setup.name):
            raise RuntimeError("Editionに一致しないSetup.exeを拒否しました。")
        expected = sha_file.read_text(encoding="ascii").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(setup) != expected:
            raise RuntimeError("Setup.exeのSHA-256検証に失敗しました。")
        wait_for_process(args.pid)
        completed = subprocess.run([
            str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            f"/DIR={target}",
        ], timeout=300)
        if completed.returncode != 0:
            raise RuntimeError(f"インストーラーが失敗しました: {completed.returncode}")
        result.update(success=True, message="更新を適用しました。")
    except Exception as error:
        result["message"] = str(error)
    status_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result["success"]:
        try:
            command = json.loads(args.launch_json)
            if isinstance(command, list) and command:
                subprocess.Popen(command, cwd=str(target), close_fds=True)
        except Exception:
            pass
    return 0 if result["success"] else 1

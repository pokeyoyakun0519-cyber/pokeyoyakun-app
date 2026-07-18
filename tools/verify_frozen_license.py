from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXE_PATH = PROJECT_ROOT / "release" / "user_dist_rc4" / "ポケヨヤ君.exe"
EXPECTED_ENDPOINT = "https://api.pokeyoyakun.com"
ARCHIVE_ENDPOINT = "core/online_license_endpoint.json"


def bundled_endpoint(exe_path: Path) -> str:
    archive = CArchiveReader(str(exe_path))
    names = {name.replace("\\", "/"): name for name in archive.toc}
    archive_name = names.get(ARCHIVE_ENDPOINT)
    if archive_name is None:
        raise SystemExit(
            "PyInstaller内部にonline_license_endpoint.jsonがありません。"
        )
    try:
        payload = json.loads(archive.extract(archive_name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("同梱ライセンス接続先を解析できません。") from error
    return str(payload.get("public_url", "")).strip().rstrip("/")


def run_frozen_health_test(exe_path: Path) -> None:
    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="pokeyoya_license_self_test_") as directory:
        environment["LOCALAPPDATA"] = directory
        environment["POKEYOYA_DATA_ROOT"] = str(Path(directory) / "PokeyoyaKun")
        completed = subprocess.run(
            [str(exe_path), "--license-api-self-test"],
            cwd=exe_path.parent,
            env=environment,
            timeout=45,
        )
    if completed.returncode != 0:
        raise SystemExit(
            "frozen User Editionから本番ライセンスAPIへ接続できませんでした。"
        )


def main() -> None:
    if not EXE_PATH.is_file():
        raise SystemExit(f"RC4 EXEが見つかりません: {EXE_PATH}")
    endpoint = bundled_endpoint(EXE_PATH)
    if endpoint != EXPECTED_ENDPOINT:
        raise SystemExit(f"frozen EXEの接続先が不正です: {endpoint}")
    print(f"FROZEN_LICENSE_ENDPOINT_OK: {endpoint}")
    run_frozen_health_test(EXE_PATH)
    print("FROZEN_LICENSE_HEALTH_OK")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXE_PATH = PROJECT_ROOT / "release" / "user_dist_rc4" / "ポケヨヤ君.exe"


def archive_has_certifi_ca(exe_path: Path) -> bool:
    archive = CArchiveReader(str(exe_path))
    names = {name.replace("\\", "/").lower() for name in archive.toc}
    return "certifi/cacert.pem" in names


def run_frozen_ca_self_test(exe_path: Path) -> None:
    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="pokeyoya_tls_self_test_") as directory:
        environment["LOCALAPPDATA"] = directory
        completed = subprocess.run(
            [str(exe_path), "--tls-ca-self-test"],
            cwd=exe_path.parent,
            env=environment,
            timeout=45,
        )
    if completed.returncode != 0:
        raise SystemExit(
            "frozen EXEがcertifi CAバンドルを読み込めませんでした。"
        )


def main() -> None:
    if not EXE_PATH.is_file():
        raise SystemExit(f"RC4 EXEが見つかりません: {EXE_PATH}")
    if not archive_has_certifi_ca(EXE_PATH):
        raise SystemExit("PyInstaller内部にcertifi/cacert.pemがありません。")
    print("PYINSTALLER_CERTIFI_CA_OK")
    run_frozen_ca_self_test(EXE_PATH)
    print("FROZEN_CERTIFI_CA_LOAD_OK")


if __name__ == "__main__":
    main()

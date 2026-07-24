from __future__ import annotations

import json
import getpass
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXE_PATH = PROJECT_ROOT / "release" / "user_dist_rc4" / "ポケヨヤ君.exe"
EXPECTED_ENDPOINT = "https://api.pokeyoyakun.com"
ARCHIVE_ENDPOINT = "core/online_license_endpoint.json"
ARCHIVE_KEYRING = "core/online_license_public_keys.json"
EXPECTED_KEY_ID = "online-2026-07-vps"
EXPECTED_FINGERPRINT = (
    "5ab3726be8f068ab8305079b04916dd40fa1e259916a4d10b8ea2379e5fe47c7"
)


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


def bundled_key_fingerprint(exe_path: Path) -> str:
    archive = CArchiveReader(str(exe_path))
    names = {name.replace("\\", "/"): name for name in archive.toc}
    archive_name = names.get(ARCHIVE_KEYRING)
    if archive_name is None:
        raise SystemExit("PyInstaller内部にオンライン公開鍵一覧がありません。")
    try:
        payload = json.loads(archive.extract(archive_name).decode("utf-8"))
        records = {
            str(record["key_id"]): record
            for record in payload["keys"]
            if isinstance(record, dict)
        }
        record = records[EXPECTED_KEY_ID]
        public_key = rsa.RSAPublicNumbers(
            int(record["e"]),
            int(str(record["n"]), 16),
        ).public_key()
        der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit("同梱オンライン公開鍵を解析できません。") from error
    if "online-2026-07-prod" not in records:
        raise SystemExit("既存オンライン公開鍵が同梱一覧から失われています。")
    return hashlib.sha256(der).hexdigest()


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


def run_frozen_lifecycle_test(exe_path: Path) -> None:
    license_key = getpass.getpass(
        "実ライセンスキー（画面・ログへ表示しません）: "
    ).strip().upper()
    if not license_key:
        raise SystemExit("実ライセンスキーが入力されていません。")
    license_key_hash = hashlib.sha256(license_key.encode("utf-8")).hexdigest()[:16]
    print("FROZEN_LICENSE_KEY_HASH:", license_key_hash)
    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="pokeyoya_license_lifecycle_") as directory:
        result_path = Path(directory) / "result.json"
        environment["LOCALAPPDATA"] = directory
        environment["POKEYOYA_DATA_ROOT"] = str(Path(directory) / "PokeyoyaKun")
        environment["POKEYOYA_TEST_LICENSE_KEY"] = license_key
        environment["POKEYOYA_TEST_RESULT_PATH"] = str(result_path)
        completed = subprocess.run(
            [str(exe_path), "--license-api-lifecycle-self-test"],
            cwd=exe_path.parent,
            env=environment,
            timeout=90,
        )
        environment.pop("POKEYOYA_TEST_LICENSE_KEY", None)
        license_key = ""
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit("frozenライセンス試験結果を読み取れません。") from error
    print("FROZEN_ACTIVATE_OK:", bool(result.get("activate")))
    print("FROZEN_VERIFY_OK:", bool(result.get("verify")))
    print("FROZEN_DEACTIVATE_OK:", bool(result.get("deactivate")))
    print("FROZEN_TOKEN_KEY_ID:", str(result.get("key_id", "")))
    print("FROZEN_FAILED_STAGE:", str(result.get("failed_stage", "")))
    print("FROZEN_EXCEPTION_TYPE:", str(result.get("exception_type", "")))
    print("FROZEN_FAILURE_MESSAGE:", str(result.get("message", "")))
    diagnostics = result.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    for stage in ("activate", "verify", "deactivate"):
        diagnostic = diagnostics.get(stage, {})
        if not isinstance(diagnostic, dict):
            continue
        label = stage.upper()
        print(
            f"FROZEN_{label}_HTTP_STATUS:",
            diagnostic.get("http_status", ""),
        )
        print(
            f"FROZEN_{label}_CATEGORY:",
            str(diagnostic.get("category", "")),
        )
        print(
            f"FROZEN_{label}_TOKEN_PRESENT:",
            bool(diagnostic.get("token_present", False)),
        )
        print(
            f"FROZEN_{label}_TOKEN_KEY_ID:",
            str(diagnostic.get("token_key_id", "")),
        )
        print(
            f"FROZEN_{label}_JSON:",
            json.dumps(
                diagnostic.get("response_json"),
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    report_path_value = os.environ.get("POKEYOYA_LIFECYCLE_REPORT_PATH", "").strip()
    if report_path_value:
        Path(report_path_value).write_text(
            json.dumps(
                {
                    "license_key_hash": license_key_hash,
                    "activate": bool(result.get("activate")),
                    "verify": bool(result.get("verify")),
                    "deactivate": bool(result.get("deactivate")),
                    "key_id": str(result.get("key_id", "")),
                    "returncode": completed.returncode,
                    "failed_stage": str(result.get("failed_stage", "")),
                    "exception_type": str(result.get("exception_type", "")),
                    "message": str(result.get("message", "")),
                    "diagnostics": diagnostics,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if completed.returncode != 0 or not all(
        bool(result.get(name)) for name in ("activate", "verify", "deactivate")
    ):
        raise SystemExit("frozen実ライセンス試験に失敗しました。")
    if str(result.get("key_id", "")) != EXPECTED_KEY_ID:
        raise SystemExit("frozen応答のkey_idが新しいVPS公開鍵と一致しません。")


def main() -> None:
    if not EXE_PATH.is_file():
        raise SystemExit(f"RC4 EXEが見つかりません: {EXE_PATH}")
    endpoint = bundled_endpoint(EXE_PATH)
    if endpoint != EXPECTED_ENDPOINT:
        raise SystemExit(f"frozen EXEの接続先が不正です: {endpoint}")
    print(f"FROZEN_LICENSE_ENDPOINT_OK: {endpoint}")
    fingerprint = bundled_key_fingerprint(EXE_PATH)
    if fingerprint != EXPECTED_FINGERPRINT:
        raise SystemExit(f"frozen EXEの公開鍵指紋が不正です: {fingerprint}")
    print(f"FROZEN_LICENSE_KEY_OK: {EXPECTED_KEY_ID} {fingerprint}")
    run_frozen_health_test(EXE_PATH)
    print("FROZEN_LICENSE_HEALTH_OK")
    if "--lifecycle" in sys.argv:
        run_frozen_lifecycle_test(EXE_PATH)


if __name__ == "__main__":
    main()

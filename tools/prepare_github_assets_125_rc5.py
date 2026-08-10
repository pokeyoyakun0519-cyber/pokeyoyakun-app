from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = (
    PROJECT_ROOT / "release" / "github_assets" / "ver1.25.0-rc5"
)
FROZEN_EXE = PROJECT_ROOT / "release" / "user_dist_rc5" / "ポケヨヤ君.exe"
INTEGRITY_MANIFEST = PROJECT_ROOT / "release" / "user_dist_rc5" / "release-integrity.json"
VERSION_INFO = PROJECT_ROOT / "installer" / "version_info.txt"
PROVENANCE_NAME = "RC5_RELEASE_PROVENANCE.txt"
SOURCES = (
    (
        PROJECT_ROOT
        / "release"
        / "user_installer_rc5"
        / "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.exe",
        "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.exe",
    ),
    (
        PROJECT_ROOT / "RELEASE_NOTES_Ver1.25.0_RC5.txt",
        "RELEASE_NOTES_Ver1.25.0_RC5.txt",
    ),
    (
        PROJECT_ROOT / "TESTER_README_Ver1.25.0_RC5.txt",
        "TESTER_README_Ver1.25.0_RC5.txt",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_value(source: str, name: str) -> str:
    match = re.search(
        rf"StringStruct\('{re.escape(name)}',\s*'([^']+)'\)",
        source,
    )
    if match is None:
        raise SystemExit(f"version_info.txtに{name}がありません。")
    return match.group(1)


def _write_provenance(installer: Path) -> Path:
    if not FROZEN_EXE.is_file() or not INTEGRITY_MANIFEST.is_file():
        raise SystemExit("Frozen EXEまたはrelease-integrity.jsonがありません。")
    manifest = json.loads(INTEGRITY_MANIFEST.read_text(encoding="utf-8"))
    build_commit = str(manifest.get("build_commit", "")).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", build_commit) is None:
        raise SystemExit("release-integrity.jsonに有効なbuild_commitがありません。")
    version_source = VERSION_INFO.read_text(encoding="utf-8")
    inno_version = os.environ.get("POKEYOYA_INNO_SETUP_VERSION", "").strip()
    if not inno_version:
        raise SystemExit("POKEYOYA_INNO_SETUP_VERSIONを指定してください。")
    build_time = datetime.fromtimestamp(FROZEN_EXE.stat().st_mtime).astimezone()
    destination = ASSET_DIR / PROVENANCE_NAME
    destination.write_text(
        "\n".join(
            (
                "PokeyoyaKun User Edition Release Provenance",
                "Version: 1.25.0 RC5",
                f"Build commit SHA: {build_commit}",
                f"Installer SHA-256: {sha256(installer)}",
                f"Frozen EXE SHA-256: {sha256(FROZEN_EXE)}",
                f"FileVersion: {_version_value(version_source, 'FileVersion')}",
                f"ProductVersion: {_version_value(version_source, 'ProductVersion')}",
                f"Build datetime: {build_time.isoformat()}",
                f"PyInstaller version: {importlib.metadata.version('pyinstaller')}",
                f"Inno Setup version: {inno_version}",
                "Authenticode: unsigned RC5 tester candidate",
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def main() -> None:
    missing = [str(source) for source, _ in SOURCES if not source.is_file()]
    if missing:
        raise SystemExit("GitHub Assets元ファイルがありません:\n- " + "\n- ".join(missing))

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    expected = {destination for _, destination in SOURCES} | {
        PROVENANCE_NAME,
        "SHA256SUMS.txt",
    }
    for path in ASSET_DIR.iterdir():
        if path.is_dir():
            raise SystemExit(f"GitHub Assets内に想定外のディレクトリがあります: {path}")
        if path.name not in expected:
            path.unlink()

    destinations: list[Path] = []
    for source, destination_name in SOURCES:
        destination = ASSET_DIR / destination_name
        shutil.copy2(source, destination)
        destinations.append(destination)

    destinations.append(_write_provenance(destinations[0]))

    checksum_file = ASSET_DIR / "SHA256SUMS.txt"
    checksum_file.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in destinations),
        encoding="utf-8",
        newline="\n",
    )
    print(f"GitHub Releases添付用ファイルを準備しました: {ASSET_DIR}")
    for path in (*destinations, checksum_file):
        print(f"- {path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()

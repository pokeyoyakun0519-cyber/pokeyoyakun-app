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
ASSET_DIR = PROJECT_ROOT / "release" / "github_assets" / "ver1.25.0"
DIST_DIR = PROJECT_ROOT / "release" / "user_dist_rc5"
FROZEN_EXE = DIST_DIR / "ポケヨヤ君.exe"
UPDATER_EXE = DIST_DIR / "PokeyoyaKunUpdaterV2.exe"
MANIFEST = DIST_DIR / "release-integrity.json"
VERSION_INFO = PROJECT_ROOT / "installer" / "version_info.txt"
INSTALLER = (
    PROJECT_ROOT / "release" / "user_installer_rc5"
    / "PokeyoyaKun_User_Setup_Ver1.25.0.exe"
)
SOURCES = (
    (INSTALLER, INSTALLER.name),
    (
        PROJECT_ROOT / "RELEASE_NOTES_Ver1.25.0.txt",
        "RELEASE_NOTES_Ver1.25.0.txt",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_value(name: str) -> str:
    source = VERSION_INFO.read_text(encoding="utf-8")
    match = re.search(rf"StringStruct\('{name}',\s*'([^']+)'\)", source)
    if match is None:
        raise SystemExit(f"version_info.txtに{name}がありません。")
    return match.group(1)


def write_provenance(installer: Path) -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    build_commit = str(manifest.get("build_commit", "")).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", build_commit) is None:
        raise SystemExit("release-integrity.jsonのbuild_commitが不正です。")
    inno_version = os.environ.get("POKEYOYA_INNO_SETUP_VERSION", "").strip()
    if not inno_version:
        raise SystemExit("POKEYOYA_INNO_SETUP_VERSIONを指定してください。")
    destination = ASSET_DIR / "STABLE_RELEASE_PROVENANCE.txt"
    destination.write_text(
        "\n".join((
            "PokeyoyaKun User Edition Stable Release Provenance",
            "Version: 1.25.0",
            "Channel: stable",
            f"Build Commit: {build_commit}",
            f"Build datetime: {datetime.fromtimestamp(FROZEN_EXE.stat().st_mtime).astimezone().isoformat()}",
            f"FileVersion: {version_value('FileVersion')}",
            f"ProductVersion: {version_value('ProductVersion')}",
            f"Frozen EXE SHA-256: {sha256(FROZEN_EXE)}",
            f"Updater V2 SHA-256: {sha256(UPDATER_EXE)}",
            f"Installer SHA-256: {sha256(installer)}",
            f"PyInstaller version: {importlib.metadata.version('pyinstaller')}",
            f"Inno Setup version: {inno_version}",
            "License endpoint: https://api.pokeyoyakun.com",
            "Public key ID: online-2026-07-vps",
            "Public key fingerprint: 5ab3726be8f068ab8305079b04916dd40fa1e259916a4d10b8ea2379e5fe47c7",
            "Authenticode: unsigned",
            "",
        )),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def main() -> None:
    required = [source for source, _ in SOURCES] + [FROZEN_EXE, UPDATER_EXE, MANIFEST]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Stable assets元ファイルがありません:\n- " + "\n- ".join(missing))
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for path in ASSET_DIR.iterdir():
        if path.is_dir():
            raise SystemExit(f"想定外のディレクトリがあります: {path}")
        path.unlink()
    destinations = []
    for source, name in SOURCES:
        destination = ASSET_DIR / name
        shutil.copy2(source, destination)
        destinations.append(destination)
    destinations.append(write_provenance(destinations[0]))
    sums = ASSET_DIR / "SHA256SUMS.txt"
    sums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in destinations),
        encoding="utf-8",
        newline="\n",
    )
    for path in (*destinations, sums):
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()

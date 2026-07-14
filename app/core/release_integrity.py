from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.runtime_paths import install_root, is_frozen


MANIFEST_NAME = "release-integrity.json"
FORBIDDEN_SUFFIXES = {".py", ".pyc", ".pdb", ".spec"}
FORBIDDEN_DIRECTORIES = {"tests", "test", "__pycache__"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_runtime_integrity() -> tuple[bool, str]:
    """配布物の破損や単純な差し替えを起動時に検出する。"""
    if not is_frozen():
        return True, "ソース実行のため配布物検査を省略しました。"

    root = install_root()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return False, "配布物の整合性マニフェストがありません。"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if manifest.get("algorithm") != "sha256" or not isinstance(files, dict):
            raise ValueError("unsupported manifest")
    except (OSError, ValueError, KeyError, TypeError):
        return False, "配布物の整合性マニフェストが壊れています。"

    for name, digest in files.items():
        if not isinstance(name, str) or Path(name).name != name:
            return False, "配布物の整合性マニフェストに不正なパスがあります。"
        expected = str(digest).lower()
        if len(expected) != 64 or any(
            char not in "0123456789abcdef" for char in expected
        ):
            return False, "配布物の整合性ハッシュ形式が不正です。"
        target = root / name
        if not target.is_file() or _sha256(target) != expected:
            return False, f"実行ファイルの改ざんまたは破損を検出しました: {name}"

    for path in root.iterdir():
        if path.is_dir() and path.name.lower() in FORBIDDEN_DIRECTORIES:
            return False, f"配布先に不要な開発用フォルダーがあります: {path.name}"
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            return False, f"配布先に不要な開発用ファイルがあります: {path.name}"

    return True, "配布物の整合性を確認しました。"

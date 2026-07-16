from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = (
    PROJECT_ROOT / "release" / "github_assets" / "ver1.25.0-rc2"
)
SOURCES = (
    (
        PROJECT_ROOT
        / "release"
        / "user_installer"
        / "PokeyoyaKun_User_Setup_Ver1.25.0_RC2.exe",
        "PokeyoyaKun_User_Setup_Ver1.25.0_RC2.exe",
    ),
    (
        PROJECT_ROOT / "RELEASE_NOTES_Ver1.25.0_RC2.txt",
        "RELEASE_NOTES_Ver1.25.0_RC2.txt",
    ),
    (
        PROJECT_ROOT / "TESTER_README_Ver1.25.0_RC2.txt",
        "TESTER_README_Ver1.25.0_RC2.txt",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    missing = [str(source) for source, _ in SOURCES if not source.is_file()]
    if missing:
        raise SystemExit("GitHub Assets元ファイルがありません:\n- " + "\n- ".join(missing))

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    expected = {destination for _, destination in SOURCES} | {"SHA256SUMS.txt"}
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

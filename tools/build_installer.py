import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ISS_FILE = PROJECT_ROOT / "installer" / "PokeyoyaKun_Setup.iss"

POSSIBLE_COMPILERS = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def find_iscc() -> Path | None:
    for path in POSSIBLE_COMPILERS:
        if path.exists():
            return path

    command = shutil.which("ISCC.exe")
    return Path(command) if command else None


def main() -> None:
    compiler = find_iscc()

    if compiler is None:
        raise SystemExit(
            "Inno Setup 6が見つかりません。\n"
            "公式サイトからInno Setup 6をインストール後、"
            "もう一度BUILD_INSTALLER.batを実行してください。"
        )

    dist_dir = PROJECT_ROOT / "release" / "dist"
    required = [
        dist_dir / "ポケヨヤ君.exe",
        dist_dir / "ポケヨヤ君_設定.exe",
    ]

    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "先にBUILD_EXE.batを実行してください。\n"
            "不足: " + ", ".join(missing)
        )

    result = subprocess.run([str(compiler), str(ISS_FILE)])

    if result.returncode != 0:
        raise SystemExit(
            f"インストーラー作成に失敗しました。終了コード: {result.returncode}"
        )

    print("インストーラーを作成しました。")
    print(PROJECT_ROOT / "release" / "installer")


if __name__ == "__main__":
    main()

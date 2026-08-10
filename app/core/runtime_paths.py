import os
import sys
from pathlib import Path


APP_FOLDER_NAME = "PokeyoyaKun"


def is_frozen() -> bool:
    """PyInstallerまたはNuitkaでEXE化されているか判定する。"""
    return bool(
        getattr(sys, "frozen", False)
        or "__compiled__" in globals()
    )


def install_root() -> Path:
    """
    EXE版ではEXEの配置フォルダー、
    ソース版ではプロジェクト直下を返す。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[2]


def app_root() -> Path:
    """
    書き込み可能なユーザーデータ保存先。

    ソース版:
        プロジェクト直下

    EXE版:
        %LOCALAPPDATA%\\PokeyoyaKun

    Program Filesへ直接設定を書こうとして権限エラーになる問題を避ける。
    """
    explicit_root = os.environ.get("POKEYOYA_DATA_ROOT", "").strip()
    if explicit_root:
        root = Path(explicit_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    if not is_frozen():
        return install_root()

    local_app_data = os.environ.get("LOCALAPPDATA")

    if local_app_data:
        root = Path(local_app_data) / APP_FOLDER_NAME
    else:
        root = Path.home() / "AppData" / "Local" / APP_FOLDER_NAME

    root.mkdir(parents=True, exist_ok=True)
    return root


def bundled_root() -> Path:
    """
    PyInstallerの一時展開先、またはソースのプロジェクト直下。
    アイコンなど読み取り専用の同梱データ参照に使う。
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    if "__compiled__" in globals():
        # Nuitkaは同梱データ参照用の__file__を維持する。
        return Path(__file__).resolve().parents[2]

    return install_root()

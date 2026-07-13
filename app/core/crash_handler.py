import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from core.runtime_paths import app_root


def install_crash_handler() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(
                exc_type,
                exc_value,
                exc_traceback,
            )
            return

        logs_dir = app_root() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / f"crash_{timestamp}.log"

        text = "".join(
            traceback.format_exception(
                exc_type,
                exc_value,
                exc_traceback,
            )
        )
        log_path.write_text(text, encoding="utf-8")

        try:
            QMessageBox.critical(
                None,
                "予期しないエラー",
                "アプリで予期しないエラーが発生しました。\n\n"
                f"ログ保存先:\n{log_path}",
            )
        finally:
            sys.__excepthook__(
                exc_type,
                exc_value,
                exc_traceback,
            )

    sys.excepthook = handle_exception

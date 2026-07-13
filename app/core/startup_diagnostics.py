import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root


class StartupDiagnostics:
    def __init__(self):
        self.logs_dir = app_root() / "logs"
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.logs_dir = Path(tempfile.gettempdir()) / "PokeyoyaKun_logs"
            self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.path = self.logs_dir / "startup.log"

    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(f"[{timestamp}] {message}\n")
        except OSError:
            pass

    def write_exception(self, title: str, error: BaseException) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_path = self.logs_dir / f"startup_error_{timestamp}.log"

        details = "".join(
            traceback.format_exception(
                type(error),
                error,
                error.__traceback__,
            )
        )

        try:
            error_path.write_text(
                f"{title}\n\n{details}",
                encoding="utf-8",
            )
        except OSError:
            error_path = Path(tempfile.gettempdir()) / (
                f"PokeyoyaKun_startup_error_{timestamp}.log"
            )
            error_path.write_text(
                f"{title}\n\n{details}",
                encoding="utf-8",
            )

        self.write(f"{title}: {error}")
        return error_path

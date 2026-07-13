from datetime import datetime
from pathlib import Path


class LogManager:
    """ポケヨヤ君の動作履歴をlogs/app.logへ保存する。"""

    def __init__(self):
        project_root = Path(__file__).resolve().parents[2]
        self.log_path = project_root / "logs" / "app.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"

        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(line)

    def read_recent(self, max_lines: int = 200) -> str:
        if not self.log_path.exists():
            return "ログはまだありません。"

        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return "ログを読み込めませんでした。"

        if not lines:
            return "ログはまだありません。"

        return "\n".join(lines[-max_lines:])

    def clear(self) -> None:
        if self.log_path.exists():
            self.log_path.write_text("", encoding="utf-8")

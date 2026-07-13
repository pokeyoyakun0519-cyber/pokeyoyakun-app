from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config_manager import ConfigManager
from core.log_manager import LogManager
from core.notification_store import NotificationStore


class NotificationManager:
    """
    ポップアップと通知音をまとめて扱う。
    現時点の音声再生はWindowsのWAVファイルに対応。
    """

    def __init__(self):
        self.config_manager = ConfigManager()
        self.log_manager = LogManager()
        self.notification_store = NotificationStore()

    def notify(self, parent, title: str, message: str) -> None:
        config = self.config_manager.load()
        general = config["general"]
        sound_file = config["notification"].get("sound_file", "")

        if general.get("play_notification_sound", True):
            self._play_sound(sound_file)

        if general.get("show_popup", True):
            QMessageBox.information(parent, title, message)

        self.log_manager.write(f"{title}: {message}")
        self.notification_store.add(title, message)

    def _play_sound(self, sound_file: str) -> None:
        path = Path(sound_file) if sound_file else None

        if path and path.exists() and path.suffix.lower() == ".wav":
            try:
                import winsound
                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
                return
            except Exception:
                pass

        QApplication.beep()

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

    def __init__(self, config_manager=None, notification_store=None):
        self.config_manager = config_manager or ConfigManager()
        self.log_manager = LogManager()
        self.notification_store = notification_store or NotificationStore()

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

    def notify_application_deadline(self, reminder: dict, *, parent=None, tray_controller=None) -> bool:
        title = "応募締切リマインダー"
        message = (
            f'{reminder.get("tcg", "その他")} / {reminder.get("product_name", "商品名未設定")}\n'
            f'{reminder.get("site_name", "店舗名未設定")}\n'
            f'締切: {reminder.get("application_end_at", "未取得")} '
            f'（残り{reminder.get("remaining_text", "不明")}）'
        )
        config = self.config_manager.load()
        general = config.get("general", {})
        if general.get("play_notification_sound", True):
            self._play_sound(config.get("notification", {}).get("sound_file", ""))
        if general.get("show_popup", True):
            if tray_controller is not None and hasattr(tray_controller, "show_application_reminder"):
                tray_controller.show_application_reminder(
                    title, message, str(reminder.get("application_url", ""))
                )
            elif parent is not None:
                QMessageBox.information(parent, title, message)
        self.log_manager.write(f"{title}: {message}")
        self.notification_store.add(
            title,
            message,
            "応募締切",
            action_url=str(reminder.get("application_url", "")),
            action_label="応募ページを開く",
            metadata={
                "history_key": reminder.get("history_key", ""),
                "offset_minutes": reminder.get("offset_minutes", 0),
            },
        )
        return True

    def notify_application_change(self, event: dict, *, parent=None, tray_controller=None) -> bool:
        title = "応募情報が変更されました"
        lines = [
            f'{item.get("label", "変更")}: {item.get("before") or "未取得"} → {item.get("after") or "未取得"}'
            for item in event.get("changes", {}).values()
        ]
        message = (
            f'{event.get("product_name", "商品名未設定")} / '
            f'{event.get("site_name", "店舗名未設定")}\n'
            + "\n".join(lines[:6])
        )
        config = self.config_manager.load()
        if config.get("general", {}).get("show_popup", True):
            if tray_controller is not None and hasattr(tray_controller, "show_application_reminder"):
                tray_controller.show_application_reminder(
                    title, message, str(event.get("application_url", ""))
                )
            elif parent is not None:
                QMessageBox.information(parent, title, message)
        self.log_manager.write(f"{title}: {message}")
        self.notification_store.add(
            title,
            message,
            "応募情報変更",
            action_url=str(event.get("application_url", "")),
            action_label="応募ページを開く",
            metadata={"event_id": event.get("id", "")},
        )
        return True

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

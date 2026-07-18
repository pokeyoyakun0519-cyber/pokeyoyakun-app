from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from core.behavior_config import BehaviorConfig
from core.runtime_paths import bundled_root
from core.safe_product_url import can_open_product_url, open_product_url

class TrayController(QObject):
    def __init__(self, window, scheduler, parent=None):
        super().__init__(parent)
        self.window = window
        self.scheduler = scheduler
        self.config = BehaviorConfig()

        icon_path = bundled_root() / "assets" / "pokeyoya_icon.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else window.windowIcon()

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("ポケヨヤ君")

        menu = QMenu()
        show_action = QAction("ポケヨヤ君を表示", self)
        run_action = QAction("今すぐ監視", self)
        quit_action = QAction("完全に終了", self)

        show_action.triggered.connect(self.show_window)
        run_action.triggered.connect(self.scheduler.run_now)
        quit_action.triggered.connect(self.quit_application)

        menu.addAction(show_action)
        menu.addAction(run_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._activated)
        self.tray.messageClicked.connect(self._open_last_notification_action)
        self.last_notification_action_url = ""
        self.tray.show()

        self.scheduler.run_completed.connect(self._monitor_completed)
        self.scheduler.status_changed.connect(self.tray.setToolTip)

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def hide_window(self):
        self.window.hide()
        if self.config.load().get("show_tray_notifications", True):
            self.tray.showMessage(
                "ポケヨヤ君",
                "タスクトレイで監視を続けています。",
                QSystemTrayIcon.Information,
                2500,
            )

    def quit_application(self):
        self.window.allow_close = True
        self.tray.hide()
        QApplication.quit()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window() if not self.window.isVisible() else self.window.hide()

    def _monitor_completed(self, result):
        if not self.config.load().get("show_tray_notifications", True):
            return
        changes = len(result.get("changed_sources", []))
        wins = len(result.get("newly_won", []))
        if changes or wins:
            self.tray.showMessage(
                "自動監視が完了しました",
                f"変更候補：{changes}件 / 当選候補：{wins}件",
                QSystemTrayIcon.Information,
                5000,
            )

    def show_application_reminder(self, title: str, message: str, action_url: str) -> None:
        self.last_notification_action_url = action_url if can_open_product_url(action_url) else ""
        suffix = "\n通知をクリックして応募ページを開く" if self.last_notification_action_url else ""
        self.tray.showMessage(
            title,
            message + suffix,
            QSystemTrayIcon.Warning,
            10_000,
        )

    def _open_last_notification_action(self):
        if self.last_notification_action_url:
            open_product_url(self.last_notification_action_url)

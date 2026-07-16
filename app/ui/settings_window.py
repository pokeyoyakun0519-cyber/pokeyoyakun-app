from PySide6.QtWidgets import QMainWindow

from core.version import APP_CHANNEL, APP_VERSION
from ui.settings_page import SettingsPage


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            f"ポケヨヤ君設定 Ver.{APP_VERSION} {APP_CHANNEL.upper()}"
        )
        self.resize(900, 760)
        self.setMinimumSize(760, 620)

        self.setCentralWidget(SettingsPage())

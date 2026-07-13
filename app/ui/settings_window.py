from PySide6.QtWidgets import QMainWindow

from ui.settings_page import SettingsPage


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ポケヨヤ君設定 Ver.1.22.0 RC")
        self.resize(900, 760)
        self.setMinimumSize(760, 620)

        self.setCentralWidget(SettingsPage())

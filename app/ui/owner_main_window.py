from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from core.version import APP_CHANNEL, APP_VERSION
from ui.main_window import MainWindow


class OwnerMainWindow(MainWindow):
    """Owner専用ビルドからだけ読み込まれるメイン画面。"""

    SETTINGS_EXECUTABLE = "PokeyoyaKun_Owner_Settings.exe"

    def _window_title(self):
        return (
            f"ポケヨヤ君 Owner Edition Ver.{APP_VERSION} "
            f"{APP_CHANNEL.upper()} - 開発者専用・配布禁止"
        )

    def _edition_banner(self):
        banner = QFrame()
        banner.setObjectName("OwnerEditionBanner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(20, 8, 20, 8)
        edition = QLabel("Owner Edition")
        notice = QLabel("開発者専用・配布禁止")
        notice.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(edition)
        layout.addStretch()
        layout.addWidget(notice)
        return banner

    def _is_owner_edition(self):
        return True

    def _navigation_labels(self):
        return [
            item
            for item in super()._navigation_labels()
            if item[0] != "online_license_button"
        ]

    def _system_navigation_buttons(self):
        return [
            self.resident_button, self.update_button,
            self.history_button, self.self_test_button,
            self.regression_button, self.release_readiness_button,
            self.support_button, self.feedback_button,
            self.public_roadmap_button, self.about_button,
            self.open_settings_button,
        ]

    def _version_text(self):
        return (
            f"Version {APP_VERSION} {APP_CHANNEL.upper()} OWNER\n"
            "開発者専用・配布禁止"
        )

    def _developer_menu_expanded(self):
        return self.ui_mode == "detailed"

    def _developer_menu_title(self):
        return "Owner開発者メニュー"

    def _add_license_page(self, page_map):
        # Owner用バイナリには認証画面・認証ページを生成しない。
        return None

    def _create_update_page(self):
        from core.owner_update_manager import OwnerUpdateManager
        from ui.update_page import UpdatePage

        return UpdatePage(OwnerUpdateManager())

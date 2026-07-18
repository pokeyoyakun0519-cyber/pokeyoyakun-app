import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QToolButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.behavior_config import BehaviorConfig
from core.application_change_tracker import ApplicationChangeTracker
from core.application_reminder import ApplicationDeadlineReminder
from core.config_manager import ConfigManager
from core.notification_manager import NotificationManager
from core.product_store import ProductStore
from core.monitor_scheduler import MonitorScheduler
from core.p2_startup import P2StartupCoordinator
from core.runtime_paths import is_frozen
from core.version import APP_CHANNEL, APP_VERSION
from ui.about_page import AboutPage
from ui.application_dashboard_page import ApplicationDashboardPage
from ui.backup_page import BackupPage
from ui.calendar_page import CalendarPage
from ui.candidates_page import CandidatesPage
from ui.external_notification_page import ExternalNotificationPage
from ui.feedback_page import FeedbackPage
from ui.email_accounts_page import EmailAccountsPage
from ui.history_page import HistoryPage
from ui.home_page import HomePage
from ui.log_viewer_page import LogViewerPage
from ui.lottery_page import LotteryPage
from ui.migration_page import MigrationPage
from ui.notification_center_page import NotificationCenterPage
from ui.notification_page import NotificationPage
from ui.plugin_page import PluginPage
from ui.plugin_distribution_page import PluginDistributionPage
from ui.product_page import ProductPage
from ui.public_roadmap_page import PublicRoadmapPage
from ui.resident_page import ResidentPage
from ui.regression_page import RegressionPage
from ui.release_readiness_page import ReleaseReadinessPage
from ui.scheduler_page import SchedulerPage
from ui.self_test_page import SelfTestPage
from ui.site_master_page import SiteMasterPage
from ui.sources_page import SourcesPage
from ui.storage_page import StoragePage
from ui.statistics_page import StatisticsPage
from ui.support_page import SupportPage
from ui.update_page import UpdatePage

class MainWindow(QMainWindow):
    SETTINGS_EXECUTABLE = "ポケヨヤ君_設定.exe"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self._window_title())
        self.resize(1280, 780)
        self.setMinimumSize(980, 620)

        self.behavior_config = BehaviorConfig()
        self.monitor_scheduler = MonitorScheduler(self)
        self.tray_controller = None
        self.allow_close = False
        self.p2_startup_result = P2StartupCoordinator().run()
        self._build_ui()
        self._setup_application_assistant()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        edition_banner = self._edition_banner()
        if edition_banner is not None:
            root.addWidget(edition_banner)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        self.pages = self._build_pages()
        self._connect_navigation()

        content_layout.addWidget(sidebar)
        content_layout.addWidget(self.pages, 1)
        root.addWidget(content, 1)

    def _window_title(self):
        return f"ポケヨヤ君 Ver.{APP_VERSION} {APP_CHANNEL.upper()}"

    def _edition_banner(self):
        return None

    def _navigation_labels(self):
        return [
            ("home_button", "ホーム"),
            ("product_button", "商品一覧"),
            ("application_dashboard_button", "応募ダッシュボード"),
            ("calendar_button", "カレンダー"),
            ("statistics_button", "応募統計"),
            ("candidates_button", "新弾候補"),
            ("lottery_button", "抽選結果確認"),
            ("email_accounts_button", "メールアカウント"),
            ("sources_button", "公式情報ソース"),
            ("site_master_button", "サイトマスター"),
            ("plugin_button", "プラグイン管理"),
            ("plugin_distribution_button", "プラグイン配信"),
            ("scheduler_button", "自動監視"),
            ("notification_center_button", "通知センター"),
            ("notification_button", "通知・ログ"),
            ("external_notification_button", "外部通知"),
            ("log_viewer_button", "ログビューア"),
            ("storage_button", "データ保存場所"),
            ("migration_button", "データ移行"),
            ("backup_button", "バックアップ"),
            ("resident_button", "常駐・自動起動"),
            ("update_button", "アップデート"),
            ("online_license_button", "オンラインライセンス"),
            ("history_button", "更新履歴"),
            ("self_test_button", "セルフテスト"),
            ("regression_button", "回帰テスト"),
            ("release_readiness_button", "リリース準備状況"),
            ("support_button", "サポート"),
            ("feedback_button", "ご意見・ご要望"),
            ("public_roadmap_button", "人気要望・開発状況"),
            ("about_button", "アプリ情報"),
        ]

    def _system_navigation_buttons(self):
        return [
            self.resident_button, self.update_button,
            self.online_license_button,
            self.history_button, self.self_test_button,
            self.regression_button, self.release_readiness_button,
            self.support_button, self.feedback_button,
            self.public_roadmap_button, self.about_button,
            self.open_settings_button,
        ]

    def _version_text(self):
        return f"Version {APP_VERSION} {APP_CHANNEL.upper()}"

    def _developer_menu_expanded(self):
        return False

    def _developer_menu_title(self):
        return "詳細・開発者向け"

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(270)

        outer = QVBoxLayout(sidebar)
        outer.setContentsMargins(14, 18, 14, 14)
        outer.setSpacing(10)

        title = QLabel("ポケヨヤ君")
        title.setObjectName("AppTitle")
        subtitle = QLabel("TCG Reservation Assistant")
        subtitle.setObjectName("VersionLabel")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("SidebarMenuContainer")
        menu = QVBoxLayout(container)
        menu.setContentsMargins(4, 6, 4, 6)
        menu.setSpacing(6)

        labels = self._navigation_labels()
        for attr, label in labels:
            setattr(self, attr, self._make_nav_button(label))

        self.open_settings_button = QPushButton("設定ソフトを開く")
        self.open_settings_button.setObjectName("NavigationButton")
        self.open_settings_button.setMinimumHeight(40)

        self.navigation_buttons = [
            getattr(self, attr) for attr, _ in labels
        ]

        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        for button in self.navigation_buttons:
            self.navigation_group.addButton(button)
        self.home_button.setChecked(True)

        menu.addWidget(self.home_button)

        self.menu_sections = {}
        self.menu_sections["商品・応募"] = self._add_collapsible_section(
            menu,
            "商品・応募",
            [
                self.product_button,
                self.application_dashboard_button,
                self.calendar_button,
                self.statistics_button,
                self.candidates_button,
                self.lottery_button,
            ],
            expanded=True,
        )
        self.menu_sections["監視"] = self._add_collapsible_section(
            menu,
            "監視",
            [
                self.scheduler_button,
                self.sources_button,
                self.site_master_button,
            ],
            expanded=True,
        )
        self.menu_sections["通知"] = self._add_collapsible_section(
            menu,
            "通知",
            [
                self.notification_center_button,
                self.external_notification_button,
            ],
            expanded=True,
        )
        other_section = self._add_collapsible_section(
            menu,
            "その他",
            [
                self.support_button,
                self.feedback_button,
                self.public_roadmap_button,
                self.history_button,
                self.about_button,
            ],
            expanded=self._developer_menu_expanded(),
        )
        self.menu_sections["その他"] = other_section
        self._add_developer_menu(
            other_section[2],
            [
                self.email_accounts_button,
                self.plugin_button,
                self.plugin_distribution_button,
                self.notification_button,
                self.log_viewer_button,
                self.storage_button,
                self.migration_button,
                self.backup_button,
                self.self_test_button,
                self.regression_button,
                self.release_readiness_button,
            ],
        )

        settings_buttons = [
            self.open_settings_button,
            self.resident_button,
            self.update_button,
        ]
        if hasattr(self, "online_license_button"):
            settings_buttons.append(self.online_license_button)
        self.menu_sections["設定"] = self._add_collapsible_section(
            menu,
            "設定",
            settings_buttons,
            expanded=False,
        )
        menu.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        version = QLabel(self._version_text())
        version.setObjectName("VersionLabel")
        version.setAlignment(Qt.AlignCenter)
        self.exit_button = QPushButton("終了")
        self.exit_button.setObjectName("ExitButton")
        self.exit_button.setMinimumHeight(40)

        outer.addWidget(version)
        outer.addWidget(self.exit_button)
        return sidebar

    @staticmethod
    def _make_nav_button(text):
        button = QPushButton(text)
        button.setObjectName("NavigationButton")
        button.setCheckable(True)
        button.setMinimumHeight(40)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return button

    @staticmethod
    def _add_menu_section(layout, title, buttons):
        label = QLabel(title)
        label.setObjectName("MenuSectionLabel")
        layout.addWidget(label)
        for button in buttons:
            layout.addWidget(button)
        layout.addSpacing(8)

    def _add_collapsible_section(self, layout, title, buttons, *, expanded):
        toggle = QToolButton()
        toggle.setObjectName("MenuSectionButton")
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        container = QWidget()
        container.setObjectName("MenuSectionContainer")
        section_layout = QVBoxLayout(container)
        section_layout.setContentsMargins(10, 2, 0, 4)
        section_layout.setSpacing(5)
        for button in buttons:
            section_layout.addWidget(button)
        container.setVisible(expanded)

        def set_expanded(checked):
            container.setVisible(checked)
            toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

        toggle.toggled.connect(set_expanded)
        layout.addWidget(toggle)
        layout.addWidget(container)
        return toggle, container, section_layout

    def _add_developer_menu(self, layout, buttons):
        expanded = self._developer_menu_expanded()
        toggle = QToolButton()
        toggle.setObjectName("DeveloperMenuButton")
        toggle.setText(self._developer_menu_title())
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

        container = QWidget()
        container.setObjectName("DeveloperMenuContainer")
        detail_layout = QVBoxLayout(container)
        detail_layout.setContentsMargins(10, 2, 0, 0)
        detail_layout.setSpacing(5)
        for button in buttons:
            detail_layout.addWidget(button)
        container.setVisible(expanded)

        def set_expanded(checked):
            container.setVisible(checked)
            toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

        toggle.toggled.connect(set_expanded)
        layout.addWidget(toggle)
        layout.addWidget(container)
        self.developer_menu_button = toggle
        self.developer_menu_container = container

    def _build_pages(self):
        pages = QStackedWidget()
        pages.setContentsMargins(24, 24, 24, 24)

        self.home_page = HomePage(self.monitor_scheduler)
        self.product_page = ProductPage()
        self.application_dashboard_page = ApplicationDashboardPage()
        self.calendar_page = CalendarPage()
        self.statistics_page = StatisticsPage()
        self.home_page.navigate_requested.connect(self._navigate_to)
        self.calendar_page.navigate_requested.connect(self._navigate_to)
        self.application_dashboard_page.open_lottery_page.connect(
            self._show_lottery_page
        )
        self.candidates_page = CandidatesPage()
        self.lottery_page = LotteryPage()
        self.email_accounts_page = EmailAccountsPage()
        self.sources_page = SourcesPage()
        self.site_master_page = SiteMasterPage()
        self.plugin_page = PluginPage()
        self.plugin_distribution_page = PluginDistributionPage()
        self.scheduler_page = SchedulerPage(self.monitor_scheduler)
        self.notification_center_page = NotificationCenterPage()
        self.notification_page = NotificationPage()
        self.external_notification_page = ExternalNotificationPage()
        self.log_viewer_page = LogViewerPage()
        self.storage_page = StoragePage()
        self.migration_page = MigrationPage()
        self.backup_page = BackupPage()
        self.resident_page = ResidentPage()
        self.update_page = self._create_update_page()
        self.history_page = HistoryPage()
        self.self_test_page = SelfTestPage()
        self.regression_page = RegressionPage()
        self.release_readiness_page = ReleaseReadinessPage()
        self.support_page = SupportPage()
        self.feedback_page = FeedbackPage()
        self.public_roadmap_page = PublicRoadmapPage()
        self.about_page = AboutPage()

        self.page_map = {
            self.home_button: self.home_page,
            self.product_button: self.product_page,
            self.application_dashboard_button: self.application_dashboard_page,
            self.calendar_button: self.calendar_page,
            self.statistics_button: self.statistics_page,
            self.candidates_button: self.candidates_page,
            self.lottery_button: self.lottery_page,
            self.email_accounts_button: self.email_accounts_page,
            self.sources_button: self.sources_page,
            self.site_master_button: self.site_master_page,
            self.plugin_button: self.plugin_page,
            self.plugin_distribution_button: self.plugin_distribution_page,
            self.scheduler_button: self.scheduler_page,
            self.notification_center_button: self.notification_center_page,
            self.notification_button: self.notification_page,
            self.external_notification_button: self.external_notification_page,
            self.log_viewer_button: self.log_viewer_page,
            self.storage_button: self.storage_page,
            self.migration_button: self.migration_page,
            self.backup_button: self.backup_page,
            self.resident_button: self.resident_page,
            self.update_button: self.update_page,
            self.history_button: self.history_page,
            self.self_test_button: self.self_test_page,
            self.regression_button: self.regression_page,
            self.release_readiness_button: self.release_readiness_page,
            self.support_button: self.support_page,
            self.feedback_button: self.feedback_page,
            self.public_roadmap_button: self.public_roadmap_page,
            self.about_button: self.about_page,
        }

        self._add_license_page(self.page_map)

        for page in self.page_map.values():
            pages.addWidget(page)
        pages.setCurrentWidget(self.home_page)
        return pages

    def _add_license_page(self, page_map):
        from ui.online_license_page import OnlineLicensePage

        self.online_license_page = OnlineLicensePage()
        page_map[self.online_license_button] = self.online_license_page

    def _create_update_page(self):
        from core.update_manager import UpdateManager

        return UpdatePage(UpdateManager())

    def _connect_navigation(self):
        for button, page in self.page_map.items():
            button.clicked.connect(
                lambda checked=False, target=page:
                self.pages.setCurrentWidget(target)
            )
        self.open_settings_button.clicked.connect(self.open_settings_app)
        self.exit_button.clicked.connect(self.close)

    def _navigate_to(self, target: str, item_id: str = ""):
        mapping = {
            "home": self.home_button,
            "product": self.product_button,
            "application": self.application_dashboard_button,
            "calendar": self.calendar_button,
            "statistics": self.statistics_button,
            "site_master": self.site_master_button,
            "sources": self.sources_button,
            "notifications": self.notification_center_button,
            "log": self.log_viewer_button,
            "update": self.update_button,
        }
        button = mapping.get(target)
        if button is None:
            return
        page = self.page_map[button]
        self.pages.setCurrentWidget(page)
        button.setChecked(True)
        if target == "product" and item_id:
            self.product_page.reload_saved_products()
            product = next(
                (item for item in self.product_page._all_products if str(item.get("product_id", item.get("id", ""))) == item_id),
                None,
            )
            if product:
                self.product_page.open_product_detail(product)
        elif target == "application":
            self.application_dashboard_page.reload()


    def _show_lottery_page(self):
        self.lottery_page.reload_items()
        self.pages.setCurrentWidget(
            self.lottery_page
        )

        for button in self.page_map:
            button.setChecked(
                button is self.lottery_button
            )

    def open_settings_app(self):
        if is_frozen():
            settings_exe = (
                Path(sys.executable).resolve().parent
                / self.SETTINGS_EXECUTABLE
            )
            if not settings_exe.exists():
                QMessageBox.warning(
                    self, "設定ソフトが見つかりません",
                    f"{self.SETTINGS_EXECUTABLE}が同じフォルダーにありません。",
                )
                return
            subprocess.Popen([str(settings_exe)])
            return

        app_folder = Path(__file__).resolve().parents[1]
        settings_script = app_folder / "settings_main.py"
        subprocess.Popen(
            [sys.executable, str(settings_script)],
            cwd=str(app_folder.parent),
        )

    def set_tray_controller(self, controller):
        self.tray_controller = controller
        self.resident_page.tray_controller = controller
        QTimer.singleShot(0, self._check_application_assistant)

    def _setup_application_assistant(self):
        self.application_store = ProductStore()
        self.application_config = ConfigManager()
        self.application_reminder = ApplicationDeadlineReminder(
            self.application_store, self.application_config
        )
        self.application_change_tracker = ApplicationChangeTracker(
            self.application_store.root
        )
        self.application_notification_manager = NotificationManager(
            self.application_config
        )
        self.application_assistant_timer = QTimer(self)
        self.application_assistant_timer.setInterval(60_000)
        self.application_assistant_timer.timeout.connect(
            self._check_application_assistant
        )
        self.application_assistant_timer.start()

    def _check_application_assistant(self):
        try:
            products = self.application_store.load_products()
            self.application_change_tracker.compare_and_update(products)
            assistant = self.application_config.load().get(
                "application_assistant", {}
            )
            important_only = bool(
                assistant.get("important_changes_only", True)
            )
            all_pending_changes = self.application_change_tracker.pending_notifications(
                important_only=False
            )
            notified_change_ids = []
            for event in all_pending_changes:
                if important_only and not event.get("important"):
                    notified_change_ids.append(str(event.get("id", "")))
                    continue
                self.application_notification_manager.notify_application_change(
                    event, parent=self, tray_controller=self.tray_controller
                )
                notified_change_ids.append(str(event.get("id", "")))
            self.application_change_tracker.mark_notified(notified_change_ids)
            self.application_reminder.run(
                lambda reminder: self.application_notification_manager.notify_application_deadline(
                    reminder, parent=self, tray_controller=self.tray_controller
                )
            )
        except (OSError, ValueError, TypeError):
            # 応募支援の一時的な失敗でUser/Owner本体の起動・監視を止めない。
            return

    def changeEvent(self, event):
        super().changeEvent(event)
        if (
            event.type() == QEvent.WindowStateChange
            and self.isMinimized()
            and self.behavior_config.load().get("minimize_to_tray", True)
            and self.tray_controller is not None
        ):
            self.tray_controller.hide_window()

    def closeEvent(self, event: QCloseEvent):
        if (
            not self.allow_close
            and self.behavior_config.load().get("close_to_tray", True)
            and self.tray_controller is not None
        ):
            event.ignore()
            self.tray_controller.hide_window()
            return
        event.accept()

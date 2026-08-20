import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QToolButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.behavior_config import BehaviorConfig
from core.application_change_tracker import ApplicationChangeTracker
from core.application_reminder import ApplicationDeadlineReminder
from core.application_notifications import ApplicationNotificationService
from core.config_manager import ConfigManager
from core.initial_data_bootstrap import InitialDataBootstrap
from core.notification_manager import NotificationManager
from core.product_store import ProductStore
from core.monitor_scheduler import MonitorScheduler
from core.p2_startup import P2StartupCoordinator, should_show_user_state_warning
from core.runtime_paths import is_frozen
from core.startup_diagnostics import StartupDiagnostics
from core.tcg_categories import categories
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
from ui.global_search_widget import GlobalSearchWidget
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


class InitialDataBootstrapWorker(QObject):
    official_loaded = Signal(dict)
    retail_progress = Signal(dict)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def is_cancel_requested(self) -> bool:
        return (
            self._cancel_requested.is_set()
            or QThread.currentThread().isInterruptionRequested()
        )

    @Slot()
    def run(self):
        try:
            self.completed.emit(InitialDataBootstrap().run(
                on_official_loaded=self.official_loaded.emit,
                on_retail_progress=self.retail_progress.emit,
                cancel_requested=self.is_cancel_requested,
            ))
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    SETTINGS_EXECUTABLE = "ポケヨヤ君_設定.exe"
    SHUTDOWN_WAIT_MS = 5000

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self._window_title())
        self.resize(1280, 780)
        self.setMinimumSize(860, 560)

        self.behavior_config = BehaviorConfig()
        self.ui_config_manager = ConfigManager()
        self.ui_mode = self._configured_ui_mode()
        self.monitor_scheduler = MonitorScheduler(self)
        self.monitor_scheduler.suspend("起動調整中")
        self.tray_controller = None
        self.allow_close = False
        self._startup_coordination_complete = False
        self._shutdown_started = False
        self._shutdown_complete = False
        self._deferred_quit_requested = False
        self._pending_monitor_refresh = set()
        self.p2_startup_result = P2StartupCoordinator().run()
        self._build_ui()
        if should_show_user_state_warning(self.p2_startup_result, sys.argv):
            QTimer.singleShot(0, self._show_user_state_safety_warning)
        self.monitor_scheduler.run_completed.connect(
            self._refresh_data_pages_after_monitor
        )
        self.monitor_scheduler.worker_finished.connect(
            self._continue_startup_after_monitor
        )

        self._setup_application_assistant()
        self.monitor_refresh_timer = QTimer(self)
        self.monitor_refresh_timer.setSingleShot(True)
        self.monitor_refresh_timer.setInterval(500)
        self.monitor_refresh_timer.timeout.connect(
            self._flush_monitor_refresh
        )
        self.ui_mode_timer = QTimer(self)
        self.ui_mode_timer.setInterval(1500)
        self.ui_mode_timer.timeout.connect(self._reload_ui_mode)
        self.ui_mode_timer.start()
        self.setup_wizard = None
        self.gmail_setup_dialog = None
        self.initial_data_thread = None
        self.initial_data_worker = None
        self.shutdown_poll_timer = QTimer(self)
        self.shutdown_poll_timer.setInterval(100)
        self.shutdown_poll_timer.timeout.connect(
            self._complete_deferred_quit_if_ready
        )
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(
                self.shutdown_background_work
            )
        QTimer.singleShot(0, self._show_initial_setup_if_needed)

    def _show_user_state_safety_warning(self):
        QMessageBox.warning(
            self,
            "ユーザー状態ファイルの復元が必要です",
            "user_state.jsonが破損しているため、状態更新と自動監視を停止しました。\n"
            "ファイルは変更していません。バックアップからの復元を行ってください。",
        )

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
        self.sidebar = sidebar
        self.pages = self._build_pages()
        self._connect_navigation()

        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.global_search = GlobalSearchWidget(lambda: self.ui_mode)
        self.global_search.result_activated.connect(self._navigate_to)
        main_layout.addWidget(self.global_search)
        main_layout.addWidget(self.pages, 1)

        content_layout.addWidget(sidebar)
        content_layout.addWidget(main_area, 1)
        root.addWidget(content, 1)

    def _window_title(self):
        return f"ポケヨヤ君 Ver.{APP_VERSION} {APP_CHANNEL.upper()}"

    def _edition_banner(self):
        return None

    def _is_owner_edition(self):
        return False

    def _show_initial_setup_if_needed(self):
        if self._shutdown_started:
            return
        from core.setup_coordinator import SetupCoordinator

        coordinator = SetupCoordinator()
        if not coordinator.is_completed():
            self.open_setup_wizard(coordinator=coordinator)

    def open_setup_wizard(self, *, coordinator=None):
        from ui.setup_wizard import SetupWizard

        if self.setup_wizard is not None and self.setup_wizard.isVisible():
            self.setup_wizard.raise_()
            self.setup_wizard.activateWindow()
            return self.setup_wizard
        self.setup_wizard = SetupWizard(
            coordinator=coordinator,
            owner_edition=self._is_owner_edition(),
            parent=self,
        )
        self.setup_wizard.completed.connect(self._setup_wizard_completed)
        self.setup_wizard.show()
        return self.setup_wizard

    def _setup_wizard_completed(self, values):
        if self._shutdown_started:
            return
        self._apply_ui_mode(values.get("ui_mode", "simple"))
        self.monitor_scheduler.suspend("初回商品取得の確認中")
        self._navigate_to("home")
        if values.get("gmail_setup_now"):
            from ui.setup_wizard import GmailSetupDialog

            self.gmail_setup_dialog = GmailSetupDialog(self)
            self.gmail_setup_dialog.show()
        QTimer.singleShot(0, self._start_initial_data_bootstrap)

    def _start_initial_data_bootstrap(self):
        if self._shutdown_started or self._startup_coordination_complete:
            return False
        if "--smoke-test" in sys.argv:
            self._complete_startup_coordination()
            return False
        if self.initial_data_thread is not None:
            StartupDiagnostics().write(
                "Initial data bootstrap duplicate start was suppressed"
            )
            return False
        if self.monitor_scheduler.running:
            StartupDiagnostics().write(
                "Initial data bootstrap was deferred because "
                "a monitor worker is already running"
            )
            return False
        if not bool(
            self.ui_config_manager.load().get(
                "general", {}
            ).get("setup_completed", False)
        ):
            return False

        self.monitor_scheduler.suspend("初回商品取得中")
        bootstrap = InitialDataBootstrap()
        if not bootstrap.should_run():
            self._complete_startup_coordination()
            return False

        StartupDiagnostics().write(
            "Initial data bootstrap: empty products/candidates detected; "
            "starting official source retrieval"
        )
        if hasattr(self, "product_page"):
            self.product_page.result_label.setText(
                "初回の商品情報をバックグラウンドで取得しています。"
            )

        self.initial_data_thread = QThread(self)
        self.initial_data_worker = InitialDataBootstrapWorker()
        self.initial_data_worker.moveToThread(self.initial_data_thread)
        self.initial_data_thread.started.connect(self.initial_data_worker.run)
        self.initial_data_worker.completed.connect(
            self._initial_data_bootstrap_completed
        )
        self.initial_data_worker.official_loaded.connect(
            self._initial_data_bootstrap_official_loaded
        )
        self.initial_data_worker.retail_progress.connect(
            self._initial_data_bootstrap_retail_progress
        )
        self.initial_data_worker.failed.connect(
            self._initial_data_bootstrap_failed
        )
        self.initial_data_worker.completed.connect(self.initial_data_thread.quit)
        self.initial_data_worker.failed.connect(self.initial_data_thread.quit)
        self.initial_data_worker.completed.connect(
            self.initial_data_worker.deleteLater
        )
        self.initial_data_worker.failed.connect(
            self.initial_data_worker.deleteLater
        )
        self.initial_data_thread.finished.connect(
            self._initial_data_bootstrap_finished
        )
        self.initial_data_thread.finished.connect(
            self.initial_data_thread.deleteLater
        )
        self.initial_data_thread.start()
        return True

    @Slot(dict)
    def _initial_data_bootstrap_official_loaded(self, result):
        if self._shutdown_started or not result.get("started"):
            return
        per_tcg = result.get("per_tcg", {})
        StartupDiagnostics().write(
            "Initial data bootstrap official phase: "
            f'sources={result.get("source_count", 0)} '
            f'changed={result.get("changed_source_count", 0)} '
            f'candidates={result.get("candidate_count", 0)} '
            f'products={result.get("product_count", 0)} '
            f'retail_targets={result.get("retail_candidate_count", 0)} '
            + " ".join(
                f"{item.key}={per_tcg.get(item.key, 0)}"
                for item in categories()
            )
        )
        self.product_page.reload_saved_products()
        self.candidates_page.reload_candidates()
        self.sources_page.reload_sources()
        if result.get("retail_candidate_count", 0):
            self.product_page.result_label.setText(
                "公式商品を読み込みました。応募・予約情報を"
                "バックグラウンドで確認しています。"
            )

    @Slot(dict)
    def _initial_data_bootstrap_retail_progress(self, progress):
        if self._shutdown_started:
            return
        searched = int(progress.get("searched", 0))
        total = int(progress.get("total", 0))
        name = str(progress.get("candidate_name", ""))
        StartupDiagnostics().write(
            "Initial application search progress: "
            f"{searched}/{total} candidate={name}"
        )
        self.product_page.reload_saved_products()
        self.application_dashboard_page.reload()
        self.candidates_page.reload_candidates()
        self.product_page.result_label.setText(
            f"応募・予約情報を確認中です（{searched}/{total}件）。"
        )

    @Slot(dict)
    def _initial_data_bootstrap_completed(self, result):
        if self._shutdown_started or not result.get("started"):
            return
        if result.get("cancelled"):
            StartupDiagnostics().write(
                "Initial data bootstrap was cancelled at a safe boundary"
            )
            return
        StartupDiagnostics().write(
            "Initial data bootstrap completed: "
            f'products={result.get("product_count", 0)} '
            f'retail_targets={result.get("retail_candidate_count", 0)} '
            f'retail_searched={result.get("retail_searched_count", 0)}'
        )
        self.product_page.reload_saved_products()
        self.application_dashboard_page.reload()
        self.candidates_page.reload_candidates()
        self.product_page.result_label.setText(
            "初回の商品・応募情報の確認が完了しました。"
        )

    @Slot(str)
    def _initial_data_bootstrap_failed(self, message):
        StartupDiagnostics().write(
            f"Initial data bootstrap failed: {message}"
        )
        if not self._shutdown_started and hasattr(self, "product_page"):
            self.product_page.result_label.setText(
                "初回の商品情報取得に失敗しました。"
                "公式情報ソース画面から再確認できます。"
            )

    @Slot()
    def _initial_data_bootstrap_finished(self):
        self.initial_data_worker = None
        self.initial_data_thread = None
        if self._shutdown_started:
            self._complete_deferred_quit_if_ready()
            return
        self._complete_startup_coordination()

    def _complete_startup_coordination(self):
        if self._startup_coordination_complete or self._shutdown_started:
            return
        self._startup_coordination_complete = True
        self.monitor_scheduler.resume()

    @Slot()
    def _continue_startup_after_monitor(self):
        if (
            self._shutdown_started
            or self._startup_coordination_complete
            or self.initial_data_thread is not None
        ):
            return
        QTimer.singleShot(0, self._start_initial_data_bootstrap)

    @Slot(dict)
    def _refresh_data_pages_after_monitor(self, _result):
        if self._shutdown_started:
            return
        result = _result if isinstance(_result, dict) else {}
        if not result:
            self._pending_monitor_refresh.update(
                {"products", "applications", "candidates", "sources"}
            )
            self._flush_monitor_refresh()
            return
        if result.get("source_count"):
            self._pending_monitor_refresh.add("sources")
        if result.get("changed_sources"):
            self._pending_monitor_refresh.update({"products", "candidates"})
        candidate = result.get("candidate_search", {})
        if candidate.get("new_hit_candidates"):
            self._pending_monitor_refresh.update({"products", "applications", "candidates"})
        x_recent = result.get("x_recent", {})
        if x_recent.get("candidate_count") or x_recent.get("promoted_count"):
            self._pending_monitor_refresh.update(
                {"products", "applications", "candidates", "sources"}
            )
        if result.get("newly_won") or result.get("gmail_results"):
            self._pending_monitor_refresh.add("applications")
        if not self._pending_monitor_refresh:
            return
        self.monitor_refresh_timer.start()

    def _flush_monitor_refresh(self):
        if self._shutdown_started:
            self._pending_monitor_refresh.clear()
            return
        pending = set(self._pending_monitor_refresh)
        self._pending_monitor_refresh.clear()
        if "products" in pending:
            self.product_page.reload_saved_products()
        if "applications" in pending:
            self.application_dashboard_page.reload()
        if "candidates" in pending:
            self.candidates_page.reload_candidates()
        if "sources" in pending:
            self.sources_page.reload_sources()

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
        return self.ui_mode == "detailed"

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
                self.email_accounts_button,
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
        self.simple_mode_buttons = {
            self.home_button,
            self.product_button,
            self.application_dashboard_button,
            self.calendar_button,
            self.notification_center_button,
            self.email_accounts_button,
            self.scheduler_button,
            self.open_settings_button,
        }
        self._apply_ui_mode(self.ui_mode)
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
        return toggle, container, section_layout, tuple(buttons)

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

    def _configured_ui_mode(self):
        try:
            configured = self.ui_config_manager.load().get("general", {}).get(
                "ui_mode", "simple"
            )
        except (OSError, ValueError, TypeError):
            return "simple"
        return "detailed" if configured == "detailed" else "simple"

    def _reload_ui_mode(self):
        mode = self._configured_ui_mode()
        if mode != self.ui_mode:
            self._apply_ui_mode(mode)

    def _apply_ui_mode(self, mode):
        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        self.ui_mode = "detailed" if mode == "detailed" else "simple"
        detailed = self.ui_mode == "detailed"

        for button in self.navigation_buttons:
            button.setVisible(detailed or button in self.simple_mode_buttons)
        self.open_settings_button.setVisible(True)

        for title, section in self.menu_sections.items():
            toggle, container, _, buttons = section
            section_visible = detailed or any(
                button in self.simple_mode_buttons for button in buttons
            )
            toggle.setVisible(section_visible)
            if not section_visible:
                container.setVisible(False)
                continue
            if detailed or title in {"商品・応募", "監視", "通知", "設定"}:
                toggle.setChecked(True)
            container.setVisible(toggle.isChecked())

        self.developer_menu_button.setVisible(detailed)
        self.developer_menu_button.setChecked(detailed)
        self.developer_menu_container.setVisible(detailed)
        if hasattr(self, "global_search"):
            self.global_search.refresh_for_mode_change()

        if not detailed and hasattr(self, "pages"):
            current_page = self.pages.currentWidget()
            hidden_current_page = any(
                page is current_page and button not in self.simple_mode_buttons
                for button, page in self.page_map.items()
            )
            if hidden_current_page:
                self.pages.setCurrentWidget(self.home_page)
                self.home_button.setChecked(True)
        self.setUpdatesEnabled(updates_enabled)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sidebar"):
            target_width = 230 if event.size().width() < 1080 else 270
            if self.sidebar.width() != target_width:
                self.sidebar.setFixedWidth(target_width)

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
        self.update_page.set_quit_callback(
            self.request_application_quit
        )
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
        QTimer.singleShot(0, self._start_initial_data_bootstrap)

    def _setup_application_assistant(self):
        self.application_store = ProductStore()
        self.application_config = ConfigManager()
        self.application_reminder = ApplicationDeadlineReminder(
            self.application_store, self.application_config
        )
        self.application_event_notifications = ApplicationNotificationService(
            self.application_config
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
        if self._shutdown_started:
            return
        try:
            products = self.application_store.load_products()
            for event in self.application_event_notifications.collect(products):
                self.application_notification_manager.notify_application_event(
                    event,
                    parent=self,
                    tray_controller=self.tray_controller,
                )
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
        event.ignore()
        self.request_application_quit()

    def request_application_quit(self):
        if self._shutdown_complete:
            application = QApplication.instance()
            if application is not None:
                application.quit()
            return
        self.allow_close = True
        if self.tray_controller is not None:
            self.tray_controller.tray.hide()
        stopped = self.shutdown_background_work()
        if stopped:
            self._shutdown_complete = True
            application = QApplication.instance()
            if application is not None:
                application.quit()
            return
        self._deferred_quit_requested = True
        self.hide()
        if not self.shutdown_poll_timer.isActive():
            self.shutdown_poll_timer.start()

    @Slot()
    def shutdown_background_work(self) -> bool:
        if self._shutdown_complete:
            return True
        self._shutdown_started = True
        self.ui_mode_timer.stop()
        self.application_assistant_timer.stop()
        self.monitor_scheduler.request_shutdown()
        self.candidates_page.request_shutdown()
        self.update_page.request_shutdown()

        if self.initial_data_worker is not None:
            self.initial_data_worker.cancel()
        if (
            self.initial_data_thread is not None
            and self.initial_data_thread.isRunning()
        ):
            self.initial_data_thread.requestInterruption()
            self.initial_data_thread.quit()

        deadline = time.monotonic() + (self.SHUTDOWN_WAIT_MS / 1000)
        initial_stopped = self._wait_for_initial_data_thread(
            self._remaining_wait_ms(deadline)
        )
        monitor_stopped = self.monitor_scheduler.wait_for_shutdown(
            self._remaining_wait_ms(deadline)
        )
        candidate_search_stopped = self.candidates_page.wait_for_shutdown(
            self._remaining_wait_ms(deadline)
        )
        update_stopped = self.update_page.wait_for_shutdown(
            self._remaining_wait_ms(deadline)
        )
        stopped = (
            initial_stopped
            and monitor_stopped
            and candidate_search_stopped
            and update_stopped
        )
        if not stopped:
            StartupDiagnostics().write(
                "Background shutdown exceeded the bounded wait. "
                "The app will remain alive without starting new work "
                "until workers reach a safe boundary."
            )
        return stopped

    def _wait_for_initial_data_thread(self, timeout_ms: int) -> bool:
        thread = self.initial_data_thread
        if thread is None or not thread.isRunning():
            return True
        stopped = thread.wait(max(0, min(int(timeout_ms), self.SHUTDOWN_WAIT_MS)))
        if not stopped:
            StartupDiagnostics().write(
                "Initial data bootstrap exceeded the shutdown wait limit; "
                "forced termination was not used"
            )
        return bool(stopped)

    @staticmethod
    def _remaining_wait_ms(deadline: float) -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    def _background_threads_stopped(self) -> bool:
        initial_stopped = (
            self.initial_data_thread is None
            or not self.initial_data_thread.isRunning()
        )
        monitor_thread = self.monitor_scheduler.thread
        monitor_stopped = (
            monitor_thread is None or not monitor_thread.isRunning()
        )
        return (
            initial_stopped
            and monitor_stopped
            and self.candidates_page.is_shutdown_complete()
            and self.update_page.is_shutdown_complete()
        )

    @Slot()
    def _complete_deferred_quit_if_ready(self):
        if (
            not self._deferred_quit_requested
            or not self._background_threads_stopped()
        ):
            return
        self.shutdown_poll_timer.stop()
        self._shutdown_complete = True
        application = QApplication.instance()
        if application is not None:
            application.quit()

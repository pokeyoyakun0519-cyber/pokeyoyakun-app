from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.credential_store import CredentialStore
from core.log_manager import LogManager
from core.maintenance import MaintenanceManager, format_bytes
from core.site_master_manager import SiteMasterManager
from core.site_monitor_sync import SiteMonitorSync
from core.tcg_categories import categories, display_name
from core.product_categories import PRODUCT_CATEGORY_LABELS


class SettingsPage(QFrame):
    CATEGORY_NAMES = (
        "基本設定",
        "表示",
        "監視",
        "通知",
        "アカウント・連携",
        "データ管理",
        "詳細設定",
    )
    SIMPLE_CATEGORIES = frozenset(CATEGORY_NAMES[:5])

    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.config_manager = ConfigManager()
        self.credential_store = CredentialStore()
        self.maintenance = MaintenanceManager()
        self.log_manager = LogManager()
        self.site_manager = SiteMasterManager()
        self.site_sync = SiteMonitorSync(self.config_manager, self.site_manager)
        self.setting_cards = []
        self.category_pages = {}
        self.category_layouts = {}
        self._baseline_values = {}
        self.has_unsaved_changes = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 26, 28, 26)
        outer.setSpacing(14)

        title = QLabel("ポケヨヤ君設定")
        title.setObjectName("PageTitle")
        subtitle = QLabel("設定はカテゴリ別に整理されています。項目名で検索することもできます。")
        subtitle.setObjectName("MutedText")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        search_row = QHBoxLayout()
        self.settings_search = QLineEdit()
        self.settings_search.setObjectName("SettingsSearch")
        self.settings_search.setPlaceholderText("設定を検索（例：通知、締切、店舗、パスワード）")
        self.search_result_label = QLabel("")
        self.search_result_label.setObjectName("MutedText")
        search_row.addWidget(self.settings_search, 1)
        search_row.addWidget(self.search_result_label)
        outer.addLayout(search_row)

        self.category_tabs = QTabWidget()
        self.category_tabs.setObjectName("SettingsCategoryTabs")
        for category in self.CATEGORY_NAMES:
            self._add_category(category)
        outer.addWidget(self.category_tabs, 1)

        self._build_basic_settings()
        self._build_display_settings()
        self._build_monitoring_settings()
        self._build_notification_settings()
        self._build_account_settings()
        self._build_data_settings()
        self._build_detailed_settings()

        save_row = QHBoxLayout()
        self.save_status = QLabel("変更はありません。")
        self.save_status.setObjectName("SettingsSaveStatus")
        self.save_status.setProperty("state", "clean")
        self.save_button = QPushButton("設定を保存")
        self.save_button.setObjectName("AccentButton")
        self.save_button.clicked.connect(self.save_settings)
        save_row.addWidget(self.save_status, 1)
        save_row.addWidget(self.save_button)
        outer.addLayout(save_row)

        self.load_settings()
        self._setup_change_tracking()
        self.settings_search.textChanged.connect(self._apply_settings_filter)
        self.ui_mode.currentIndexChanged.connect(self._apply_settings_filter)
        self._apply_settings_filter()
        self.update_cache_size()

    def _add_category(self, category):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 12, 8, 12)
        layout.setSpacing(14)
        layout.addStretch()
        scroll.setWidget(container)
        self.category_tabs.addTab(scroll, category)
        self.category_pages[category] = scroll
        self.category_layouts[category] = layout

    def _register_card(self, category, title, card, *search_terms):
        layout = self.category_layouts[category]
        layout.insertWidget(layout.count() - 1, card)
        self.setting_cards.append({
            "category": category,
            "title": title,
            "card": card,
            "search": " ".join((category, title, *search_terms)).casefold(),
        })
        return card

    def _make_card(self, title_text):
        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)
        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)
        return card

    def _build_basic_settings(self):
        card = self._make_card("アプリの基本動作")
        self.auto_input = QCheckBox("アカウント登録フォームへの入力補助を有効にする")
        self.new_product_fetch = QCheckBox("起動時に新弾情報を確認する")
        card.layout().addWidget(self.auto_input)
        card.layout().addWidget(self.new_product_fetch)
        self.rerun_setup_button = QPushButton("初回セットアップを再実行")
        self.rerun_setup_button.clicked.connect(self.open_setup_wizard)
        card.layout().addWidget(self.rerun_setup_button)
        self._register_card("基本設定", "アプリの基本動作", card, "起動 新商品 入力補助")

    def _build_display_settings(self):
        mode_card = self._make_card("表示モード")
        note = QLabel(
            "かんたんモードは主要設定だけを表示します。"
            "詳細モードでは、データ管理や店舗別設定を含むすべての項目を表示します。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        self.ui_mode = QComboBox()
        self.ui_mode.addItem("かんたんモード", "simple")
        self.ui_mode.addItem("詳細モード", "detailed")
        mode_card.layout().addWidget(note)
        mode_card.layout().addWidget(self.ui_mode)
        self._register_card("表示", "表示モード", mode_card, "かんたん 詳細 初心者 メニュー")

        list_card = self._make_card("一覧表示")
        self.show_ended_applications = QCheckBox("終了済み応募を通常表示へ含める")
        self.group_applications_by_product = QCheckBox("応募先を商品ごとにまとめる")
        list_card.layout().addWidget(self.show_ended_applications)
        list_card.layout().addWidget(self.group_applications_by_product)
        self._register_card("表示", "一覧表示", list_card, "終了済み 商品 応募 グループ")

    def _build_monitoring_settings(self):
        games_card = self._make_card("監視するTCG")
        games_grid = QGridLayout()
        self.game_checks = {}
        for index, category in enumerate(categories(enabled_only=True)):
            checkbox = QCheckBox(category.display_name)
            self.game_checks[category.key] = checkbox
            games_grid.addWidget(checkbox, index // 2, index % 2)
        games_card.layout().addLayout(games_grid)
        self.priority_monitoring_only = QCheckBox(
            "ポケモンカード／ONE PIECEを優先監視（他TCGの自動巡回を停止）"
        )
        games_card.layout().addWidget(self.priority_monitoring_only)
        self._register_card("監視", "監視するTCG", games_card, "ポケモン ワンピース 遊戯王 ガンダム")

        monitor_card = self._make_card("新商品の自動監視")
        self.auto_monitor_new_releases = QCheckBox("新弾を発売日前に自動で監視へ追加する")
        self.auto_monitor_days = QComboBox()
        for days in (7, 14, 30, 60):
            self.auto_monitor_days.addItem(f"発売{days}日前", days)
        self.notify_new_sites = QCheckBox("新規店舗が追加されたら通知する")
        monitor_card.layout().addWidget(self.auto_monitor_new_releases)
        monitor_card.layout().addWidget(self.auto_monitor_days)
        monitor_card.layout().addWidget(self.notify_new_sites)
        self._register_card("監視", "新商品の自動監視", monitor_card, "発売日 新弾 新店舗 日数")

    def _build_notification_settings(self):
        behavior_card = self._make_card("通知の基本動作")
        self.sound_enabled = QCheckBox("通知音を鳴らす")
        self.popup_enabled = QCheckBox("ポップアップ通知を表示する")
        self.notify_important_application_changes = QCheckBox("重要な変更だけ通知")
        behavior_card.layout().addWidget(self.sound_enabled)
        behavior_card.layout().addWidget(self.popup_enabled)
        behavior_card.layout().addWidget(self.notify_important_application_changes)
        self._register_card("通知", "通知の基本動作", behavior_card, "音 ポップアップ 重要 変更")

        event_card = self._make_card("応募・販売情報の通知対象")
        self.application_events_enabled = QCheckBox("新規confirmed・受付開始・再販を通知")
        event_card.layout().addWidget(self.application_events_enabled)
        event_card.layout().addWidget(QLabel("TCG"))
        self.notification_tcg_checks = {}
        for key, label in (
            ("pokemon", "Pokemon"),
            ("onepiece", "ONE PIECE"),
            ("union_arena", "UNION ARENA"),
            ("dragon_ball_fusion_world", "Dragon Ball Fusion World"),
        ):
            checkbox = QCheckBox(label)
            self.notification_tcg_checks[key] = checkbox
            event_card.layout().addWidget(checkbox)
        event_card.layout().addWidget(QLabel("販売方式"))
        self.notification_sales_checks = {}
        for mode, label in (
            ("ONLINE", "ネット販売"),
            ("STORE", "店舗販売"),
            ("HYBRID", "オンライン応募・店舗受取"),
        ):
            checkbox = QCheckBox(label)
            self.notification_sales_checks[mode] = checkbox
            event_card.layout().addWidget(checkbox)
        self.notification_prefectures = QLineEdit()
        self.notification_prefectures.setPlaceholderText("都道府県をカンマ区切り。空欄は全国")
        event_card.layout().addWidget(self.notification_prefectures)
        self.notification_regions = QLineEdit()
        self.notification_regions.setPlaceholderText("地方をカンマ区切り。空欄は全地方")
        event_card.layout().addWidget(self.notification_regions)
        self.notification_favorite_store_only = QCheckBox("お気に入り店舗だけ通知")
        self.notification_new_only = QCheckBox("新着（24時間以内）だけ通知")
        self.notification_deadline_soon_only = QCheckBox("締切間近（72時間以内）だけ通知")
        event_card.layout().addWidget(self.notification_favorite_store_only)
        event_card.layout().addWidget(self.notification_new_only)
        event_card.layout().addWidget(self.notification_deadline_soon_only)
        event_card.layout().addWidget(QLabel("商品カテゴリ"))
        self.notification_product_category_checks = {}
        for value, label in PRODUCT_CATEGORY_LABELS.items():
            checkbox = QCheckBox(label)
            self.notification_product_category_checks[value] = checkbox
            event_card.layout().addWidget(checkbox)
        self._register_card(
            "通知",
            "応募・販売情報の通知対象",
            event_card,
            "confirmed TCG 販売方式 都道府県 カテゴリ 再販 予約 抽選",
        )

        reminder_card = self._make_card("締切リマインダー")
        reminder_note = QLabel("未応募かつ受付中で、締切日時が確定している案件だけを通知します。")
        reminder_note.setObjectName("MutedText")
        reminder_note.setWordWrap(True)
        self.deadline_24h = QCheckBox("締切24時間前に通知")
        self.deadline_3h = QCheckBox("締切3時間前に通知")
        self.deadline_30m = QCheckBox("締切30分前に通知")
        reminder_card.layout().addWidget(reminder_note)
        reminder_card.layout().addWidget(self.deadline_24h)
        reminder_card.layout().addWidget(self.deadline_3h)
        reminder_card.layout().addWidget(self.deadline_30m)
        self._register_card("通知", "締切リマインダー", reminder_card, "24時間 3時間 30分 応募")

        sound_card = self._make_card("通知音ファイル")
        sound_row = QHBoxLayout()
        self.sound_path = QLineEdit()
        self.sound_path.setReadOnly(True)
        choose_button = QPushButton("WAVファイルを選択")
        choose_button.clicked.connect(self.choose_sound_file)
        sound_row.addWidget(self.sound_path, 1)
        sound_row.addWidget(choose_button)
        sound_card.layout().addLayout(sound_row)
        self._register_card("通知", "通知音ファイル", sound_card, "WAV サウンド ファイル")

    def _build_account_settings(self):
        profile_card = self._make_card("入力補助プロフィール")
        profile_layout = QFormLayout()
        profile_layout.setSpacing(10)
        self.name_input = QLineEdit()
        self.furigana_input = QLineEdit()
        self.email_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.phone_input = QLineEdit()
        self.postal_input = QLineEdit()
        self.address_input = QLineEdit()
        self.password_input.setPlaceholderText("Windowsの機能で保護して保存します")
        self.postal_input.setPlaceholderText("例：123-4567")
        profile_layout.addRow("氏名", self.name_input)
        profile_layout.addRow("フリガナ", self.furigana_input)
        profile_layout.addRow("メールアドレス", self.email_input)
        profile_layout.addRow("パスワード", self.password_input)
        profile_layout.addRow("電話番号", self.phone_input)
        profile_layout.addRow("郵便番号", self.postal_input)
        profile_layout.addRow("住所", self.address_input)
        profile_card.layout().addLayout(profile_layout)
        security_note = QLabel(
            "パスワードは通常の設定ファイルには保存せず、"
            "WindowsのDPAPIで現在のPC・Windowsユーザーに紐付けて保護します。"
        )
        security_note.setObjectName("MutedText")
        security_note.setWordWrap(True)
        profile_card.layout().addWidget(security_note)
        self._register_card("アカウント・連携", "入力補助プロフィール", profile_card, "氏名 メール パスワード 電話 住所 DPAPI")

    def _build_data_settings(self):
        card = self._make_card("キャッシュ・ログ")
        row = QHBoxLayout()
        self.cache_size_label = QLabel()
        self.cache_size_label.setObjectName("MutedText")
        clear_button = QPushButton("キャッシュ・ログを削除")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self.clear_cache)
        row.addWidget(self.cache_size_label)
        row.addStretch()
        row.addWidget(clear_button)
        card.layout().addLayout(row)
        self._register_card("データ管理", "キャッシュ・ログ", card, "削除 容量 メンテナンス temp logs")

    def _build_detailed_settings(self):
        sites_card = self._make_card("監視するサイト")
        filter_row = QHBoxLayout()
        self.site_tcg_filter = QComboBox()
        self.site_tcg_filter.addItem("すべて", "all")
        for category in categories(enabled_only=True):
            self.site_tcg_filter.addItem(category.display_name, category.key)
        self.site_search = QLineEdit()
        self.site_search.setPlaceholderText("店舗名を検索")
        enable_all = QPushButton("表示中をすべて有効")
        disable_all = QPushButton("表示中をすべて無効")
        enable_all.clicked.connect(lambda: self._set_visible_sites(True))
        disable_all.clicked.connect(lambda: self._set_visible_sites(False))
        self.site_tcg_filter.currentIndexChanged.connect(self._filter_sites)
        self.site_search.textChanged.connect(self._filter_sites)
        filter_row.addWidget(self.site_tcg_filter)
        filter_row.addWidget(self.site_search, 1)
        filter_row.addWidget(enable_all)
        filter_row.addWidget(disable_all)
        sites_card.layout().addLayout(filter_row)

        self.site_checks = {}
        self.site_rows = {}
        sync_result = self.site_sync.sync(notify=False)
        new_ids = set(sync_result.get("new_site_ids", []))
        for site in sync_result.get("sites", []):
            site_id = str(site.get("id", ""))
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            checkbox = QCheckBox(str(site.get("name", site_id)))
            tcg_text = " / ".join(display_name(key) for key in site.get("tcg_keys", [])) or "TCG取扱未確認"
            support_note = ""
            if site.get("chain_support") == "partial":
                support_note = "　一部店舗のみ／取扱未確認"
            if not site.get("monitoring_supported", False):
                support_note += "　自動監視未対応（公式URLを手動確認）"
            info = QLabel(
                tcg_text
                + f'　{site.get("application_method", "Web")}　{site.get("site_url", "")}'
                + support_note
                + ("　新規" if site_id in new_ids else "")
                + ("　利用停止" if not site.get("active", True) else "")
            )
            info.setObjectName("MutedText")
            info.setWordWrap(True)
            checkbox.setEnabled(bool(site.get("active", True)) and bool(site.get("monitoring_supported", False)))
            row_layout.addWidget(checkbox)
            row_layout.addWidget(info, 1)
            sites_card.layout().addWidget(row)
            self.site_checks[site_id] = checkbox
            self.site_rows[site_id] = (row, site)
        self._register_card("詳細設定", "監視するサイト", sites_card, "店舗 サイト URL partial manual 公式")

    def load_settings(self):
        config = self.config_manager.load()
        general = config["general"]
        profile = config["profile"]
        notification = config["notification"]
        assistant = config.get("application_assistant", {})

        self.ui_mode.setCurrentIndex(max(0, self.ui_mode.findData(general.get("ui_mode", "simple"))))
        for key, checkbox in self.game_checks.items():
            checkbox.setChecked(bool(config["games"].get(key, True)))
        self.priority_monitoring_only.setChecked(bool(
            general.get("priority_monitoring_only", False)
        ))
        for site_id, checkbox in self.site_checks.items():
            checkbox.setChecked(bool(config["sites"].get(site_id, False)))
        self.auto_input.setChecked(general["auto_input_enabled"])
        self.new_product_fetch.setChecked(general["new_product_auto_fetch"])
        self.sound_enabled.setChecked(general["play_notification_sound"])
        self.popup_enabled.setChecked(general["show_popup"])
        self.auto_monitor_new_releases.setChecked(bool(general.get("auto_monitor_new_releases", True)))
        self.auto_monitor_days.setCurrentIndex(max(0, self.auto_monitor_days.findData(int(general.get("auto_monitor_days_before", 30)))))
        self.show_ended_applications.setChecked(bool(general.get("show_ended_applications", False)))
        self.notify_new_sites.setChecked(bool(general.get("notify_new_monitoring_sites", True)))
        reminder_enabled = {
            int(item.get("minutes", 0)): bool(item.get("enabled", False))
            for item in assistant.get("reminders", [])
        }
        self.deadline_24h.setChecked(reminder_enabled.get(1440, True))
        self.deadline_3h.setChecked(reminder_enabled.get(180, True))
        self.deadline_30m.setChecked(reminder_enabled.get(30, True))
        self.group_applications_by_product.setChecked(bool(assistant.get("group_by_product", True)))
        self.notify_important_application_changes.setChecked(bool(assistant.get("important_changes_only", True)))
        self.name_input.setText(profile["name"])
        self.furigana_input.setText(profile["furigana"])
        self.email_input.setText(profile["email"])
        self.password_input.setText(self.credential_store.load_password())
        self.phone_input.setText(profile["phone"])
        self.postal_input.setText(profile["postal_code"])
        self.address_input.setText(profile["address"])
        self.sound_path.setText(notification["sound_file"])
        self.application_events_enabled.setChecked(
            bool(notification.get("application_events_enabled", True))
        )
        notification_tcg = notification.get("tcg", {})
        for key, checkbox in self.notification_tcg_checks.items():
            checkbox.setChecked(bool(notification_tcg.get(key, True)))
        enabled_sales_modes = set(notification.get("sales_modes", ["ONLINE", "STORE", "HYBRID"]))
        for key, checkbox in self.notification_sales_checks.items():
            checkbox.setChecked(key in enabled_sales_modes)
        self.notification_prefectures.setText(
            ", ".join(str(item) for item in notification.get("prefectures", []))
        )
        self.notification_regions.setText(
            ", ".join(str(item) for item in notification.get("regions", []))
        )
        self.notification_favorite_store_only.setChecked(
            bool(notification.get("favorite_store_only", False))
        )
        self.notification_new_only.setChecked(bool(notification.get("new_only", False)))
        self.notification_deadline_soon_only.setChecked(
            bool(notification.get("deadline_soon_only", False))
        )
        enabled_product_categories = set(
            notification.get("product_categories", list(PRODUCT_CATEGORY_LABELS))
        )
        for key, checkbox in self.notification_product_category_checks.items():
            checkbox.setChecked(key in enabled_product_categories)

    def _tracked_widgets(self):
        return [
            self.ui_mode, self.auto_input, self.new_product_fetch,
            self.show_ended_applications, self.group_applications_by_product,
            self.priority_monitoring_only,
            *self.game_checks.values(), self.auto_monitor_new_releases,
            self.auto_monitor_days, self.notify_new_sites, self.sound_enabled,
            self.popup_enabled, self.notify_important_application_changes,
            self.deadline_24h, self.deadline_3h, self.deadline_30m,
            self.application_events_enabled,
            *self.notification_tcg_checks.values(),
            *self.notification_sales_checks.values(),
            self.notification_prefectures,
            self.notification_regions,
            self.notification_favorite_store_only,
            self.notification_new_only,
            self.notification_deadline_soon_only,
            *self.notification_product_category_checks.values(),
            self.sound_path, self.name_input, self.furigana_input,
            self.email_input, self.password_input, self.phone_input,
            self.postal_input, self.address_input, *self.site_checks.values(),
        ]

    @staticmethod
    def _widget_value(widget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return None

    def _setup_change_tracking(self):
        widgets = self._tracked_widgets()
        self._baseline_values = {widget: self._widget_value(widget) for widget in widgets}
        for widget in widgets:
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._update_changed_state)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._update_changed_state)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._update_changed_state)

    def _update_changed_state(self, *_args):
        changed_count = 0
        for widget, baseline in self._baseline_values.items():
            changed = self._widget_value(widget) != baseline
            widget.setProperty("settingsChanged", changed)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            changed_count += int(changed)
        self.has_unsaved_changes = changed_count > 0
        if self.has_unsaved_changes:
            self._set_save_status(f"未保存の変更があります（{changed_count}項目）", "dirty")
            self.save_button.setText("変更を保存")
        else:
            self._set_save_status("変更はありません。", "clean")
            self.save_button.setText("設定を保存")

    def _set_save_status(self, text, state):
        self.save_status.setText(text)
        self.save_status.setProperty("state", state)
        self.save_status.style().unpolish(self.save_status)
        self.save_status.style().polish(self.save_status)

    def _apply_settings_filter(self, *_args):
        query = self.settings_search.text().strip().casefold()
        detailed = self.ui_mode.currentData() == "detailed"
        visible_cards = 0
        first_visible_tab = -1
        for category in self.CATEGORY_NAMES:
            category_allowed = detailed or category in self.SIMPLE_CATEGORIES
            category_matches = 0
            for item in self.setting_cards:
                if item["category"] != category:
                    continue
                matches = not query or query in item["search"]
                item["card"].setVisible(category_allowed and matches)
                category_matches += int(category_allowed and matches)
            index = self.category_tabs.indexOf(self.category_pages[category])
            tab_visible = category_matches > 0
            self.category_tabs.setTabVisible(index, tab_visible)
            if tab_visible and first_visible_tab < 0:
                first_visible_tab = index
            visible_cards += category_matches
        if first_visible_tab >= 0 and not self.category_tabs.isTabVisible(self.category_tabs.currentIndex()):
            self.category_tabs.setCurrentIndex(first_visible_tab)
        self.search_result_label.setText(f"{visible_cards}件" if query else "")

    def save_settings(self):
        config = self.config_manager.load()
        general = dict(config.get("general", {}))
        general.update({
            "ui_mode": str(self.ui_mode.currentData() or "simple"),
            "auto_input_enabled": self.auto_input.isChecked(),
            "new_product_auto_fetch": self.new_product_fetch.isChecked(),
            "play_notification_sound": self.sound_enabled.isChecked(),
            "show_popup": self.popup_enabled.isChecked(),
            "auto_monitor_new_releases": self.auto_monitor_new_releases.isChecked(),
            "auto_monitor_days_before": int(self.auto_monitor_days.currentData()),
            "show_ended_applications": self.show_ended_applications.isChecked(),
            "notify_new_monitoring_sites": self.notify_new_sites.isChecked(),
            "priority_monitoring_only": self.priority_monitoring_only.isChecked(),
        })
        config.update({
            "general": general,
            "profile": {
                "name": self.name_input.text().strip(), "furigana": self.furigana_input.text().strip(),
                "email": self.email_input.text().strip(), "phone": self.phone_input.text().strip(),
                "postal_code": self.postal_input.text().strip(), "address": self.address_input.text().strip(),
            },
            "notification": {
                **dict(config.get("notification", {})),
                "sound_file": self.sound_path.text().strip(),
                "application_events_enabled": self.application_events_enabled.isChecked(),
                "tcg": {
                    key: checkbox.isChecked()
                    for key, checkbox in self.notification_tcg_checks.items()
                },
                "sales_modes": [
                    key for key, checkbox in self.notification_sales_checks.items()
                    if checkbox.isChecked()
                ],
                "prefectures": [
                    value.strip()
                    for value in self.notification_prefectures.text().replace("、", ",").split(",")
                    if value.strip()
                ],
                "regions": [
                    value.strip()
                    for value in self.notification_regions.text().replace("、", ",").split(",")
                    if value.strip()
                ],
                "favorite_store_only": self.notification_favorite_store_only.isChecked(),
                "new_only": self.notification_new_only.isChecked(),
                "deadline_soon_only": self.notification_deadline_soon_only.isChecked(),
                "product_categories": [
                    key
                    for key, checkbox in self.notification_product_category_checks.items()
                    if checkbox.isChecked()
                ],
                "suppress_after_applied": True,
            },
            "games": {key: checkbox.isChecked() for key, checkbox in self.game_checks.items()},
            "sites": {key: checkbox.isChecked() for key, checkbox in self.site_checks.items()},
            "application_assistant": {
                **dict(config.get("application_assistant", {})),
                "deadline_reminders_enabled": any((self.deadline_24h.isChecked(), self.deadline_3h.isChecked(), self.deadline_30m.isChecked())),
                "reminders": [
                    {"minutes": 1440, "enabled": self.deadline_24h.isChecked(), "label": "24時間前"},
                    {"minutes": 180, "enabled": self.deadline_3h.isChecked(), "label": "3時間前"},
                    {"minutes": 30, "enabled": self.deadline_30m.isChecked(), "label": "30分前"},
                ],
                "group_by_product": self.group_applications_by_product.isChecked(),
                "important_changes_only": self.notify_important_application_changes.isChecked(),
            },
        })
        config.setdefault("site_sync", {})["new_site_ids"] = []
        try:
            self.config_manager.save(config)
            self.credential_store.save_password(self.password_input.text())
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            self._set_save_status(f"保存できませんでした。原因: {reason}", "error")
            QMessageBox.critical(self, "保存エラー", f"設定を保存できませんでした。\n\n原因: {reason}")
            return

        self.log_manager.write("設定ソフトから設定を保存しました。")
        self._baseline_values = {widget: self._widget_value(widget) for widget in self._tracked_widgets()}
        self._update_changed_state()
        self._set_save_status("✓ 設定を保存しました。", "success")
        QMessageBox.information(self, "保存完了", "設定を保存しました。")

    def open_setup_wizard(self):
        if self.has_unsaved_changes:
            self._set_save_status(
                "初回セットアップを開く前に、現在の変更を保存または元に戻してください。",
                "dirty",
            )
            return None
        from ui.setup_wizard import SetupWizard, owner_settings_runtime

        self.setup_wizard = SetupWizard(
            owner_edition=owner_settings_runtime(), parent=self.window()
        )
        self.setup_wizard.completed.connect(self._setup_wizard_completed)
        self.setup_wizard.show()
        return self.setup_wizard

    def _setup_wizard_completed(self, values):
        self.load_settings()
        self._baseline_values = {
            widget: self._widget_value(widget) for widget in self._tracked_widgets()
        }
        self._update_changed_state()
        self._apply_settings_filter()
        self._set_save_status("✓ 初回セットアップ設定を保存しました。", "success")
        if values.get("gmail_setup_now"):
            from ui.setup_wizard import GmailSetupDialog

            self.gmail_setup_dialog = GmailSetupDialog(self.window())
            self.gmail_setup_dialog.show()

    def _filter_sites(self, *_args):
        tcg_key = str(self.site_tcg_filter.currentData() or "all")
        keyword = self.site_search.text().strip().casefold()
        for site_id, (row, site) in self.site_rows.items():
            tcg_ok = tcg_key == "all" or tcg_key in site.get("tcg_keys", [])
            text_ok = not keyword or keyword in str(site.get("name", site_id)).casefold()
            row.setVisible(tcg_ok and text_ok)

    def _set_visible_sites(self, enabled):
        for site_id, checkbox in self.site_checks.items():
            row, site = self.site_rows[site_id]
            if row.isVisible() and bool(site.get("active", True)) and bool(site.get("monitoring_supported", False)):
                checkbox.setChecked(enabled)

    def choose_sound_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "通知音を選択", "", "WAVファイル (*.wav);;すべてのファイル (*.*)")
        if file_path:
            self.sound_path.setText(file_path)

    def update_cache_size(self):
        self.cache_size_label.setText(f"現在のキャッシュ・ログ容量：{format_bytes(self.maintenance.calculate_size())}")

    def clear_cache(self):
        answer = QMessageBox.question(
            self, "キャッシュ削除", "tempフォルダとlogsフォルダの中身を削除しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        removed_files, removed_bytes = self.maintenance.clear()
        self.update_cache_size()
        QMessageBox.information(
            self, "削除完了",
            f"{removed_files}個のファイルを削除しました。\n削除容量：{format_bytes(removed_bytes)}",
        )

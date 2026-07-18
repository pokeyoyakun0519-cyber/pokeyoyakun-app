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
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.tcg_categories import categories
from core.credential_store import CredentialStore
from core.log_manager import LogManager
from core.maintenance import MaintenanceManager, format_bytes
from core.site_master_manager import SiteMasterManager
from core.site_monitor_sync import SiteMonitorSync
from core.tcg_categories import display_name


class SettingsPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.config_manager = ConfigManager()
        self.credential_store = CredentialStore()
        self.maintenance = MaintenanceManager()
        self.log_manager = LogManager()
        self.site_manager = SiteMasterManager()
        self.site_sync = SiteMonitorSync(self.config_manager, self.site_manager)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(28, 26, 28, 26)
        outer_layout.setSpacing(14)

        title = QLabel("ポケヨヤ君設定")
        title.setObjectName("PageTitle")
        outer_layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer_layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        display_card = self._make_card("表示モード")
        display_note = QLabel(
            "かんたんモードは日常的に使う機能だけを表示します。"
            "詳細モードでは、開発者向け機能を含むすべてのメニューを表示します。"
        )
        display_note.setObjectName("MutedText")
        display_note.setWordWrap(True)
        self.ui_mode = QComboBox()
        self.ui_mode.addItem("かんたんモード", "simple")
        self.ui_mode.addItem("詳細モード", "detailed")
        display_card.layout().addWidget(display_note)
        display_card.layout().addWidget(self.ui_mode)
        layout.addWidget(display_card)

        # 監視するTCG
        games_card = self._make_card("監視するTCG")
        games_grid = QGridLayout()

        self.game_checks = {}
        for index, category in enumerate(categories(enabled_only=True)):
            checkbox = QCheckBox(category.display_name)
            self.game_checks[category.key] = checkbox
            games_grid.addWidget(checkbox, index // 2, index % 2)

        games_card.layout().addLayout(games_grid)
        layout.addWidget(games_card)

        # 監視するサイト
        sites_card = self._make_card("監視するサイト")
        site_filter_row = QHBoxLayout()
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
        site_filter_row.addWidget(self.site_tcg_filter)
        site_filter_row.addWidget(self.site_search, 1)
        site_filter_row.addWidget(enable_all)
        site_filter_row.addWidget(disable_all)
        sites_card.layout().addLayout(site_filter_row)

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
            checkbox.setEnabled(
                bool(site.get("active", True))
                and bool(site.get("monitoring_supported", False))
            )
            row_layout.addWidget(checkbox)
            row_layout.addWidget(info, 1)
            sites_card.layout().addWidget(row)
            self.site_checks[site_id] = checkbox
            self.site_rows[site_id] = (row, site)
        layout.addWidget(sites_card)

        # 基本設定
        general_card = self._make_card("基本設定")
        general_layout = general_card.layout()

        self.auto_input = QCheckBox("アカウント登録フォームへの入力補助を有効にする")
        self.new_product_fetch = QCheckBox("起動時に新弾情報を確認する")
        self.sound_enabled = QCheckBox("通知音を鳴らす")
        self.popup_enabled = QCheckBox("ポップアップ通知を表示する")
        self.auto_monitor_new_releases = QCheckBox("新弾を発売日前に自動で監視へ追加する")
        self.auto_monitor_days = QComboBox()
        for days in (7, 14, 30, 60):
            self.auto_monitor_days.addItem(f"発売{days}日前", days)
        self.show_ended_applications = QCheckBox("終了済み応募を通常表示へ含める")
        self.notify_new_sites = QCheckBox("新規店舗が追加されたら通知する")

        general_layout.addWidget(self.auto_input)
        general_layout.addWidget(self.new_product_fetch)
        general_layout.addWidget(self.sound_enabled)
        general_layout.addWidget(self.popup_enabled)
        general_layout.addWidget(self.auto_monitor_new_releases)
        general_layout.addWidget(self.auto_monitor_days)
        general_layout.addWidget(self.show_ended_applications)
        general_layout.addWidget(self.notify_new_sites)
        layout.addWidget(general_card)

        application_card = self._make_card("応募支援")
        application_note = QLabel(
            "未応募かつ受付中で、締切日時が確定している案件だけを通知します。"
        )
        application_note.setObjectName("MutedText")
        application_note.setWordWrap(True)
        self.deadline_24h = QCheckBox("締切24時間前に通知")
        self.deadline_3h = QCheckBox("締切3時間前に通知")
        self.deadline_30m = QCheckBox("締切30分前に通知")
        self.group_applications_by_product = QCheckBox("応募先を商品ごとにまとめる")
        self.notify_important_application_changes = QCheckBox("重要な変更だけ通知")
        application_card.layout().addWidget(application_note)
        application_card.layout().addWidget(self.deadline_24h)
        application_card.layout().addWidget(self.deadline_3h)
        application_card.layout().addWidget(self.deadline_30m)
        application_card.layout().addWidget(self.group_applications_by_product)
        application_card.layout().addWidget(self.notify_important_application_changes)
        layout.addWidget(application_card)

        # プロフィール
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
        layout.addWidget(profile_card)

        # 通知音
        notification_card = self._make_card("通知音")
        sound_row = QHBoxLayout()

        self.sound_path = QLineEdit()
        self.sound_path.setReadOnly(True)
        choose_sound_button = QPushButton("WAVファイルを選択")
        choose_sound_button.clicked.connect(self.choose_sound_file)

        sound_row.addWidget(self.sound_path, 1)
        sound_row.addWidget(choose_sound_button)
        notification_card.layout().addLayout(sound_row)
        layout.addWidget(notification_card)

        # メンテナンス
        maintenance_card = self._make_card("メンテナンス")
        maintenance_row = QHBoxLayout()

        self.cache_size_label = QLabel()
        self.cache_size_label.setObjectName("MutedText")

        clear_button = QPushButton("キャッシュ・ログを削除")
        clear_button.setObjectName("DangerButton")
        clear_button.clicked.connect(self.clear_cache)

        maintenance_row.addWidget(self.cache_size_label)
        maintenance_row.addStretch()
        maintenance_row.addWidget(clear_button)
        maintenance_card.layout().addLayout(maintenance_row)
        layout.addWidget(maintenance_card)

        save_row = QHBoxLayout()
        save_row.addStretch()

        save_button = QPushButton("設定を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self.save_settings)
        save_row.addWidget(save_button)

        layout.addLayout(save_row)
        layout.addStretch()

        self.load_settings()
        self.update_cache_size()

    def _make_card(self, title_text: str) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingsCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        return card

    def load_settings(self) -> None:
        config = self.config_manager.load()
        general = config["general"]
        profile = config["profile"]
        notification = config["notification"]
        games = config["games"]
        sites = config["sites"]
        assistant = config.get("application_assistant", {})

        mode_index = self.ui_mode.findData(general.get("ui_mode", "simple"))
        self.ui_mode.setCurrentIndex(max(0, mode_index))

        for key, checkbox in self.game_checks.items():
            checkbox.setChecked(bool(games.get(key, True)))

        for site_id, checkbox in self.site_checks.items():
            checkbox.setChecked(bool(sites.get(site_id, False)))

        self.auto_input.setChecked(general["auto_input_enabled"])
        self.new_product_fetch.setChecked(general["new_product_auto_fetch"])
        self.sound_enabled.setChecked(general["play_notification_sound"])
        self.popup_enabled.setChecked(general["show_popup"])
        self.auto_monitor_new_releases.setChecked(bool(general.get("auto_monitor_new_releases", True)))
        days_index = self.auto_monitor_days.findData(int(general.get("auto_monitor_days_before", 30)))
        self.auto_monitor_days.setCurrentIndex(max(0, days_index))
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
        self.notify_important_application_changes.setChecked(
            bool(assistant.get("important_changes_only", True))
        )

        self.name_input.setText(profile["name"])
        self.furigana_input.setText(profile["furigana"])
        self.email_input.setText(profile["email"])
        self.password_input.setText(self.credential_store.load_password())
        self.phone_input.setText(profile["phone"])
        self.postal_input.setText(profile["postal_code"])
        self.address_input.setText(profile["address"])
        self.sound_path.setText(notification["sound_file"])

    def save_settings(self) -> None:
        config = self.config_manager.load()
        config.update({
            "general": {
                "ui_mode": str(self.ui_mode.currentData() or "simple"),
                "auto_input_enabled": self.auto_input.isChecked(),
                "new_product_auto_fetch": self.new_product_fetch.isChecked(),
                "play_notification_sound": self.sound_enabled.isChecked(),
                "show_popup": self.popup_enabled.isChecked(),
                "auto_monitor_new_releases": self.auto_monitor_new_releases.isChecked(),
                "auto_monitor_days_before": int(self.auto_monitor_days.currentData()),
                "show_ended_applications": self.show_ended_applications.isChecked(),
                "notify_new_monitoring_sites": self.notify_new_sites.isChecked(),
            },
            "profile": {
                "name": self.name_input.text().strip(),
                "furigana": self.furigana_input.text().strip(),
                "email": self.email_input.text().strip(),
                "phone": self.phone_input.text().strip(),
                "postal_code": self.postal_input.text().strip(),
                "address": self.address_input.text().strip(),
            },
            "notification": {
                "sound_file": self.sound_path.text().strip(),
            },
            "games": {
                key: checkbox.isChecked()
                for key, checkbox in self.game_checks.items()
            },
            "sites": {key: checkbox.isChecked() for key, checkbox in self.site_checks.items()},
            "application_assistant": {
                "deadline_reminders_enabled": any((
                    self.deadline_24h.isChecked(),
                    self.deadline_3h.isChecked(),
                    self.deadline_30m.isChecked(),
                )),
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
            QMessageBox.critical(
                self,
                "保存エラー",
                f"設定を保存できませんでした。\n\n{error}",
            )
            return

        self.log_manager.write("設定ソフトから設定を保存しました。")
        QMessageBox.information(self, "保存完了", "設定を保存しました。")

    def _filter_sites(self, *_args) -> None:
        tcg_key = str(self.site_tcg_filter.currentData() or "all")
        keyword = self.site_search.text().strip().casefold()
        for site_id, (row, site) in self.site_rows.items():
            tcg_ok = tcg_key == "all" or tcg_key in site.get("tcg_keys", [])
            text_ok = not keyword or keyword in str(site.get("name", site_id)).casefold()
            row.setVisible(tcg_ok and text_ok)

    def _set_visible_sites(self, enabled: bool) -> None:
        for site_id, checkbox in self.site_checks.items():
            row, site = self.site_rows[site_id]
            if (
                row.isVisible()
                and bool(site.get("active", True))
                and bool(site.get("monitoring_supported", False))
            ):
                checkbox.setChecked(enabled)

    def choose_sound_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "通知音を選択",
            "",
            "WAVファイル (*.wav);;すべてのファイル (*.*)",
        )

        if file_path:
            self.sound_path.setText(file_path)

    def update_cache_size(self) -> None:
        size = self.maintenance.calculate_size()
        self.cache_size_label.setText(
            f"現在のキャッシュ・ログ容量：{format_bytes(size)}"
        )

    def clear_cache(self) -> None:
        answer = QMessageBox.question(
            self,
            "キャッシュ削除",
            "tempフォルダとlogsフォルダの中身を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        removed_files, removed_bytes = self.maintenance.clear()
        self.update_cache_size()

        QMessageBox.information(
            self,
            "削除完了",
            f"{removed_files}個のファイルを削除しました。\n"
            f"削除容量：{format_bytes(removed_bytes)}",
        )

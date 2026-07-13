from PySide6.QtWidgets import (
    QCheckBox,
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
from core.credential_store import CredentialStore
from core.log_manager import LogManager
from core.maintenance import MaintenanceManager, format_bytes


class SettingsPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.config_manager = ConfigManager()
        self.credential_store = CredentialStore()
        self.maintenance = MaintenanceManager()
        self.log_manager = LogManager()

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

        # 監視するTCG
        games_card = self._make_card("監視するTCG")
        games_grid = QGridLayout()

        self.game_pokemon = QCheckBox("ポケモンカード")
        self.game_onepiece = QCheckBox("ONE PIECEカードゲーム")
        self.game_gundam = QCheckBox("ガンダムカードゲーム")

        games_grid.addWidget(self.game_pokemon, 0, 0)
        games_grid.addWidget(self.game_onepiece, 0, 1)
        games_grid.addWidget(self.game_gundam, 1, 0)

        games_card.layout().addLayout(games_grid)
        layout.addWidget(games_card)

        # 監視するサイト
        sites_card = self._make_card("監視するサイト")
        sites_grid = QGridLayout()

        self.site_pokemon_center = QCheckBox("ポケモンセンターオンライン")
        self.site_amazon = QCheckBox("Amazon")
        self.site_rakuten = QCheckBox("楽天")
        self.site_yodobashi = QCheckBox("ヨドバシ")
        self.site_biccamera = QCheckBox("ビックカメラ")
        self.site_amiami = QCheckBox("あみあみ")

        site_widgets = [
            self.site_pokemon_center,
            self.site_amazon,
            self.site_rakuten,
            self.site_yodobashi,
            self.site_biccamera,
            self.site_amiami,
        ]

        for index, widget in enumerate(site_widgets):
            sites_grid.addWidget(widget, index // 2, index % 2)

        sites_card.layout().addLayout(sites_grid)
        layout.addWidget(sites_card)

        # 基本設定
        general_card = self._make_card("基本設定")
        general_layout = general_card.layout()

        self.auto_input = QCheckBox("アカウント登録フォームへの入力補助を有効にする")
        self.new_product_fetch = QCheckBox("起動時に新弾情報を確認する")
        self.sound_enabled = QCheckBox("通知音を鳴らす")
        self.popup_enabled = QCheckBox("ポップアップ通知を表示する")

        general_layout.addWidget(self.auto_input)
        general_layout.addWidget(self.new_product_fetch)
        general_layout.addWidget(self.sound_enabled)
        general_layout.addWidget(self.popup_enabled)
        layout.addWidget(general_card)

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

        self.game_pokemon.setChecked(games["pokemon"])
        self.game_onepiece.setChecked(games["onepiece"])
        self.game_gundam.setChecked(games["gundam"])

        self.site_pokemon_center.setChecked(sites["pokemon_center"])
        self.site_amazon.setChecked(sites["amazon"])
        self.site_rakuten.setChecked(sites["rakuten"])
        self.site_yodobashi.setChecked(sites["yodobashi"])
        self.site_biccamera.setChecked(sites["biccamera"])
        self.site_amiami.setChecked(sites["amiami"])

        self.auto_input.setChecked(general["auto_input_enabled"])
        self.new_product_fetch.setChecked(general["new_product_auto_fetch"])
        self.sound_enabled.setChecked(general["play_notification_sound"])
        self.popup_enabled.setChecked(general["show_popup"])

        self.name_input.setText(profile["name"])
        self.furigana_input.setText(profile["furigana"])
        self.email_input.setText(profile["email"])
        self.password_input.setText(self.credential_store.load_password())
        self.phone_input.setText(profile["phone"])
        self.postal_input.setText(profile["postal_code"])
        self.address_input.setText(profile["address"])
        self.sound_path.setText(notification["sound_file"])

    def save_settings(self) -> None:
        config = {
            "general": {
                "auto_input_enabled": self.auto_input.isChecked(),
                "new_product_auto_fetch": self.new_product_fetch.isChecked(),
                "play_notification_sound": self.sound_enabled.isChecked(),
                "show_popup": self.popup_enabled.isChecked(),
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
                "pokemon": self.game_pokemon.isChecked(),
                "onepiece": self.game_onepiece.isChecked(),
                "gundam": self.game_gundam.isChecked(),
            },
            "sites": {
                "pokemon_center": self.site_pokemon_center.isChecked(),
                "amazon": self.site_amazon.isChecked(),
                "rakuten": self.site_rakuten.isChecked(),
                "yodobashi": self.site_yodobashi.isChecked(),
                "biccamera": self.site_biccamera.isChecked(),
                "amiami": self.site_amiami.isChecked(),
            },
        }

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

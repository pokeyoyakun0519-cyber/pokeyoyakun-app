import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.site_master_manager import SiteMasterManager
from core.site_monitor_sync import SiteMonitorSync


SALES_TYPES = [
    "通常販売",
    "抽選販売",
    "先着販売",
    "招待販売",
    "抽選・通常販売",
    "通常販売・招待販売",
    "その他",
]


class SiteEditorCard(QFrame):
    def __init__(self, site: dict, save_callback, delete_callback):
        super().__init__()
        self.site = site
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()

        title = QLabel(site.get("name", "名称未設定"))
        title.setObjectName("ProductName")

        self.enabled = QCheckBox("有効")
        self.enabled.setChecked(bool(site.get("enabled", True)))

        save_button = QPushButton("保存")
        save_button.setObjectName("AccentButton")

        delete_button = QPushButton("削除")
        delete_button.setObjectName("DangerButton")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.enabled)
        header.addWidget(save_button)
        header.addWidget(delete_button)

        form = QFormLayout()

        self.name_input = QLineEdit(site.get("name", ""))
        self.url_input = QLineEdit(site.get("site_url", ""))
        self.tcg_input = QLineEdit(",".join(site.get("tcg_keys", ["other"])))
        self.method_input = QLineEdit(site.get("application_method", "Web"))

        self.sales_type = QComboBox()
        self.sales_type.addItems(SALES_TYPES)
        current_type = site.get("sales_type", "通常販売")
        if current_type in SALES_TYPES:
            self.sales_type.setCurrentText(current_type)

        self.purchase_history_required = QCheckBox("購入履歴が必要")
        self.purchase_history_required.setChecked(
            bool(site.get("purchase_history_required", False))
        )

        self.membership_required = QCheckBox("会員登録が必要")
        self.membership_required.setChecked(
            bool(site.get("membership_required", False))
        )

        self.notes = QTextEdit()
        self.notes.setPlainText(site.get("notes", ""))
        self.notes.setFixedHeight(80)

        form.addRow("サイト名", self.name_input)
        form.addRow("店舗URL（HTTPS）", self.url_input)
        form.addRow("対象TCGキー", self.tcg_input)
        form.addRow("対応方式", self.method_input)
        form.addRow("販売方式", self.sales_type)
        form.addRow("", self.purchase_history_required)
        form.addRow("", self.membership_required)
        form.addRow("注意事項", self.notes)

        save_button.clicked.connect(
            lambda: save_callback(
                site.get("id", ""),
                {
                    "id": site.get("id", ""),
                    "name": self.name_input.text().strip() or "名称未設定",
                    "enabled": self.enabled.isChecked(),
                    "active": bool(site.get("active", True)),
                    "site_url": self.url_input.text().strip(),
                    "tcg_keys": [value.strip() for value in self.tcg_input.text().split(",") if value.strip()],
                    "application_method": self.method_input.text().strip() or "Web",
                    "sales_type": self.sales_type.currentText(),
                    "purchase_history_required": self.purchase_history_required.isChecked(),
                    "membership_required": self.membership_required.isChecked(),
                    "notes": self.notes.toPlainText().strip(),
                },
            )
        )

        delete_button.clicked.connect(
            lambda: delete_callback(site.get("id", ""))
        )

        layout.addLayout(header)
        layout.addLayout(form)


class SiteMasterPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.manager = SiteMasterManager()
        self.site_sync = SiteMonitorSync(site_manager=self.manager)
        self.log_manager = LogManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("サイトマスター")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "販売サイトごとの共通条件を管理します。"
            "ここで登録した注意事項や販売方式は、将来の商品詳細画面で共通表示に使います。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        add_card = QFrame()
        add_card.setObjectName("SettingsCard")
        add_layout = QVBoxLayout(add_card)

        add_title = QLabel("新しいサイトを追加")
        add_title.setObjectName("SectionTitle")

        add_row = QHBoxLayout()

        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("例：Joshin")

        self.new_sales_type = QComboBox()
        self.new_sales_type.addItems(SALES_TYPES)

        add_button = QPushButton("サイトを追加")
        add_button.setObjectName("AccentButton")
        add_button.clicked.connect(self.add_site)

        add_row.addWidget(self.new_name, 2)
        add_row.addWidget(self.new_sales_type, 1)
        add_row.addWidget(add_button)

        add_layout.addWidget(add_title)
        add_layout.addLayout(add_row)
        layout.addWidget(add_card)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload_sites()

    def add_site(self) -> None:
        name = self.new_name.text().strip()

        if not name:
            QMessageBox.warning(
                self,
                "サイト名が空です",
                "追加するサイト名を入力してください。",
            )
            return

        site_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if not site_id:
            site_id = f"site_{len(self.manager.load_sites()) + 1}"

        existing_ids = {
            site.get("id")
            for site in self.manager.load_sites()
        }
        original_id = site_id
        counter = 2

        while site_id in existing_ids:
            site_id = f"{original_id}_{counter}"
            counter += 1

        site = {
            "id": site_id,
            "name": name,
            "enabled": True,
            "active": True,
            "site_url": "",
            "tcg_keys": ["other"],
            "application_method": "Web",
            "sales_type": self.new_sales_type.currentText(),
            "purchase_history_required": False,
            "membership_required": False,
            "notes": "",
        }

        self.manager.add_site(site)
        self.site_sync.sync()
        self.log_manager.write(f"サイトマスターへ追加しました: {name}")

        self.new_name.clear()
        self.reload_sites()

    def save_site(self, site_id: str, updated: dict) -> None:
        self.manager.update_site(site_id, updated)
        self.site_sync.sync()
        self.log_manager.write(
            f"サイトマスターを更新しました: {updated.get('name')}"
        )
        QMessageBox.information(
            self,
            "保存完了",
            "サイト情報を保存しました。",
        )
        self.reload_sites()

    def delete_site(self, site_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "サイト削除",
            "このサイトを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.manager.delete_site(site_id)
            self.site_sync.sync()
            self.log_manager.write(
                f"サイトマスターから削除しました: {site_id}"
            )
            self.reload_sites()

    def reload_sites(self) -> None:
        sites = self.manager.load_sites()

        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        for site in sites:
            list_layout.addWidget(
                SiteEditorCard(
                    site,
                    self.save_site,
                    self.delete_site,
                )
            )

        list_layout.addStretch()
        self.scroll.setWidget(container)

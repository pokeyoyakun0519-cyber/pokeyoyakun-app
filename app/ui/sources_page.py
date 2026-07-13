import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.notification_manager import NotificationManager
from core.source_manager import SourceManager


class SourceEditDialog(QDialog):
    def __init__(
        self,
        source: dict,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "公式情報ソースを編集"
        )
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(
            str(source.get("name", ""))
        )
        self.url = QLineEdit(
            str(source.get("url", ""))
        )

        form.addRow("名前", self.name)
        form.addRow("URL", self.url)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save
            | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(
            self.accept
        )
        buttons.rejected.connect(
            self.reject
        )
        layout.addWidget(buttons)


class SourceCard(QFrame):
    def __init__(
        self,
        source: dict,
        edit_callback,
        toggle_callback,
        remove_callback,
    ):
        super().__init__()
        self.source = source
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        layout.setSpacing(8)

        header = QHBoxLayout()

        name = QLabel(
            source.get(
                "name",
                "名称未設定",
            )
        )
        name.setObjectName("ProductName")

        enabled = bool(
            source.get("enabled", True)
        )
        enabled_label = QLabel(
            "有効" if enabled else "無効"
        )
        enabled_label.setObjectName(
            "StatusOpen"
            if enabled
            else "StatusClosed"
        )

        status = QLabel(
            str(
                source.get(
                    "last_status",
                    "未確認",
                )
            )
        )
        status.setObjectName("StatusOther")

        open_button = QPushButton(
            "ページを開く"
        )
        open_button.clicked.connect(
            lambda: webbrowser.open(
                source.get("url", "")
            )
        )

        edit_button = QPushButton("編集")
        edit_button.clicked.connect(
            lambda: edit_callback(source)
        )

        toggle_button = QPushButton(
            "無効化"
            if enabled
            else "有効化"
        )
        toggle_button.clicked.connect(
            lambda: toggle_callback(source)
        )

        remove_button = QPushButton("削除")
        remove_button.setObjectName(
            "DangerButton"
        )
        remove_button.clicked.connect(
            lambda: remove_callback(
                source.get("id", "")
            )
        )

        header.addWidget(name)
        header.addStretch()
        header.addWidget(enabled_label)
        header.addWidget(status)
        header.addWidget(open_button)
        header.addWidget(edit_button)
        header.addWidget(toggle_button)
        header.addWidget(remove_button)

        url_label = QLabel(
            source.get("url", "")
        )
        url_label.setObjectName("MutedText")
        url_label.setWordWrap(True)

        checked = QLabel(
            "最終確認："
            + (
                source.get("last_checked")
                or "未確認"
            )
        )
        checked.setObjectName("MutedText")

        layout.addLayout(header)
        layout.addWidget(url_label)
        layout.addWidget(checked)


class SourcesPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.source_manager = SourceManager()
        self.log_manager = LogManager()
        self.notification_manager = (
            NotificationManager()
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("公式情報ソース")
        title.setObjectName("PageTitle")

        check_button = QPushButton(
            "登録ページを手動確認"
        )
        check_button.setObjectName(
            "AccentButton"
        )
        check_button.clicked.connect(
            self.check_sources
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(check_button)
        layout.addLayout(header)

        description = QLabel(
            "追加した公式情報ソースは、"
            "編集・無効化・再有効化・削除ができます。"
            "無効化したソースは自動監視と手動確認の対象外になります。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        add_card = QFrame()
        add_card.setObjectName(
            "SettingsCard"
        )
        add_layout = QVBoxLayout(add_card)

        add_title = QLabel(
            "新しい情報ソースを登録"
        )
        add_title.setObjectName(
            "SectionTitle"
        )

        fields = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(
            "例：ポケモンカード公式"
        )
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "https:// から始まるURL"
        )
        add_button = QPushButton("登録")
        add_button.clicked.connect(
            self.add_source
        )

        fields.addWidget(
            self.name_input,
            1,
        )
        fields.addWidget(
            self.url_input,
            2,
        )
        fields.addWidget(add_button)

        add_layout.addWidget(add_title)
        add_layout.addLayout(fields)
        layout.addWidget(add_card)

        self.result_label = QLabel("")
        self.result_label.setObjectName(
            "MutedText"
        )
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(
            QFrame.NoFrame
        )
        layout.addWidget(self.scroll, 1)

        self.reload_sources()

    def add_source(self) -> None:
        name = self.name_input.text().strip()
        url = self.url_input.text().strip()

        if not url.lower().startswith(
            ("http://", "https://")
        ):
            QMessageBox.warning(
                self,
                "URLを確認してください",
                "http:// または https:// から始まるURLを入力してください。",
            )
            return

        self.source_manager.add_source(
            name,
            url,
        )
        self.name_input.clear()
        self.url_input.clear()
        self.reload_sources()

    def edit_source(
        self,
        source: dict,
    ) -> None:
        dialog = SourceEditDialog(
            source,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        url = dialog.url.text().strip()
        if not url.lower().startswith(
            ("http://", "https://")
        ):
            QMessageBox.warning(
                self,
                "URLを確認してください",
                "http:// または https:// から始まるURLを入力してください。",
            )
            return

        self.source_manager.update_source(
            str(source.get("id", "")),
            dialog.name.text(),
            url,
        )
        self.reload_sources()

    def toggle_source(
        self,
        source: dict,
    ) -> None:
        enabled = bool(
            source.get("enabled", True)
        )
        action = (
            "無効化"
            if enabled
            else "有効化"
        )
        answer = QMessageBox.question(
            self,
            f"情報ソースを{action}",
            f'「{source.get("name", "")}」を{action}しますか？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.source_manager.set_enabled(
            str(source.get("id", "")),
            not enabled,
        )
        self.reload_sources()

    def remove_source(
        self,
        source_id: str,
    ) -> None:
        answer = QMessageBox.question(
            self,
            "情報ソースを削除",
            "この情報ソースを完全に削除しますか？\n"
            "過去に取得した商品・履歴は削除しません。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.source_manager.remove_source(
            source_id
        )
        self.reload_sources()

    def check_sources(self) -> None:
        sources = [
            source
            for source in self.source_manager.load_sources()
            if source.get("enabled", True)
        ]

        if not sources:
            QMessageBox.information(
                self,
                "有効な情報ソースなし",
                "確認対象の情報ソースがありません。",
            )
            return

        checked, changed = (
            self.source_manager.check_all()
        )
        self.result_label.setText(
            f"{len(sources)}件を確認し、"
            f"{len(changed)}件で変更または商品追加がありました。"
        )
        self.reload_sources()

    def reload_sources(self) -> None:
        sources = (
            self.source_manager
            .load_sources()
        )

        container = QWidget()
        list_layout = QVBoxLayout(
            container
        )
        list_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        list_layout.setSpacing(12)

        if not sources:
            empty = QLabel(
                "情報ソースはまだ登録されていません。"
            )
            empty.setAlignment(
                Qt.AlignCenter
            )
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        else:
            for source in sources:
                list_layout.addWidget(
                    SourceCard(
                        source,
                        self.edit_source,
                        self.toggle_source,
                        self.remove_source,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

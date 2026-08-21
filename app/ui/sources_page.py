import webbrowser

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.notification_manager import NotificationManager
from core.source_manager import SourceManager
from core.tcg_categories import categories, display_name
from core.x_monitoring_status import XMonitoringStatus


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
        self.tcg = QComboBox()
        for category in categories(enabled_only=True):
            self.tcg.addItem(category.display_name, category.key)
        index = self.tcg.findData(source.get("tcg_key", "other"))
        self.tcg.setCurrentIndex(max(0, index))

        form.addRow("名前", self.name)
        form.addRow("URL", self.url)
        form.addRow("TCG", self.tcg)
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
        check_callback,
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
            f'{display_name(source.get("tcg_key"), source.get("tcg"))} ｜ '
            + source.get(
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

        state = str(source.get("check_state", "")).strip().lower()
        if not state:
            last_status = str(source.get("last_status", "未確認"))
            if last_status.startswith(("確認失敗", "接続失敗", "HTTPエラー")):
                state = "error"
            elif last_status.startswith("確認成功"):
                state = "checked"
            else:
                state = "unchecked"
        status_labels = {
            "checked": ("🟢 確認済み", "StatusOpen"),
            "checking": ("🟡 確認中", "StatusOther"),
            "error": ("🔴 エラー", "StatusClosed"),
            "unchecked": ("⚪ 未確認", "StatusOther"),
        }
        status_text, status_object = status_labels.get(
            state, status_labels["unchecked"]
        )
        status = QLabel(status_text)
        status.setObjectName(status_object)

        open_button = QPushButton(
            "ページを開く"
        )
        open_button.clicked.connect(
            lambda: webbrowser.open(
                source.get("url", "")
            )
        )

        check_button = QPushButton("確認")
        check_button.setObjectName("AccentButton")
        check_button.setEnabled(enabled and state != "checking")
        check_button.clicked.connect(lambda: check_callback(source))

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
        header.addWidget(check_button)
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

        detail = QLabel(str(source.get("last_status", "未確認")))
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(url_label)
        layout.addWidget(detail)
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
        self._checking = False
        self._check_queue: list[str] = []
        self._check_total = 0
        self._check_done = 0
        self._check_changed = 0

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

        self.check_all_button = QPushButton(
            "すべて確認"
        )
        self.check_all_button.setObjectName(
            "AccentButton"
        )
        self.check_all_button.clicked.connect(
            self.check_sources
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.check_all_button)
        layout.addLayout(header)

        description = QLabel(
            "追加した公式情報ソースは、"
            "編集・無効化・再有効化・削除ができます。"
            "無効化したソースは自動監視と手動確認の対象外になります。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        x_card = QFrame()
        x_card.setObjectName("SettingsCard")
        x_layout = QVBoxLayout(x_card)
        x_title = QLabel("X信頼アカウント監視")
        x_title.setObjectName("SectionTitle")
        self.x_monitoring_summary = QLabel("")
        self.x_monitoring_summary.setObjectName("MutedText")
        self.x_monitoring_summary.setWordWrap(True)
        x_layout.addWidget(x_title)
        x_layout.addWidget(self.x_monitoring_summary)
        layout.addWidget(x_card)

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
        self.tcg_input = QComboBox()
        for category in categories(enabled_only=True):
            self.tcg_input.addItem(category.display_name, category.key)
        add_button = QPushButton("登録")
        add_button.clicked.connect(
            self.add_source
        )
        yugioh_button = QPushButton("遊戯王OCG公式を入力")
        yugioh_button.clicked.connect(self.fill_yugioh_official_source)

        fields.addWidget(
            self.name_input,
            1,
        )
        fields.addWidget(
            self.url_input,
            2,
        )
        fields.addWidget(self.tcg_input)
        fields.addWidget(yugioh_button)
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

    def fill_yugioh_official_source(self) -> None:
        """公式ソースの値を入力する。登録は利用者が明示的に行う。"""
        self.name_input.setText("遊戯王OCG公式 商品情報")
        self.url_input.setText(SourceManager.YUGIOH_OFFICIAL_PRODUCTS_URL)
        index = self.tcg_input.findData("yugioh")
        if index >= 0:
            self.tcg_input.setCurrentIndex(index)

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
            str(self.tcg_input.currentData()),
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
            str(dialog.tcg.currentData()),
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

        self._start_checks([
            str(source.get("id", ""))
            for source in sources
        ])

    def check_source(self, source: dict) -> None:
        if not source.get("enabled", True):
            return
        self._start_checks([str(source.get("id", ""))])

    def _start_checks(self, source_ids: list[str]) -> None:
        if self._checking:
            self.result_label.setText("確認処理中です。完了までお待ちください。")
            return
        self._check_queue = [source_id for source_id in source_ids if source_id]
        if not self._check_queue:
            return
        self._checking = True
        self._check_total = len(self._check_queue)
        self._check_done = 0
        self._check_changed = 0
        self.check_all_button.setEnabled(False)
        self._prepare_next_check()

    def _prepare_next_check(self) -> None:
        if not self._check_queue:
            self._finish_checks()
            return
        source_id = self._check_queue[0]
        sources = self.source_manager.load_sources()
        source = next(
            (
                item for item in sources
                if str(item.get("id", "")) == source_id
            ),
            {},
        )
        self.source_manager.mark_checking(source_id)
        self.result_label.setText(
            f"確認中 {self._check_done + 1}/{self._check_total}："
            f"{source.get('name', '公式情報ソース')}"
        )
        self.reload_sources()
        QApplication.processEvents()
        QTimer.singleShot(0, self._execute_next_check)

    def _execute_next_check(self) -> None:
        if not self._check_queue:
            self._finish_checks()
            return
        source_id = self._check_queue.pop(0)
        _source, changed = self.source_manager.check_source(source_id)
        self._check_done += 1
        if changed:
            self._check_changed += 1
        self.reload_sources()
        self._prepare_next_check()

    def _finish_checks(self) -> None:
        self._checking = False
        self.check_all_button.setEnabled(True)
        self.result_label.setText(
            f"{self._check_done}件の確認が完了しました。"
            f"{self._check_changed}件で変更または商品追加がありました。"
        )
        self.reload_sources()

    def reload_sources(self) -> None:
        self._reload_x_monitoring()
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
                        self.check_source,
                        self.toggle_source,
                        self.remove_source,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

    def _reload_x_monitoring(self) -> None:
        monitor = XMonitoringStatus()
        summary = monitor.summary()
        lines = [
            f'X情報 最終更新: {summary.get("last_success") or "未取得"}  /  '
            f'状態: {summary.get("state", "未設定")}',
            summary.get("message", ""),
        ]
        for item in monitor.rows():
            lines.append(
                f'{item.get("tcg", "other")}  @{item.get("username", "")}  '
                f'{item.get("trust_level", "INFO_ACCOUNT")}  '
                f'{"有効" if item.get("enabled", True) else "無効"}  '
                f'最終取得:{item.get("last_fetch") or "未取得"}  '
                f'最終検知:{item.get("last_post_detected") or "未検知"}  '
                f'candidate:{item.get("candidate_count", 0)}  '
                f'confirmed:{item.get("confirmed_count", 0)}  '
                f'error:{item.get("error") or "なし"}'
            )
        self.x_monitoring_summary.setText("\n".join(lines) or "監視アカウント未設定")

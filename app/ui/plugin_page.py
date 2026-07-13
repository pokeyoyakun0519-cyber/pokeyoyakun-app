import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.plugin_manager import PluginManager
from core.retail_plugin_loader import RetailPluginLoader
from core.retail_plugin_registry import (
    load_all_retail_plugins,
)
from core.retail_plugin_state import RetailPluginState


class PluginPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.manager = PluginManager()
        self.retail_loader = RetailPluginLoader()
        self.retail_state = RetailPluginState()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("プラグイン管理")
        title.setObjectName("PageTitle")

        example_button = QPushButton(
            "サンプルJSONを作成"
        )
        example_button.clicked.connect(
            self.create_example
        )

        folder_button = QPushButton(
            "JSONプラグインフォルダーを開く"
        )
        folder_button.clicked.connect(
            self.open_retail_plugin_folder
        )

        refresh_button = QPushButton("再スキャン")
        refresh_button.setObjectName(
            "AccentButton"
        )
        refresh_button.clicked.connect(
            self.reload_plugins
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(example_button)
        header.addWidget(folder_button)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        description = QLabel(
            "組み込み店舗は無効化・再有効化できます。"
            "外部JSON店舗は無効化に加えて、"
            "確認後にJSONファイルごと削除できます。"
            "応募履歴や過去の結果データは削除しません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.summary = QLabel("")
        self.summary.setObjectName("MutedText")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload_plugins()

    def reload_plugins(self) -> None:
        python_plugins = (
            self.manager.discover_plugins()
        )
        retail_plugins, messages = (
            load_all_retail_plugins()
        )

        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        list_layout.setSpacing(12)

        python_title = QLabel(
            "Pythonサイトプラグイン"
        )
        python_title.setObjectName("SectionTitle")
        list_layout.addWidget(python_title)

        for plugin in python_plugins:
            list_layout.addWidget(
                self._make_python_card(plugin)
            )

        retail_title = QLabel(
            "店舗検索JSONプラグイン"
        )
        retail_title.setObjectName("SectionTitle")
        list_layout.addWidget(retail_title)

        external_count = 0
        enabled_count = 0

        for plugin in retail_plugins:
            if (
                plugin.get("source")
                == "external_json"
            ):
                external_count += 1
            if plugin.get("enabled", True):
                enabled_count += 1

            list_layout.addWidget(
                self._make_retail_card(plugin)
            )

        if messages:
            label = QLabel(
                "\n".join(messages[-10:])
            )
            label.setObjectName("MutedText")
            label.setWordWrap(True)
            list_layout.addWidget(label)

        list_layout.addStretch()
        self.scroll.setWidget(container)

        self.summary.setText(
            f"Python：{len(python_plugins)}件　"
            f"店舗定義：{len(retail_plugins)}件　"
            f"外部JSON：{external_count}件　"
            f"有効：{enabled_count}件"
        )

    def create_example(self) -> None:
        path = (
            self.retail_loader
            .write_example_plugin()
        )
        self.summary.setText(
            f"サンプルを作成しました：{path}"
        )
        self.reload_plugins()

    def open_retail_plugin_folder(self) -> None:
        folder = self.retail_loader.plugin_dir
        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        if sys.platform.startswith("win"):
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(folder)]
            )
        else:
            subprocess.Popen(
                ["xdg-open", str(folder)]
            )

    def _toggle_retail_plugin(
        self,
        plugin: dict,
    ) -> None:
        plugin_id = str(
            plugin.get("id", "")
        )
        currently_enabled = bool(
            plugin.get("enabled", True)
        )
        action = (
            "無効化"
            if currently_enabled
            else "再有効化"
        )

        answer = QMessageBox.question(
            self,
            f"店舗プラグインを{action}",
            f'「{plugin.get("name", "")}」を'
            f"{action}しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.retail_state.set_enabled(
            plugin_id,
            not currently_enabled,
        )
        self.reload_plugins()

    def _delete_retail_plugin(
        self,
        plugin: dict,
    ) -> None:
        if (
            plugin.get("source")
            != "external_json"
        ):
            return

        source_file = str(
            plugin.get(
                "source_file",
                "",
            )
        )
        if not source_file:
            QMessageBox.warning(
                self,
                "削除できません",
                "元のJSONファイルが特定できません。",
            )
            return

        answer = QMessageBox.question(
            self,
            "外部店舗プラグインを削除",
            f'「{plugin.get("name", "")}」を'
            "JSONファイルごと削除しますか？\n\n"
            "応募履歴や過去の結果は残ります。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = (
            self.retail_loader
            .delete_external_plugin(
                source_file
            )
        )

        if not deleted:
            QMessageBox.warning(
                self,
                "削除失敗",
                "JSONファイルを削除できませんでした。",
            )
            return

        self.retail_state.set_enabled(
            str(plugin.get("id", "")),
            True,
        )
        self.reload_plugins()

    def _make_retail_card(
        self,
        plugin: dict,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("ProductCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        layout.setSpacing(8)

        header = QHBoxLayout()

        name = QLabel(
            str(plugin.get("name", "名称未設定"))
        )
        name.setObjectName("ProductName")

        source = str(
            plugin.get("source", "builtin")
        )
        source_label = QLabel(
            "外部JSON"
            if source == "external_json"
            else "組み込み"
        )
        source_label.setObjectName(
            "StatusLottery"
            if source == "external_json"
            else "StatusOther"
        )

        enabled = bool(
            plugin.get("enabled", True)
        )
        status_label = QLabel(
            "有効" if enabled else "無効"
        )
        status_label.setObjectName(
            "StatusOpen"
            if enabled
            else "StatusClosed"
        )

        toggle_button = QPushButton(
            "無効化"
            if enabled
            else "再有効化"
        )
        toggle_button.clicked.connect(
            lambda checked=False, item=dict(plugin):
            self._toggle_retail_plugin(item)
        )

        header.addWidget(name)
        header.addStretch()
        header.addWidget(source_label)
        header.addWidget(status_label)
        header.addWidget(toggle_button)

        if source == "external_json":
            delete_button = QPushButton("削除")
            delete_button.setObjectName(
                "DangerButton"
            )
            delete_button.clicked.connect(
                lambda checked=False, item=dict(plugin):
                self._delete_retail_plugin(item)
            )
            header.addWidget(delete_button)

        details = QLabel(
            f'ID：{plugin.get("id", "")}\n'
            f'バージョン：{plugin.get("plugin_version", "")}\n'
            f'配布元：{plugin.get("publisher", "")}\n'
            f'方式：{plugin.get("mode", "")}\n'
            f'TCG：{", ".join(plugin.get("tcg", []))}\n'
            f'地域：{", ".join(plugin.get("regions", []))}\n'
            f'ファイル：{plugin.get("source_file", "組み込み")}'
        )
        details.setObjectName("MutedText")
        details.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(details)
        return card

    @staticmethod
    def _make_python_card(plugin) -> QFrame:
        card = QFrame()
        card.setObjectName("ProductCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )

        title = QLabel(plugin.display_name)
        title.setObjectName("ProductName")
        details = QLabel(
            f"ID：{plugin.plugin_id}\n"
            f"状態：{plugin.status}\n"
            f"モジュール：{plugin.module_name}\n"
            f"メッセージ：{plugin.message}"
        )
        details.setObjectName("MutedText")
        details.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(details)
        return card

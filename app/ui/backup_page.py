from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.backup_manager import BackupManager
from core.log_manager import LogManager
from ui.design_system import busy_button


class BackupPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.manager = BackupManager()
        self.log_manager = LogManager()
        self.backup_paths = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("バックアップ")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "設定・商品データ・ログを保存します。"
            "通常バックアップは最新10世代を自動保持します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        buttons = QHBoxLayout()

        self.create_button = QPushButton("今すぐバックアップ")
        self.create_button.setObjectName("AccentButton")
        self.create_button.clicked.connect(self.create_backup)

        refresh_button = QPushButton("一覧を更新")
        refresh_button.clicked.connect(self.reload_backups)

        restore_button = QPushButton("選択したバックアップを復元")
        restore_button.clicked.connect(self.restore_selected)

        export_button = QPushButton("選択項目をZIP出力")
        export_button.clicked.connect(self.export_selected)

        delete_button = QPushButton("選択したバックアップを削除")
        delete_button.setObjectName("DangerButton")
        delete_button.clicked.connect(self.delete_selected)

        buttons.addWidget(self.create_button)
        buttons.addWidget(refresh_button)
        buttons.addWidget(restore_button)
        buttons.addWidget(export_button)
        buttons.addWidget(delete_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedText")
        layout.addWidget(self.status_label)

        self.reload_backups()

    def create_backup(self):
        with busy_button(self.create_button, "バックアップ中…"):
            path = self.manager.create_backup("manual")
        self.log_manager.write(
            f"手動バックアップを作成しました: {path.name}"
        )
        self.status_label.setText(
            f"バックアップを作成しました: {path.name}"
        )
        self.status_label.setProperty("state", "success")
        self.reload_backups()

    def reload_backups(self):
        self.backup_paths = self.manager.list_backups()
        self.list_widget.clear()

        for path in self.backup_paths:
            self.list_widget.addItem(path.name)

        self.status_label.setText(
            f"バックアップ数: {len(self.backup_paths)} "
            f"（自動保持上限: {self.manager.KEEP_GENERATIONS}世代）"
        )

    def _selected_path(self):
        row = self.list_widget.currentRow()

        if row < 0 or row >= len(self.backup_paths):
            QMessageBox.information(
                self,
                "未選択",
                "バックアップを選択してください。",
            )
            return None

        return self.backup_paths[row]

    def restore_selected(self):
        path = self._selected_path()
        if path is None:
            return

        answer = QMessageBox.question(
            self,
            "バックアップを復元",
            "現在の設定・商品データ・ログを上書きします。\n"
            "復元を続けますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.manager.restore_backup(path)
        self.log_manager.write(
            f"バックアップを復元しました: {path.name}"
        )
        QMessageBox.information(
            self,
            "復元完了",
            "バックアップを復元しました。\n"
            "アプリを再起動してください。",
        )

    def export_selected(self):
        path = self._selected_path()
        if path is None:
            return

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "バックアップZIPを保存",
            f"{path.name}.zip",
            "ZIPファイル (*.zip)",
        )

        if not destination:
            return

        if not destination.lower().endswith(".zip"):
            destination += ".zip"

        try:
            result = self.manager.export_backup_zip(
                path,
                Path(destination),
            )
        except Exception as error:
            QMessageBox.critical(
                self,
                "ZIP作成失敗",
                str(error),
            )
            return

        QMessageBox.information(
            self,
            "ZIP作成完了",
            f"バックアップを書き出しました。\n\n{result}",
        )

    def delete_selected(self):
        path = self._selected_path()
        if path is None:
            return

        answer = QMessageBox.question(
            self,
            "バックアップ削除",
            f"{path.name} を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.manager.delete_backup(path)
        self.log_manager.write(
            f"バックアップを削除しました: {path.name}"
        )
        self.reload_backups()

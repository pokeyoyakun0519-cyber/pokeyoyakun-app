from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.backup_manager import BackupManager
from core.diagnostic_bundle import DiagnosticBundle
from core.log_manager import LogManager
from core.migration_manager import MigrationManager


class MigrationPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.manager = MigrationManager()
        self.backup_manager = BackupManager()
        self.diagnostic_bundle = DiagnosticBundle()
        self.log_manager = LogManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        title = QLabel("データ移行")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "設定・商品一覧・候補・通知などをZIPへ書き出し、"
            "別のPCや新しいバージョンへ移行できます。\n"
            "安全のため、パスワードとライセンスは移行対象に含めません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        export_card = QFrame()
        export_card.setObjectName("SettingsCard")
        export_layout = QVBoxLayout(export_card)

        export_title = QLabel("データを書き出す")
        export_title.setObjectName("SectionTitle")

        export_text = QLabel(
            "現在の設定と商品データを、1つの移行用ZIPにまとめます。"
        )
        export_text.setWordWrap(True)

        export_button = QPushButton("移行パックを書き出す")
        export_button.setObjectName("AccentButton")
        export_button.clicked.connect(self.export_package)

        export_layout.addWidget(export_title)
        export_layout.addWidget(export_text)
        export_layout.addWidget(export_button)

        import_card = QFrame()
        import_card.setObjectName("SettingsCard")
        import_layout = QVBoxLayout(import_card)

        import_title = QLabel("データを読み込む")
        import_title.setObjectName("SectionTitle")

        import_text = QLabel(
            "読み込み前に現在のデータを自動バックアップします。"
        )
        import_text.setWordWrap(True)

        import_button = QPushButton("移行パックを読み込む")
        import_button.clicked.connect(self.import_package)

        import_layout.addWidget(import_title)
        import_layout.addWidget(import_text)
        import_layout.addWidget(import_button)

        diagnostic_card = QFrame()
        diagnostic_card.setObjectName("SettingsCard")
        diagnostic_layout = QVBoxLayout(diagnostic_card)

        diagnostic_title = QLabel("診断パック")
        diagnostic_title.setObjectName("SectionTitle")

        diagnostic_text = QLabel(
            "不具合調査に必要なログとシステム情報をZIPへまとめます。"
            "パスワードやライセンスは含めません。"
        )
        diagnostic_text.setWordWrap(True)

        diagnostic_button = QPushButton("診断パックを作成")
        diagnostic_button.clicked.connect(self.create_diagnostic_bundle)

        diagnostic_layout.addWidget(diagnostic_title)
        diagnostic_layout.addWidget(diagnostic_text)
        diagnostic_layout.addWidget(diagnostic_button)

        layout.addWidget(export_card)
        layout.addWidget(import_card)
        layout.addWidget(diagnostic_card)
        layout.addStretch()

    def export_package(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "移行パックを書き出す",
            "PokeyoyaKun_Migration.zip",
            "ZIPファイル (*.zip)",
        )

        if not path:
            return

        if not path.lower().endswith(".zip"):
            path += ".zip"

        try:
            result = self.manager.export_package(Path(path))
        except Exception as error:
            QMessageBox.critical(
                self,
                "書き出し失敗",
                str(error),
            )
            return

        self.log_manager.write(
            f"移行パックを書き出しました: {result}"
        )
        QMessageBox.information(
            self,
            "書き出し完了",
            f"移行パックを作成しました。\n\n{result}",
        )

    def import_package(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "移行パックを選択",
            "",
            "ZIPファイル (*.zip)",
        )

        if not path:
            return

        answer = QMessageBox.question(
            self,
            "データ読み込み",
            "現在のデータをバックアップしてから、"
            "移行パックを読み込みますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        try:
            backup = self.backup_manager.create_backup(
                "before_import"
            )
            imported = self.manager.import_package(Path(path))
        except Exception as error:
            QMessageBox.critical(
                self,
                "読み込み失敗",
                str(error),
            )
            return

        self.log_manager.write(
            f"移行パックを読み込みました: {len(imported)}件"
        )
        QMessageBox.information(
            self,
            "読み込み完了",
            f"{len(imported)}件を読み込みました。\n"
            f"事前バックアップ: {backup.name}\n\n"
            "アプリを再起動してください。",
        )

    def create_diagnostic_bundle(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "診断パックを保存",
            "PokeyoyaKun_Diagnostics.zip",
            "ZIPファイル (*.zip)",
        )

        if not path:
            return

        if not path.lower().endswith(".zip"):
            path += ".zip"

        try:
            result = self.diagnostic_bundle.create(Path(path))
        except Exception as error:
            QMessageBox.critical(
                self,
                "作成失敗",
                str(error),
            )
            return

        QMessageBox.information(
            self,
            "作成完了",
            f"診断パックを作成しました。\n\n{result}",
        )

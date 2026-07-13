from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core.backup_manager import BackupManager
from core.log_manager import LogManager
from core.update_config import UpdateConfig
from core.update_manager import UpdateError, UpdateManager
from core.version import APP_CHANNEL, APP_VERSION
from ui.update_worker import UpdateWorker


class UpdatePage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.config_manager = UpdateConfig()
        self.update_manager = UpdateManager()
        self.backup_manager = BackupManager()
        self.log_manager = LogManager()

        self.current_manifest = None
        self.downloaded_zip = None
        self.prepared_source = None
        self.worker_thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        title = QLabel("アップデート")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        current = QLabel(
            f"現在：Ver.{APP_VERSION}  "
            f"チャンネル：{APP_CHANNEL}"
        )
        current.setObjectName("SectionTitle")
        layout.addWidget(current)

        description = QLabel(
            "最新版の確認、ダウンロード、検証、バックアップ、"
            "置き換え、再起動までワンクリックで実行します。"
            "更新に失敗した場合は旧バージョンへ自動復元します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(card)

        self.manifest_input = QLineEdit()
        self.manifest_input.setPlaceholderText(
            "https://.../manifest.json "
            "またはローカルパス"
        )

        manifest_row = QHBoxLayout()
        browse = QPushButton("参照")
        browse.clicked.connect(
            self.browse_manifest
        )
        save = QPushButton("設定を保存")
        save.clicked.connect(
            self.save_config
        )
        manifest_row.addWidget(
            self.manifest_input,
            1,
        )
        manifest_row.addWidget(browse)
        manifest_row.addWidget(save)

        self.channel = QComboBox()
        self.channel.addItems(
            ["stable", "beta"]
        )
        self.check_on_startup = QCheckBox(
            "起動時に更新を確認"
        )

        card_layout.addWidget(
            QLabel("更新マニフェスト")
        )
        card_layout.addLayout(manifest_row)
        card_layout.addWidget(
            QLabel("更新チャンネル")
        )
        card_layout.addWidget(self.channel)
        card_layout.addWidget(
            self.check_on_startup
        )
        layout.addWidget(card)

        buttons = QHBoxLayout()

        self.check_button = QPushButton(
            "更新を確認"
        )
        self.check_button.clicked.connect(
            self.check_update
        )

        self.one_click_button = QPushButton(
            "ワンクリック更新"
        )
        self.one_click_button.setObjectName(
            "AccentButton"
        )
        self.one_click_button.setEnabled(False)
        self.one_click_button.clicked.connect(
            self.start_one_click_update
        )

        test = QPushButton("テスト表示")
        test.clicked.connect(
            self.check_test_manifest
        )

        buttons.addWidget(self.check_button)
        buttons.addWidget(self.one_click_button)
        buttons.addWidget(test)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status = QLabel(
            "まだ更新確認をしていません。"
        )
        self.status.setObjectName("MutedText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setObjectName("LogView")
        layout.addWidget(self.notes, 1)

        self.load_config()
        self.show_last_result()

    def load_config(self):
        config = self.config_manager.load()
        self.manifest_input.setText(
            str(
                config.get(
                    "manifest_url",
                    "",
                )
            )
        )
        self.channel.setCurrentText(
            str(
                config.get(
                    "channel",
                    APP_CHANNEL,
                )
            )
        )
        self.check_on_startup.setChecked(
            bool(
                config.get(
                    "check_on_startup",
                    True,
                )
            )
        )

    def save_config(self):
        config = self.config_manager.load()
        config.update(
            {
                "manifest_url": (
                    self.manifest_input
                    .text()
                    .strip()
                ),
                "channel": (
                    self.channel.currentText()
                ),
                "allow_beta": (
                    self.channel.currentText()
                    == "beta"
                ),
                "check_on_startup": (
                    self.check_on_startup
                    .isChecked()
                ),
            }
        )
        self.config_manager.save(config)

        QMessageBox.information(
            self,
            "保存完了",
            "更新設定を保存しました。",
        )

    def browse_manifest(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "更新マニフェストを選択",
            "",
            "JSONファイル (*.json);;"
            "すべてのファイル (*.*)",
        )
        if path:
            self.manifest_input.setText(path)

    def check_update(self):
        self._perform_check(
            self.manifest_input.text().strip()
        )

    def check_test_manifest(self):
        path = (
            self.update_manager
            .create_test_manifest()
        )
        self._perform_check(
            str(path),
            test_mode=True,
        )

    def _perform_check(
        self,
        location: str,
        test_mode: bool = False,
    ):
        self.downloaded_zip = None
        self.prepared_source = None
        self.progress.setValue(0)
        self.one_click_button.setEnabled(False)

        if not location:
            self.status.setText(
                "更新マニフェストを設定してください。"
            )
            return

        try:
            result = self.update_manager.check(
                location
            )
        except UpdateError as error:
            self.current_manifest = None
            self.status.setText(
                f"確認失敗：{error}"
            )
            self.notes.clear()
            return

        self.current_manifest = result["manifest"]
        message = result["reason"]

        if result.get("forced"):
            message += (
                "\nこの更新は必須です。"
                "更新後にアプリを再起動します。"
            )

        if test_mode:
            message += (
                "\nこれは画面確認用のテストです。"
            )

        self.status.setText(message)
        self.notes.setPlainText(
            str(
                self.current_manifest.get(
                    "notes",
                    "",
                )
            )
        )

        has_url = bool(
            str(
                self.current_manifest.get(
                    "download_url",
                    "",
                )
            ).strip()
        )
        self.one_click_button.setEnabled(
            bool(result["available"])
            and has_url
            and not test_mode
        )

    def start_one_click_update(self):
        if not self.current_manifest:
            return

        forced = bool(
            self.current_manifest.get(
                "force_update",
                False,
            )
        )
        answer = QMessageBox.question(
            self,
            "ワンクリック更新",
            "更新ファイルを取得・検証し、"
            "バックアップ後にアプリを終了して更新します。\n"
            "更新後は自動で再起動します。続けますか？"
            + (
                "\n\nこの更新は必須アップデートです。"
                if forced
                else ""
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
            if forced
            else QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._set_busy(True)
        self.status.setText(
            "更新準備を開始しています…"
        )
        self.progress.setRange(0, 0)

        self.worker_thread = QThread(self)
        self.worker = UpdateWorker(
            self.current_manifest
        )
        self.worker.moveToThread(
            self.worker_thread
        )

        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.progress.connect(
            self.status.setText
        )
        self.worker.completed.connect(
            self._on_download_completed
        )
        self.worker.failed.connect(
            self._on_download_failed
        )
        self.worker.completed.connect(
            self.worker_thread.quit
        )
        self.worker.failed.connect(
            self.worker_thread.quit
        )
        self.worker_thread.finished.connect(
            self._cleanup_worker
        )
        self.worker_thread.start()

    def _on_download_completed(
        self,
        result: dict,
    ):
        self.downloaded_zip = Path(
            str(result["zip_path"])
        )
        self.prepared_source = Path(
            str(result["source_path"])
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(75)
        self.status.setText(
            "更新ファイルの検証が完了しました。"
            "バックアップを作成しています…"
        )

        try:
            backup = (
                self.backup_manager
                .create_backup(
                    "before_program_update"
                )
            )
            command, _ = (
                self.update_manager
                .create_apply_command(
                    self.prepared_source
                )
            )
            self.update_manager.launch_apply_command(
                command
            )
        except Exception as error:
            self._on_download_failed(
                str(error)
            )
            return

        self.progress.setValue(100)
        self.log_manager.write(
            "ワンクリック更新を開始しました。"
            f"事前バックアップ: {backup.name}"
        )
        QMessageBox.information(
            self,
            "更新開始",
            "ポケヨヤ君を終了し、"
            "更新を適用して再起動します。",
        )
        QApplication.quit()

    def _on_download_failed(
        self,
        message: str,
    ):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(
            "更新に失敗しました。"
        )
        self._set_busy(False)
        QMessageBox.critical(
            self,
            "更新失敗",
            message,
        )

    def _cleanup_worker(self):
        if self.worker is not None:
            self.worker.deleteLater()
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None

    def _set_busy(
        self,
        busy: bool,
    ):
        self.check_button.setEnabled(
            not busy
        )
        self.one_click_button.setEnabled(
            not busy
            and self.current_manifest
            is not None
        )

    def show_last_result(self):
        result = (
            self.update_manager
            .read_last_result()
        )
        if not result:
            return

        if result.get("success"):
            self.status.setText(
                "前回の更新は正常に完了しました。\n"
                + str(
                    result.get(
                        "updated_at",
                        "",
                    )
                )
            )
        else:
            self.status.setText(
                "前回の更新に失敗しました。\n"
                + str(
                    result.get(
                        "message",
                        "",
                    )
                )
            )

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from core.update_config import UpdateConfig
from core.version import APP_CHANNEL, APP_VERSION
from ui.update_worker import UpdateCheckWorker, UpdateDownloadWorker


class UpdatePage(QFrame):
    def __init__(self, update_manager=None):
        super().__init__()
        self.setObjectName("ContentPanel")
        if update_manager is None:
            raise ValueError("更新Managerが必要です。")
        self.update_manager = update_manager
        self.config_manager = UpdateConfig(self.update_manager.edition_id)
        self.current_release = None
        self.thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)
        title = QLabel("アップデート")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        edition = "Owner Edition" if self.update_manager.edition_id == "owner" else "User Edition"
        self.current_label = QLabel(
            f"現在：Ver.{APP_VERSION} {APP_CHANNEL.upper()}　{edition}"
        )
        self.current_label.setObjectName("SectionTitle")
        layout.addWidget(self.current_label)
        self.latest_label = QLabel("最新：未確認")
        layout.addWidget(self.latest_label)
        self.size_label = QLabel("ダウンロードサイズ：未確認")
        layout.addWidget(self.size_label)

        self.allow_prerelease = QCheckBox("テスター向けPre-releaseも取得する")
        self.check_on_startup = QCheckBox("起動時にバックグラウンドで更新を確認")
        config = self.config_manager.load()
        self.allow_prerelease.setChecked(bool(config.get("allow_prerelease", False)))
        self.check_on_startup.setChecked(bool(config.get("check_on_startup", True)))
        self.allow_prerelease.toggled.connect(self.save_config)
        self.check_on_startup.toggled.connect(self.save_config)
        layout.addWidget(self.allow_prerelease)
        layout.addWidget(self.check_on_startup)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("更新を確認")
        self.check_button.clicked.connect(self.check_update)
        self.update_button = QPushButton("今すぐ更新")
        self.update_button.setObjectName("AccentButton")
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.start_update)
        self.later_button = QPushButton("後で")
        self.later_button.clicked.connect(lambda: self.status.setText("更新を後で行います。"))
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        for button in (self.check_button, self.update_button, self.later_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel("まだ更新確認をしていません。")
        self.status.setObjectName("MutedText")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("更新内容")
        layout.addWidget(self.notes, 1)
        self.show_last_result()
        if not self.update_manager.updates_enabled:
            self.status.setText(self.update_manager.disabled_reason)
            self.check_button.setEnabled(False)
            self.update_button.setEnabled(False)
            self.allow_prerelease.setEnabled(False)
            self.check_on_startup.setChecked(False)
            self.check_on_startup.setEnabled(False)
        elif self.check_on_startup.isChecked():
            # 起動直後の画面生成や短時間スモーク終了と競合しないよう、
            # UIが安定してから一度だけバックグラウンド確認を開始する。
            QTimer.singleShot(5000, lambda: self.check_update(background=True))

    def save_config(self):
        self.config_manager.save({
            "check_on_startup": self.check_on_startup.isChecked(),
            "allow_prerelease": self.allow_prerelease.isChecked(),
        })

    def check_update(self, checked=False, *, background=False):
        if not self.update_manager.updates_enabled:
            self.status.setText(self.update_manager.disabled_reason)
            return
        if self.thread is not None:
            return
        self.status.setText("バックグラウンドで更新を確認しています…" if background else "更新を確認しています…")
        self.check_button.setEnabled(False)
        self.thread = QThread(self)
        self.worker = UpdateCheckWorker(self.update_manager, self.allow_prerelease.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._check_completed)
        self.worker.failed.connect(self._operation_failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.thread.start()

    def _check_completed(self, result: dict):
        self.current_release = result if result.get("available") else None
        self.status.setText(str(result.get("reason", "更新確認が完了しました。")))
        self.update_button.setEnabled(self.current_release is not None)
        if self.current_release:
            self.latest_label.setText(f"最新：{result['tag']}")
            self.size_label.setText(f"ダウンロードサイズ：{result['size'] / 1024 / 1024:.1f} MB")
            self.notes.setPlainText(result.get("notes", ""))
        else:
            self.latest_label.setText("最新：現在のバージョン")
            self.size_label.setText("ダウンロード：不要")
            self.notes.clear()
        self.check_button.setEnabled(True)

    def start_update(self):
        if not self.current_release or self.thread is not None:
            return
        if QMessageBox.question(
            self, "更新の確認", "Setup.exeを取得・検証し、アプリを終了して更新しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.progress.setValue(0)
        self.status.setText("更新ファイルをダウンロードしています…")
        self.update_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.thread = QThread(self)
        self.worker = UpdateDownloadWorker(self.update_manager, self.current_release)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.completed.connect(self._download_completed)
        self.worker.failed.connect(self._operation_failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.thread.start()

    def cancel_download(self):
        if isinstance(self.worker, UpdateDownloadWorker):
            self.worker.cancel()
            self.status.setText("キャンセルしています…")

    def _download_completed(self, value: str):
        try:
            command, _status = self.update_manager.create_apply_command(Path(value))
            self.update_manager.launch_apply_command(command)
        except Exception as error:
            self._operation_failed(str(error))
            return
        self.progress.setValue(100)
        QMessageBox.information(self, "更新開始", "アプリを終了し、更新後に自動再起動します。")
        QApplication.quit()

    def _operation_failed(self, message: str):
        self.status.setText(f"更新に失敗しました：{message}")
        self.check_button.setEnabled(True)
        self.update_button.setEnabled(self.current_release is not None)
        self.cancel_button.setEnabled(False)

    def _cleanup(self):
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.cancel_button.setEnabled(False)

    def show_last_result(self):
        result = self.update_manager.read_last_result()
        if result:
            self.status.setText(
                "前回の更新は正常に完了しました。" if result.get("success")
                else "前回の更新に失敗しました。旧版は保持されています。"
            )

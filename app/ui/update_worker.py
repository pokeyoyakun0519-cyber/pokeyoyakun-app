from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from core.update_manager import UpdateManager


class UpdateWorker(QObject):
    progress = Signal(str)
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        manifest: dict,
    ):
        super().__init__()
        self.manifest = dict(manifest)

    @Slot()
    def run(self):
        try:
            self.progress.emit(
                "更新ファイルをダウンロードしています…"
            )
            manager = UpdateManager()
            zip_path = manager.download(
                self.manifest
            )

            self.progress.emit(
                "更新ファイルを検証・展開しています…"
            )
            source = manager.prepare_update(
                zip_path
            )

            self.completed.emit(
                {
                    "zip_path": str(zip_path),
                    "source_path": str(source),
                }
            )
        except Exception as error:
            self.failed.emit(str(error))

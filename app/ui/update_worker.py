from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot


class UpdateCheckWorker(QObject):
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, manager, allow_prerelease: bool):
        super().__init__()
        self.manager = manager
        self.allow_prerelease = allow_prerelease

    @Slot()
    def run(self):
        try:
            self.completed.emit(
                self.manager.check(allow_prerelease=self.allow_prerelease)
            )
        except Exception as error:
            self.failed.emit(str(error))


class UpdateDownloadWorker(QObject):
    progress = Signal(int)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, manager, release: dict):
        super().__init__()
        self.manager = manager
        self.release = dict(release)
        self.cancel_event = Event()

    def cancel(self):
        self.cancel_event.set()

    @Slot()
    def run(self):
        try:
            path = self.manager.download(
                self.release,
                progress=self.progress.emit,
                cancel=self.cancel_event,
            )
            self.completed.emit(str(path))
        except Exception as error:
            self.failed.emit(str(error))

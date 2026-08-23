from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from core.windows_process import hidden_process_kwargs


def test_windows_background_process_uses_no_window_flags():
    options = hidden_process_kwargs()
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE


class _SidebarTopLevelShowRecorder(QObject):
    def __init__(self):
        super().__init__()
        self.parentless_shows = []

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Show
            and watched.objectName() in {
                "MenuSectionContainer", "DeveloperMenuContainer",
            }
            and watched.isWindow()
        ):
            self.parentless_shows.append({
                "class": type(watched).__name__,
                "object_name": watched.objectName(),
                "parent": watched.parentWidget(),
                "is_window": watched.isWindow(),
                "window_flags": int(watched.windowFlags()),
            })
        return False


def test_page_navigation_five_rounds_has_no_transient_top_level_or_child_process():
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    recorder = _SidebarTopLevelShowRecorder()
    app.installEventFilter(recorder)
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False,
    ), patch("core.windows_process.subprocess.Popen") as launcher:
        try:
            window = MainWindow()
            window.show()
            app.processEvents()
            baseline_windows = {
                id(widget) for widget in app.topLevelWidgets()
                if widget is not window and widget.isVisible()
            }
            buttons = (
                window.home_button,
                window.product_button,
                window.application_dashboard_button,
                window.monitoring_candidates_button,
                window.calendar_button,
                window.scheduler_button,
                window.sources_button,
                window.notification_center_button,
            )
            for _round in range(5):
                for button in buttons:
                    button.click()
                    app.processEvents()

            assert recorder.parentless_shows == []
            for _toggle, container, _layout, _buttons in window.menu_sections.values():
                assert container.parentWidget() is not None
                assert container.isWindow() is False
            assert launcher.call_count == 0, launcher.mock_calls
            visible_auxiliary = [
                (type(widget).__name__, widget.windowTitle(), widget.objectName())
                for widget in app.topLevelWidgets()
                if widget is not window and widget.isVisible()
                and id(widget) not in baseline_windows
            ]
            assert visible_auxiliary == []
            assert window.pages.currentWidget() is window.notification_center_page
            window.close()
        finally:
            app.removeEventFilter(recorder)

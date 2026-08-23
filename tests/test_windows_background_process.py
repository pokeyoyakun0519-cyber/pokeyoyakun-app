from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from core.windows_process import hidden_process_kwargs


def test_windows_background_process_uses_no_window_flags():
    options = hidden_process_kwargs()
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_page_navigation_three_rounds_does_not_spawn_child_processes():
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"POKEYOYA_DATA_ROOT": directory}, clear=False,
    ), patch("core.windows_process.subprocess.Popen") as launcher:
        window = MainWindow()
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
        for _round in range(3):
            for button in buttons:
                button.click()
                app.processEvents()

        assert launcher.call_count == 0, launcher.mock_calls
        assert window.pages.currentWidget() is window.notification_center_page
        window.close()

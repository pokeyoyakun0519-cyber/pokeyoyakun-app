from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from core.candidate_auto_search import CandidateAutoSearch
from core.config_manager import ConfigManager
from core.gmail_result_service import GmailResultService
from core.initial_data_bootstrap import InitialDataBootstrap
from core.lottery_manager import LotteryManager
from core.monitor_scheduler import MonitorScheduler
from core.product_store import ProductStore
from core.scheduler_config import SchedulerConfig
from core.source_manager import SourceManager
from ui.main_window import InitialDataBootstrapWorker, MainWindow
from ui.tray_controller import TrayController


class _FakeThread:
    def __init__(self, *, running: bool = True, wait_result: bool = True):
        self.running = running
        self.wait_result = wait_result
        self.interruption_requested = False
        self.quit_requested = False
        self.wait_timeouts: list[int] = []

    def isRunning(self):
        return self.running

    def requestInterruption(self):
        self.interruption_requested = True

    def quit(self):
        self.quit_requested = True

    def wait(self, timeout):
        self.wait_timeouts.append(timeout)
        if self.wait_result:
            self.running = False
        return self.wait_result


class _FakeWorker:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _FakeSearchWorker:
    def __init__(self):
        self.cancelled = False

    def request_cancel(self):
        self.cancelled = True


class BackgroundLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            "os.environ",
            {"POKEYOYA_DATA_ROOT": str(self.root)},
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def _configure(self, *, setup_completed=True, monitor_enabled=True):
        config = ConfigManager(self.root)
        values = config.load()
        values["general"]["setup_completed"] = setup_completed
        values["general"]["new_product_auto_fetch"] = True
        config.save(values)
        scheduler = SchedulerConfig(self.root)
        scheduler_values = scheduler.load()
        scheduler_values["enabled"] = monitor_enabled
        scheduler_values["last_run"] = ""
        scheduler.save(scheduler_values)

    @staticmethod
    def _process_until(predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def _dispose_window(self, window):
        window._shutdown_started = True
        window.monitor_scheduler.request_shutdown()
        if window.initial_data_worker is not None:
            window.initial_data_worker.cancel()
        if window.initial_data_thread is not None:
            window.initial_data_thread.requestInterruption()
            window.initial_data_thread.quit()
            window.initial_data_thread.wait(3000)
        window.hide()
        window.deleteLater()
        QApplication.processEvents()

    def test_setup_completion_suspends_before_scheduling_bootstrap(self):
        self._configure()
        window = MainWindow()
        with (
            patch.object(window.monitor_scheduler, "suspend") as suspend,
            patch.object(window.monitor_scheduler, "reload_config") as reload_config,
            patch("ui.main_window.QTimer.singleShot") as single_shot,
        ):
            window._setup_wizard_completed({"ui_mode": "simple"})
        suspend.assert_called_once_with("初回商品取得の確認中")
        reload_config.assert_not_called()
        single_shot.assert_called_once()
        self._dispose_window(window)

    def test_bootstrap_blocks_reload_and_run_now_then_starts_monitor_once(self):
        self._configure()
        started = threading.Event()
        release = threading.Event()
        monitor_starts = Mock()

        def bootstrap_run(_bootstrap, **kwargs):
            started.set()
            release.wait(2)
            return {
                "started": True,
                "cancelled": False,
                "phase": "completed",
                "product_count": 0,
                "retail_candidate_count": 0,
                "retail_searched_count": 0,
            }

        window = MainWindow()
        window.monitor_scheduler._start_run = monitor_starts
        with (
            patch.object(InitialDataBootstrap, "should_run", return_value=True),
            patch.object(InitialDataBootstrap, "run", bootstrap_run),
        ):
            self.assertTrue(window._start_initial_data_bootstrap())
            self.assertTrue(started.wait(1))
            window.monitor_scheduler.reload_config()
            window.monitor_scheduler.run_now()
            monitor_starts.assert_not_called()
            release.set()
            self.assertTrue(self._process_until(
                lambda: window.initial_data_thread is None
            ))
        monitor_starts.assert_called_once()
        self.assertTrue(window._startup_coordination_complete)
        self._dispose_window(window)

    def test_bootstrap_failure_resumes_monitor_only_once(self):
        self._configure()
        monitor_starts = Mock()
        window = MainWindow()
        window.monitor_scheduler._start_run = monitor_starts
        with (
            patch.object(InitialDataBootstrap, "should_run", return_value=True),
            patch.object(
                InitialDataBootstrap,
                "run",
                side_effect=RuntimeError("expected failure"),
            ),
        ):
            self.assertTrue(window._start_initial_data_bootstrap())
            self.assertTrue(self._process_until(
                lambda: window.initial_data_thread is None
            ))
        monitor_starts.assert_called_once()
        self._dispose_window(window)

    def test_monitor_disabled_stays_disabled_after_bootstrap(self):
        self._configure(monitor_enabled=False)
        window = MainWindow()
        start_run = Mock()
        window.monitor_scheduler._start_run = start_run
        with patch.object(InitialDataBootstrap, "should_run", return_value=False):
            self.assertFalse(window._start_initial_data_bootstrap())
        self.assertTrue(window._startup_coordination_complete)
        start_run.assert_not_called()
        self._dispose_window(window)

    def test_no_bootstrap_uses_normal_monitor_path(self):
        self._configure()
        window = MainWindow()
        start_run = Mock()
        window.monitor_scheduler._start_run = start_run
        with patch.object(InitialDataBootstrap, "should_run", return_value=False):
            self.assertFalse(window._start_initial_data_bootstrap())
        start_run.assert_called_once()
        self._dispose_window(window)

    def test_existing_monitor_worker_defers_bootstrap(self):
        self._configure()
        window = MainWindow()
        window.monitor_scheduler.running = True
        with patch.object(InitialDataBootstrap, "should_run") as should_run:
            self.assertFalse(window._start_initial_data_bootstrap())
        should_run.assert_not_called()
        self.assertIsNone(window.initial_data_thread)
        self._dispose_window(window)

    def test_shutdown_completion_does_not_resume_monitor(self):
        self._configure()
        window = MainWindow()
        window._shutdown_started = True
        resume = Mock()
        window.monitor_scheduler.resume = resume
        window._initial_data_bootstrap_finished()
        resume.assert_not_called()
        self._dispose_window(window)

    def test_scheduler_reload_and_manual_run_are_blocked_while_suspended(self):
        scheduler = MonitorScheduler()
        scheduler.suspend("exclusive")
        start_run = Mock()
        scheduler._start_run = start_run
        scheduler.reload_config()
        scheduler.run_now()
        start_run.assert_not_called()
        scheduler.request_shutdown()

    def test_scheduler_refuses_second_worker(self):
        scheduler = MonitorScheduler()
        scheduler.suspended = False
        scheduler.running = True
        with patch("core.monitor_scheduler.QThread") as thread_class:
            scheduler._start_run({"check_sources": True})
        thread_class.assert_not_called()
        scheduler.request_shutdown()

    def test_scheduler_shutdown_stops_timer_and_requests_cooperative_cancel(self):
        scheduler = MonitorScheduler()
        worker = _FakeWorker()
        thread = _FakeThread()
        scheduler.worker = worker
        scheduler.thread = thread
        scheduler.request_shutdown()
        self.assertFalse(scheduler.timer.isActive())
        self.assertTrue(worker.cancelled)
        self.assertTrue(thread.interruption_requested)
        self.assertTrue(thread.quit_requested)

    def test_scheduler_wait_has_a_bounded_timeout_and_no_force_termination(self):
        scheduler = MonitorScheduler()
        thread = _FakeThread(wait_result=False)
        scheduler.thread = thread
        self.assertFalse(scheduler.wait_for_shutdown(50_000))
        self.assertEqual([10_000], thread.wait_timeouts)
        source = (APP_DIR / "core" / "monitor_scheduler.py").read_text(
            encoding="utf-8"
        )
        forbidden = "termi" + "nate("
        self.assertNotIn(forbidden, source)

    def test_bootstrap_worker_accepts_cooperative_cancel(self):
        worker = InitialDataBootstrapWorker()
        self.assertFalse(worker._cancel_requested.is_set())
        worker.cancel()
        self.assertTrue(worker._cancel_requested.is_set())

    def test_idle_shutdown_stops_all_timers(self):
        self._configure()
        window = MainWindow()
        self.assertTrue(window.shutdown_background_work())
        self.assertFalse(window.monitor_scheduler.timer.isActive())
        self.assertFalse(window.ui_mode_timer.isActive())
        self.assertFalse(window.application_assistant_timer.isActive())
        self._dispose_window(window)

    def test_shutdown_while_bootstrap_running_cancels_without_resume(self):
        self._configure()
        started = threading.Event()

        def bootstrap_run(_bootstrap, **kwargs):
            started.set()
            cancel_requested = kwargs["cancel_requested"]
            while not cancel_requested():
                time.sleep(0.01)
            return {"started": True, "cancelled": True, "phase": "cancelled"}

        window = MainWindow()
        resume = Mock()
        window.monitor_scheduler.resume = resume
        with (
            patch.object(InitialDataBootstrap, "should_run", return_value=True),
            patch.object(InitialDataBootstrap, "run", bootstrap_run),
        ):
            self.assertTrue(window._start_initial_data_bootstrap())
            self.assertTrue(started.wait(1))
            self.assertTrue(window.shutdown_background_work())
        resume.assert_not_called()
        self.assertTrue(window._shutdown_started)
        self._dispose_window(window)

    def test_shutdown_while_monitor_running_requests_cancel(self):
        self._configure()
        window = MainWindow()
        worker = _FakeWorker()
        thread = _FakeThread()
        window.monitor_scheduler.worker = worker
        window.monitor_scheduler.thread = thread
        self.assertTrue(window.shutdown_background_work())
        self.assertTrue(worker.cancelled)
        self.assertTrue(thread.interruption_requested)
        self._dispose_window(window)

    def test_shutdown_coordinates_candidate_and_update_threads(self):
        self._configure()
        window = MainWindow()
        candidate_worker = _FakeSearchWorker()
        candidate_thread = _FakeThread()
        update_worker = Mock()
        update_thread = _FakeThread()
        window.candidates_page.search_worker = candidate_worker
        window.candidates_page.search_thread = candidate_thread
        window.update_page.worker = update_worker
        window.update_page.thread = update_thread

        self.assertTrue(window.shutdown_background_work())

        self.assertTrue(candidate_worker.cancelled)
        self.assertTrue(candidate_thread.interruption_requested)
        self.assertTrue(candidate_thread.quit_requested)
        self.assertTrue(update_thread.interruption_requested)
        self.assertTrue(update_thread.quit_requested)
        self._dispose_window(window)

    def test_candidate_result_signal_after_shutdown_does_not_save(self):
        self._configure()
        window = MainWindow()
        window.candidates_page.shutting_down = True
        update_result = Mock()
        window.candidates_page.candidate_manager.update_search_result = update_result

        window.candidates_page._on_candidate_completed(
            "candidate",
            [{"name": "late"}],
            [],
        )

        update_result.assert_not_called()
        self._dispose_window(window)

    def test_update_completion_uses_coordinated_quit_callback(self):
        self._configure()
        window = MainWindow()
        coordinated_quit = Mock()
        window.update_page.set_quit_callback(coordinated_quit)
        window.update_page.update_manager.create_apply_command = Mock(
            return_value=(["updater"], "ok")
        )
        window.update_page.update_manager.launch_apply_command = Mock()

        with patch("ui.update_page.QMessageBox.information"):
            window.update_page._download_completed("update.exe")

        coordinated_quit.assert_called_once_with()
        self._dispose_window(window)

    def test_tray_full_exit_uses_window_shutdown_coordinator(self):
        window = Mock()
        scheduler = Mock()
        tray = TrayController.__new__(TrayController)
        tray.window = window
        tray.scheduler = scheduler
        tray.tray = Mock()
        TrayController.quit_application(tray)
        self.assertTrue(window.allow_close)
        tray.tray.hide.assert_called_once_with()
        window.request_application_quit.assert_called_once_with()

    def test_close_to_tray_does_not_stop_monitor(self):
        self._configure()
        window = MainWindow()
        window.tray_controller = Mock()
        event = QCloseEvent()
        with patch.object(
            window.behavior_config,
            "load",
            return_value={"close_to_tray": True},
        ), patch.object(window, "shutdown_background_work") as shutdown:
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        shutdown.assert_not_called()
        window.tray_controller.hide_window.assert_called_once_with()
        self._dispose_window(window)

    def test_full_window_close_uses_shutdown_coordinator(self):
        self._configure()
        window = MainWindow()
        event = QCloseEvent()
        with (
            patch.object(
                window.behavior_config,
                "load",
                return_value={"close_to_tray": False},
            ),
            patch.object(window, "request_application_quit") as request_quit,
        ):
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        request_quit.assert_called_once_with()
        self._dispose_window(window)

    def test_late_signals_do_not_update_ui_after_shutdown(self):
        self._configure()
        window = MainWindow()
        window._shutdown_started = True
        product_reload = Mock()
        dashboard_reload = Mock()
        window.product_page.reload_saved_products = product_reload
        window.application_dashboard_page.reload = dashboard_reload
        window._initial_data_bootstrap_official_loaded({"started": True})
        window._initial_data_bootstrap_retail_progress({})
        window._initial_data_bootstrap_completed({"started": True})
        window._refresh_data_pages_after_monitor({})
        product_reload.assert_not_called()
        dashboard_reload.assert_not_called()
        self._dispose_window(window)

    def test_cancel_callbacks_stop_each_monitor_loop_at_safe_boundaries(self):
        search = CandidateAutoSearch()
        search.candidates = Mock()
        search.candidates.load_candidates.return_value = [
            {"id": "one", "last_searched": ""},
            {"id": "two", "last_searched": ""},
        ]
        search.searcher = Mock()
        search.searcher.search_candidate.return_value = ([], [])
        search.candidates.update_search_result.return_value = {}
        result = search.run_due(
            cancel_requested=lambda: search.searcher.search_candidate.call_count >= 1
        )
        self.assertTrue(result["cancelled"])
        self.assertEqual(1, search.searcher.search_candidate.call_count)

    def test_source_lottery_and_gmail_honor_pre_cancel(self):
        cancelled = lambda: True
        source = SourceManager()
        source.save_sources = Mock()
        source.load_sources = Mock(return_value=[{"enabled": True}])
        source._check_source_record = Mock()
        source.check_all(cancel_requested=cancelled)
        source._check_source_record.assert_not_called()

        lottery = LotteryManager()
        lottery.load_items = Mock(return_value=[{"url": "https://example.com"}])
        lottery._fetch_and_judge = Mock()
        lottery.check_all(cancel_requested=cancelled)
        lottery._fetch_and_judge.assert_not_called()

        gmail = GmailResultService()
        gmail.account_manager.load_accounts = Mock(return_value=[{
            "id": "mail",
            "enabled": True,
            "connection_status": "連携済み",
        }])
        gmail.scan_account = Mock()
        gmail.scan_all_enabled(cancel_requested=cancelled)
        gmail.scan_account.assert_not_called()

    def test_temporary_json_remains_readable_and_monitor_never_overlaps(self):
        self._configure()
        started = threading.Event()
        release = threading.Event()
        overlap = []
        monitor_starts = Mock(side_effect=lambda *_args: overlap.append("monitor"))

        def bootstrap_run(_bootstrap, **_kwargs):
            ProductStore(self.root)._save_product_file([{
                "id": "safe",
                "name": "安全保存",
                "tcg_key": "pokemon",
                "status": "発売予定",
                "sites": [],
            }])
            overlap.append("bootstrap")
            started.set()
            release.wait(2)
            return {
                "started": True,
                "cancelled": False,
                "phase": "completed",
                "product_count": 1,
                "retail_candidate_count": 0,
                "retail_searched_count": 0,
            }

        window = MainWindow()
        window.monitor_scheduler._start_run = monitor_starts
        with (
            patch.object(InitialDataBootstrap, "should_run", return_value=True),
            patch.object(InitialDataBootstrap, "run", bootstrap_run),
        ):
            self.assertTrue(window._start_initial_data_bootstrap())
            self.assertTrue(started.wait(1))
            window.monitor_scheduler.reload_config()
            self.assertEqual(["bootstrap"], overlap)
            release.set()
            self.assertTrue(self._process_until(
                lambda: window.initial_data_thread is None
            ))
        self.assertEqual(["bootstrap", "monitor"], overlap)
        data = json.loads(
            (self.root / "data" / "products.json").read_text(encoding="utf-8")
        )
        self.assertEqual("safe", data[0]["id"])
        self._dispose_window(window)


if __name__ == "__main__":
    unittest.main()

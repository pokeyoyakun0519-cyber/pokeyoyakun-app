import json
import os
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from core.app_setup import configure_application, configure_high_dpi
from core.behavior_config import BehaviorConfig
from core.crash_handler import install_crash_handler
from core.release_config import ReleaseConfig
from core.release_integrity import verify_runtime_integrity
from core.secure_https import create_tls_context
from core.startup_check import StartupCheck
from core.startup_diagnostics import StartupDiagnostics
from core.whats_new_manager import WhatsNewManager


class _NavigationTopLevelRecorder(QObject):
    def __init__(self):
        super().__init__()
        self.shows = []

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            parent = watched.parentWidget()
            self.shows.append({
                "class": type(watched).__name__,
                "title": watched.windowTitle(),
                "object_name": watched.objectName(),
                "parent_class": type(parent).__name__ if parent else "",
                "is_window": watched.isWindow(),
                "window_flags": int(watched.windowFlags()),
            })
        return False


def main():
    configure_high_dpi()
    navigation_smoke = "--navigation-smoke-test" in sys.argv
    navigation_processes = []
    if navigation_smoke:
        def record_process(event, args):
            if event == "subprocess.Popen":
                executable = str(args[0] if args else "")
                navigation_processes.append(Path(executable).name or executable)

        sys.addaudithook(record_process)
    if "--tls-ca-self-test" in sys.argv:
        try:
            create_tls_context()
        except Exception:
            raise SystemExit(1)
        raise SystemExit(0)

    if "--license-api-self-test" in sys.argv:
        from core.online_license_client import OnlineLicenseClient

        ok, _message = OnlineLicenseClient().test_connection()
        raise SystemExit(0 if ok else 1)

    if "--license-api-lifecycle-self-test" in sys.argv:
        from core.online_license_client import OnlineLicenseClient

        license_key = os.environ.pop("POKEYOYA_TEST_LICENSE_KEY", "").strip()
        result_path_value = os.environ.pop("POKEYOYA_TEST_RESULT_PATH", "")
        result_path = Path(result_path_value) if result_path_value else None
        result = {
            "activate": False,
            "verify": False,
            "deactivate": False,
            "key_id": "",
            "message": "",
            "failed_stage": "input",
            "exception_type": "",
            "diagnostics": {},
        }
        exit_code = 2
        if license_key and result_path is not None:
            device_id = "RC5-FROZEN-" + uuid.uuid4().hex.upper()
            client = OnlineLicenseClient(
                device_id_provider=lambda: device_id,
            )
            activated = False
            try:
                ok, message, data = client.activate(license_key)
                result["activate"] = ok
                result["message"] = message
                result["diagnostics"]["activate"] = dict(
                    client.last_response_diagnostic
                )
                token = data.get("license_token", {})
                signature = token.get("signature", {}) if isinstance(token, dict) else {}
                result["key_id"] = str(signature.get("key_id", ""))
                activated = ok
                if ok:
                    result["failed_stage"] = "verify"
                    ok, message, _data = client.verify(license_key)
                    result["verify"] = ok
                    result["message"] = message
                    result["diagnostics"]["verify"] = dict(
                        client.last_response_diagnostic
                    )
                    exit_code = 0 if ok else 4
                else:
                    result["failed_stage"] = "activate"
                    exit_code = 3
            except Exception as error:
                result["message"] = str(error)[:500]
                result["exception_type"] = type(error).__name__
                exit_code = 7
            finally:
                if activated:
                    try:
                        ok, message, _data = client.deactivate(license_key)
                        result["deactivate"] = ok
                        result["diagnostics"]["deactivate"] = dict(
                            client.last_response_diagnostic
                        )
                        if not ok:
                            result["failed_stage"] = "deactivate"
                            result["message"] = message
                            exit_code = 5
                    except Exception as error:
                        result["failed_stage"] = "deactivate"
                        result["message"] = str(error)[:500]
                        result["exception_type"] = type(error).__name__
                        exit_code = 8
                if result["activate"] and result["verify"] and result["deactivate"]:
                    result["failed_stage"] = ""
            try:
                result_path.write_text(
                    json.dumps(result, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                exit_code = 6
        raise SystemExit(exit_code)

    diagnostics = StartupDiagnostics()
    diagnostics.write("監視ソフトの起動を開始")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("ポケヨヤ君")
        app.setQuitOnLastWindowClosed(False)
        configure_application(app)
        navigation_window_recorder = None
        if navigation_smoke:
            navigation_window_recorder = _NavigationTopLevelRecorder()
            app.installEventFilter(navigation_window_recorder)
        release_config = ReleaseConfig()
        install_crash_handler()

        integrity_ok, integrity_message = verify_runtime_integrity()
        diagnostics.write(integrity_message)
        if not integrity_ok:
            QMessageBox.critical(None, "セキュリティ検査エラー", integrity_message)
            return

        repaired = StartupCheck().run()
        if repaired:
            diagnostics.write("起動時補修: " + " / ".join(repaired))

        smoke_test = "--smoke-test" in sys.argv or navigation_smoke

        if not smoke_test:
            from ui.license_dialog import LicenseDialog

            login = LicenseDialog()
            dialog_result = login.exec()
            if dialog_result != QDialog.Accepted:
                diagnostics.write(
                    "認証画面がキャンセルされました"
                )
                return
            if not login.authenticated:
                raise RuntimeError(
                    "認証画面はAcceptedを返しましたが、"
                    "認証状態が未完了です。"
                )

        from ui.main_window import MainWindow

        window = MainWindow()

        tray_controller = None
        if not smoke_test:
            from ui.tray_controller import TrayController

            tray_controller = TrayController(
                window,
                window.monitor_scheduler,
                app,
            )
            window.set_tray_controller(
                tray_controller
            )

        behavior = BehaviorConfig().load()
        start_minimized = (
            "--minimized" in sys.argv
            or behavior.get("start_minimized", False)
        )

        if smoke_test:
            window.show()
            app.processEvents()
            diagnostics.write(
                "スモークテスト: メイン画面生成成功"
            )
            if navigation_smoke:
                def run_navigation_smoke():
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
                    transient_top_levels = [
                        item for item in navigation_window_recorder.shows
                        if item["class"] not in {
                            type(window).__name__, "SetupWizard",
                        }
                    ]
                    visible_auxiliary = [
                        widget for widget in app.topLevelWidgets()
                        if widget is not window and widget.isVisible()
                        and id(widget) not in baseline_windows
                    ]
                    result_path = os.environ.get(
                        "POKEYOYA_NAVIGATION_SMOKE_RESULT", ""
                    ).strip()
                    if result_path:
                        Path(result_path).write_text(json.dumps({
                            "rounds": 5,
                            "page_count": len(buttons),
                            "processes": navigation_processes,
                            "child_process_count": len(navigation_processes),
                            "visible_auxiliary_window_count": len(visible_auxiliary),
                            "baseline_auxiliary_window_count": len(baseline_windows),
                            "visible_auxiliary_windows": [{
                                "class": type(widget).__name__,
                                "title": widget.windowTitle(),
                                "object_name": widget.objectName(),
                            } for widget in visible_auxiliary],
                            "transient_top_level_window_count": len(
                                transient_top_levels
                            ),
                            "transient_top_level_windows": transient_top_levels,
                            "version": window._version_text(),
                        }, ensure_ascii=False), encoding="utf-8")
                    window.request_application_quit()

                QTimer.singleShot(0, run_navigation_smoke)
            else:
                QTimer.singleShot(
                    1200,
                    window.request_application_quit,
                )
        elif start_minimized:
            window.hide()
        else:
            window.show()

        if (
            not smoke_test
            and not start_minimized
            and WhatsNewManager().should_show()
        ):
            from ui.whats_new_dialog import WhatsNewDialog
            WhatsNewDialog(window).exec()

        diagnostics.write(
            "メイン画面の初期化に成功"
            if smoke_test
            else "メイン画面とタスクトレイの初期化に成功"
        )
        exit_code = app.exec()

        if smoke_test:
            diagnostics.write(
                "スモークテスト: 正常終了"
            )

        raise SystemExit(exit_code)

    except Exception as error:
        log_path = diagnostics.write_exception(
            "監視ソフトの起動に失敗しました。",
            error,
        )
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None,
                "起動エラー",
                "ポケヨヤ君を起動できませんでした。\n\n"
                f"エラーログ:\n{log_path}",
            )
        else:
            print(log_path)
            raise


if __name__ == "__main__":
    main()

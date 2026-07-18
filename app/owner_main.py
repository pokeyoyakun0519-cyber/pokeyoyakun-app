import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from core.app_setup import configure_application, configure_high_dpi
from core.behavior_config import BehaviorConfig
from core.crash_handler import install_crash_handler
from core.release_integrity import verify_runtime_integrity
from core.secure_https import create_tls_context
from core.startup_check import StartupCheck
from core.startup_diagnostics import StartupDiagnostics
from core.whats_new_manager import WhatsNewManager


def main():
    configure_high_dpi()
    if "--tls-ca-self-test" in sys.argv:
        try:
            create_tls_context()
        except Exception:
            raise SystemExit(1)
        raise SystemExit(0)

    diagnostics = StartupDiagnostics()
    diagnostics.write("Owner Editionの起動を開始")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("ポケヨヤ君 Owner Edition")
        app.setQuitOnLastWindowClosed(False)
        configure_application(app)
        install_crash_handler()

        integrity_ok, integrity_message = verify_runtime_integrity()
        diagnostics.write(integrity_message)
        if not integrity_ok:
            QMessageBox.critical(None, "セキュリティ検査エラー", integrity_message)
            return

        repaired = StartupCheck().run()
        if repaired:
            diagnostics.write("起動時補修: " + " / ".join(repaired))

        smoke_test = "--smoke-test" in sys.argv

        from ui.owner_main_window import OwnerMainWindow

        window = OwnerMainWindow()

        tray_controller = None
        if not smoke_test:
            from ui.tray_controller import TrayController

            tray_controller = TrayController(
                window,
                window.monitor_scheduler,
                app,
            )
            window.set_tray_controller(tray_controller)

        behavior = BehaviorConfig().load()
        start_minimized = (
            "--minimized" in sys.argv
            or behavior.get("start_minimized", False)
        )

        if smoke_test:
            window.show()
            app.processEvents()
            diagnostics.write("Owner Editionスモークテスト: メイン画面生成成功")
            QTimer.singleShot(1200, app.quit)
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
            "Owner Editionメイン画面の初期化に成功"
            if smoke_test
            else "Owner Editionメイン画面とタスクトレイの初期化に成功"
        )
        exit_code = app.exec()

        if smoke_test:
            diagnostics.write("Owner Editionスモークテスト: 正常終了")

        raise SystemExit(exit_code)

    except Exception as error:
        log_path = diagnostics.write_exception(
            "Owner Editionの起動に失敗しました。",
            error,
        )
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None,
                "起動エラー",
                "ポケヨヤ君 Owner Editionを起動できませんでした。\n\n"
                f"エラーログ:\n{log_path}",
            )
        else:
            print(log_path)
            raise


if __name__ == "__main__":
    main()

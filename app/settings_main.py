import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from core.app_setup import configure_application, configure_high_dpi
from core.crash_handler import install_crash_handler
from core.startup_check import StartupCheck
from core.startup_diagnostics import StartupDiagnostics
from core.release_integrity import verify_runtime_integrity


def main():
    configure_high_dpi()
    diagnostics = StartupDiagnostics()
    diagnostics.write("設定ソフトの起動を開始")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("ポケヨヤ君設定")
        configure_application(app)
        install_crash_handler()
        integrity_ok, integrity_message = verify_runtime_integrity()
        diagnostics.write(integrity_message)
        if not integrity_ok:
            QMessageBox.critical(None, "セキュリティ検査エラー", integrity_message)
            return
        StartupCheck().run()

        from ui.settings_window import SettingsWindow

        window = SettingsWindow()
        window.show()
        diagnostics.write("設定ソフトの表示に成功")
        sys.exit(app.exec())

    except Exception as error:
        log_path = diagnostics.write_exception(
            "設定ソフトの起動に失敗しました。",
            error,
        )
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None,
                "起動エラー",
                f"設定ソフトを起動できませんでした。\n\n{log_path}",
            )
        else:
            print(log_path)
            raise


if __name__ == "__main__":
    main()

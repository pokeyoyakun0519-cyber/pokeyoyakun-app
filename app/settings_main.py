import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from core.app_setup import configure_application
from core.crash_handler import install_crash_handler
from core.startup_check import StartupCheck
from core.startup_diagnostics import StartupDiagnostics


def main():
    diagnostics = StartupDiagnostics()
    diagnostics.write("設定ソフトの起動を開始")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("ポケヨヤ君設定")
        configure_application(app)
        install_crash_handler()
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

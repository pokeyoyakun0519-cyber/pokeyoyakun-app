from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon

from core.runtime_paths import bundled_root
from ui.style import STYLE


def configure_high_dpi() -> None:
    """QApplication生成前に、Qt 6のDPI端数処理を統一する。"""
    if QGuiApplication.instance() is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )


def configure_application(app) -> None:
    font = QFont("Yu Gothic UI")
    font.setPointSize(10)
    font.setHintingPreference(QFont.PreferFullHinting)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    from ui.design_system import install_ui_polish

    install_ui_polish(app)

    icon_path = bundled_root() / "assets" / "pokeyoya_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

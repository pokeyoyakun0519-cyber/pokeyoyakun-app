from PySide6.QtGui import QFont, QIcon

from core.runtime_paths import bundled_root
from ui.style import STYLE


def configure_application(app) -> None:
    font = QFont("Yu Gothic UI")
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLE)

    icon_path = bundled_root() / "assets" / "pokeyoya_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

STYLE = """
QWidget {
    background-color: #1b2838;
    color: #f2f2f2;
    font-family: "Yu Gothic UI";
    font-size: 10pt;
}

QFrame#Sidebar {
    background-color: #171f2b;
    border-right: 1px solid #2a475e;
}

QLabel#AppTitle {
    font-size: 18pt;
    font-weight: 700;
    color: #ffffff;
}

QLabel#VersionLabel {
    color: #8f98a0;
    font-size: 9pt;
}

QPushButton {
    background-color: #2a475e;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: left;
}

QPushButton:hover {
    background-color: #3a6b8c;
}

QPushButton:pressed {
    background-color: #66c0f4;
    color: #0b1118;
}

QPushButton#ExitButton {
    background-color: #6b2d35;
}

QPushButton#ExitButton:hover {
    background-color: #8a3a45;
}

QFrame#ContentPanel {
    background-color: #223447;
    border-radius: 14px;
}

QLabel#PageTitle {
    font-size: 22pt;
    font-weight: 700;
    color: #ffffff;
}

QLabel#PageText {
    font-size: 12pt;
    color: #c7d5e0;
}
"""

# 追加スタイルは下の STYLE 文字列へ結合する
STYLE += """
QPushButton#AccentButton {
    background-color: #66c0f4;
    color: #0b1118;
    font-weight: 700;
}

QPushButton#AccentButton:hover {
    background-color: #8fd3f8;
}

QPushButton#SmallButton {
    padding: 7px 10px;
    min-width: 130px;
}

QFrame#ProductCard {
    background-color: #1e3042;
    border: 1px solid #355269;
    border-radius: 12px;
}

QFrame#SiteRow {
    background-color: #172536;
    border-radius: 8px;
}

QLabel#ProductName {
    font-size: 13pt;
    font-weight: 700;
}

QLabel#MutedText {
    color: #9eabb7;
    font-size: 9pt;
}

QLabel#WarningText {
    color: #ff6b6b;
    font-weight: 700;
}

QLabel#StatusOpen {
    color: #75d58a;
    font-weight: 700;
}

QLabel#StatusLottery {
    color: #ffd166;
    font-weight: 700;
}

QLabel#StatusClosed {
    color: #ff6b6b;
    font-weight: 700;
}

QLabel#StatusOther {
    color: #c7d5e0;
    font-weight: 700;
}

QCheckBox {
    spacing: 8px;
}

QScrollArea {
    background: transparent;
    border: none;
}
"""


STYLE += """
QFrame#SettingsCard {
    background-color: #1e3042;
    border: 1px solid #355269;
    border-radius: 12px;
}

QLabel#SectionTitle {
    font-size: 13pt;
    font-weight: 700;
    color: #ffffff;
}

QLineEdit {
    background-color: #172536;
    color: #ffffff;
    border: 1px solid #355269;
    border-radius: 7px;
    padding: 9px 10px;
    selection-background-color: #66c0f4;
}

QLineEdit:focus {
    border: 1px solid #66c0f4;
}

QPushButton#DangerButton {
    background-color: #7a3039;
}

QPushButton#DangerButton:hover {
    background-color: #9a3e49;
}
"""


STYLE += """
QPlainTextEdit#LogView {
    background-color: #101a25;
    color: #c7d5e0;
    border: 1px solid #355269;
    border-radius: 10px;
    padding: 12px;
    font-family: Consolas, "Yu Gothic UI";
    font-size: 10pt;
}
"""


STYLE += """
QPushButton#NavigationButton {
    background-color: transparent;
    color: #c7d5e0;
    border: none;
    border-radius: 7px;
    padding: 10px 13px;
    text-align: left;
}

QPushButton#NavigationButton:hover {
    background-color: #263f55;
    color: #ffffff;
}

QPushButton#NavigationButton:checked {
    background-color: #3a6b8c;
    color: #ffffff;
    border-left: 4px solid #66c0f4;
    font-weight: 700;
}

QLabel#FooterStatus {
    color: #7f8c98;
    font-size: 8pt;
}

QFrame#TopBar {
    background-color: #1c2d3e;
    border-radius: 10px;
}

QLabel#DevBadge {
    background-color: #8a5a1f;
    color: #ffffff;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8pt;
    font-weight: 700;
}
"""


STYLE += """
QScrollArea#SidebarScroll {
    background-color: transparent;
    border: none;
}

QWidget#SidebarMenuContainer {
    background-color: transparent;
}

QLabel#MenuSectionLabel {
    color: #7f9db3;
    font-size: 8pt;
    font-weight: 700;
    padding: 10px 6px 4px 8px;
}

QPushButton#NavigationButton {
    min-height: 40px;
    max-height: 40px;
    padding: 0 12px;
    text-align: left;
    white-space: nowrap;
}

QScrollBar:vertical {
    background: #142333;
    width: 10px;
    margin: 2px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3a6b8c;
    min-height: 32px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #4e83a7;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


STYLE += """
QFrame#DashboardCard {
    background-color: #1e3042;
    border: 1px solid #355269;
    border-radius: 12px;
    min-width: 150px;
    min-height: 118px;
}

QFrame#DashboardCard:hover {
    border: 1px solid #4e83a7;
}

QLabel#DashboardCardTitle {
    color: #8fa9bb;
    font-size: 9pt;
    font-weight: 700;
}

QLabel#DashboardCardValue {
    color: #ffffff;
    font-size: 17pt;
    font-weight: 800;
}

QLabel#DashboardCardValue[statusLevel="success"] {
    color: #68d391;
}

QLabel#DashboardCardValue[statusLevel="warning"] {
    color: #f6c85f;
}

QLabel#DashboardCardValue[statusLevel="error"] {
    color: #ff6b6b;
}

QLabel#DashboardCardValue[statusLevel="muted"] {
    color: #7f8c98;
}

QLabel#DashboardStatusBar {
    background-color: #172536;
    color: #c7d5e0;
    border: 1px solid #355269;
    border-radius: 9px;
    padding: 11px 14px;
    font-weight: 700;
}
"""

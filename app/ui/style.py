PALETTE = {
    "background": "#0f1720",
    "surface": "#162534",
    "card": "#1b2d3d",
    "card_subtle": "#13212e",
    "border": "#304b60",
    "primary": "#66c0f4",
    "primary_hover": "#8fd3f8",
    "text": "#e7eef4",
    "muted": "#9eb0be",
    "success": "#75d58a",
    "warning": "#ffd166",
    "error": "#ff7f87",
}


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

QFrame#GlobalSearchBar {
    background-color: #171f2b;
    border-bottom: 1px solid #2a475e;
}

QLabel#GlobalSearchTitle {
    color: #ffffff;
    font-weight: 800;
}

QLabel#GlobalSearchStatus {
    color: #8fa9bb;
    min-width: 74px;
}

QLabel#GlobalSearchStatus[state="loading"] {
    color: #ffd166;
}

QLabel#GlobalSearchStatus[state="success"] {
    color: #75d58a;
}

QLabel#GlobalSearchStatus[state="error"] {
    color: #ff7f7f;
}

QFrame#GlobalSearchResults {
    background-color: #1e3042;
    border: 1px solid #355269;
    border-radius: 10px;
}

QLabel#GlobalSearchGroupTitle {
    color: #66c0f4;
    font-weight: 800;
    padding-top: 4px;
}

QPushButton#GlobalSearchResultButton {
    background-color: #172536;
    border: 1px solid #2f4960;
    border-radius: 7px;
    padding: 8px 12px;
    text-align: left;
}

QPushButton#GlobalSearchResultButton:hover {
    background-color: #2a475e;
    border-color: #66c0f4;
}

QLabel#GlobalSearchEmpty, QLabel#GlobalSearchError {
    color: #9db1c1;
    padding: 14px;
}

QLabel#GlobalSearchError {
    color: #ff8f8f;
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

QLabel#SetupProgress {
    color: #66c0f4;
    font-size: 11pt;
    font-weight: 800;
    padding: 8px 10px;
    background-color: #172536;
    border-radius: 8px;
}

QLabel#SetupInfo, QLabel#SetupSummary {
    color: #d8e3ec;
    background-color: #172536;
    border: 1px solid #355269;
    border-radius: 9px;
    padding: 14px;
}

QLabel#SetupError {
    color: #ff9a9a;
    background-color: #4b252c;
    border: 1px solid #8f3d49;
    border-radius: 8px;
    padding: 10px 12px;
    font-weight: 700;
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

QFrame#CandidateCard {
    background-color: #1f2d35;
    border: 1px solid #8a7436;
    border-radius: 8px;
}

QPushButton#AccentButton:disabled {
    background-color: #344653;
    color: #8596a3;
    border-color: #455966;
}

QLabel#StatusActive {
    color: #66c0f4;
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

QTabWidget#SettingsCategoryTabs::pane {
    border: 1px solid #355269;
    border-radius: 10px;
    background-color: #192a3a;
}

QTabWidget#SettingsCategoryTabs QTabBar::tab {
    background-color: #172536;
    color: #9db1c1;
    border: 1px solid #355269;
    padding: 9px 12px;
}

QTabWidget#SettingsCategoryTabs QTabBar::tab:selected {
    background-color: #2c5874;
    color: #ffffff;
}

QLabel#SettingsSaveStatus {
    border-radius: 8px;
    padding: 10px 12px;
}

QLabel#SettingsSaveStatus[state="clean"] {
    color: #8fa9bb;
    background-color: #172536;
}

QLabel#SettingsSaveStatus[state="dirty"] {
    color: #ffd166;
    background-color: #493d24;
    border: 1px solid #806c35;
    font-weight: 700;
}

QLabel#SettingsSaveStatus[state="success"] {
    color: #8ee0a1;
    background-color: #183d2a;
    border: 1px solid #32734a;
    font-weight: 700;
}

QLabel#SettingsSaveStatus[state="error"] {
    color: #ff9a9a;
    background-color: #4b252c;
    border: 1px solid #8f3d49;
    font-weight: 700;
}

QCheckBox[settingsChanged="true"],
QLineEdit[settingsChanged="true"],
QComboBox[settingsChanged="true"] {
    color: #ffd166;
    border: 1px solid #d3a93f;
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

QFrame#HomeSectionCard, QFrame#HomeSummaryCard {
    background-color: #1e3042;
    border: 1px solid #355269;
    border-radius: 12px;
}

QFrame#HomeSummaryItem {
    background-color: #172536;
    border: 1px solid #2f4960;
    border-radius: 9px;
}

QLabel#HomeGreeting {
    color: #ffffff;
    font-size: 22pt;
    font-weight: 800;
}

QLabel#HomePlaceholder {
    color: #8fa9bb;
    background-color: #172536;
    border: 1px dashed #355269;
    border-radius: 9px;
    padding: 14px;
}

QLabel#HomeListText {
    color: #d8e3ec;
    background-color: #172536;
    border-radius: 8px;
    padding: 10px 12px;
}

QPushButton#HomeListButton {
    background-color: #172536;
    border: 1px solid #2f4960;
    border-radius: 8px;
    color: #edf4f8;
    padding: 8px 12px;
    text-align: left;
}

QPushButton#HomeListButton:hover {
    background-color: #263f55;
    border-color: #4e83a7;
}
"""


# P3.0 最終デザインガイド。既存画面の個別指定より後で適用する。
STYLE += """
QWidget {
    background-color: #0f1720;
    color: #e7eef4;
    font-family: "Yu Gothic UI";
    font-size: 10pt;
}

QFrame#ContentPanel {
    background-color: #162534;
    border: 1px solid #263e52;
    border-radius: 12px;
}

QFrame#SettingsCard, QFrame#ProductCard, QFrame#DashboardCard,
QFrame#HomeSectionCard, QFrame#HomeSummaryCard, QFrame#GlobalSearchResults {
    background-color: #1b2d3d;
    border: 1px solid #304b60;
    border-radius: 12px;
}

QFrame#SiteRow, QFrame#HomeSummaryItem, QFrame#TopBar,
QLabel#DashboardStatusBar, QLabel#HomeListText {
    background-color: #13212e;
    border: 1px solid #263f53;
    border-radius: 8px;
}

QLabel#PageTitle, QLabel#HomeGreeting {
    color: #ffffff;
    font-size: 21pt;
    font-weight: 800;
}

QLabel#SectionTitle, QLabel#ProductName {
    color: #f5f8fa;
    font-size: 13pt;
    font-weight: 750;
}

QLabel#MutedText, QLabel#VersionLabel, QLabel#FooterStatus {
    color: #9eb0be;
}

QPushButton {
    icon-size: 18px;
    min-height: 38px;
    background-color: #29485f;
    color: #f6f9fb;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0 14px;
    font-size: 10pt;
}

QPushButton:hover {
    background-color: #376985;
    border-color: #5a91b2;
}

QPushButton:pressed, QPushButton[busy="true"] {
    background-color: #1f3b4f;
    color: #b9c7d1;
}

QPushButton:disabled {
    background-color: #1b2a36;
    color: #677b8b;
    border-color: #263a49;
}

QPushButton#SmallButton, QToolButton {
    min-height: 32px;
    border-radius: 7px;
    padding: 0 10px;
}

QPushButton#AccentButton {
    background-color: #66c0f4;
    color: #0b1720;
    font-weight: 800;
}

QPushButton#AccentButton:hover {
    background-color: #8fd3f8;
    border-color: #bce6fc;
}

QPushButton#DangerButton, QPushButton#ExitButton {
    background-color: #71333d;
    color: #fff3f4;
}

QPushButton#DangerButton:hover, QPushButton#ExitButton:hover {
    background-color: #93424f;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit,
QDateTimeEdit, QTextEdit, QPlainTextEdit {
    min-height: 36px;
    background-color: #111f2b;
    color: #f0f5f8;
    border: 1px solid #304b60;
    border-radius: 7px;
    padding: 0 10px;
    selection-background-color: #39779b;
}

QTextEdit, QPlainTextEdit {
    padding: 9px 10px;
}

QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus,
QSpinBox:focus, QDateEdit:focus, QListView:focus, QTableView:focus,
QTreeView:focus, QCheckBox:focus, QRadioButton:focus {
    border: 2px solid #66c0f4;
    outline: none;
}

QCheckBox, QRadioButton {
    spacing: 8px;
    min-height: 28px;
}

QListWidget, QTableWidget, QTreeWidget, QListView, QTableView, QTreeView {
    background-color: #111f2b;
    alternate-background-color: #162938;
    color: #e7eef4;
    border: 1px solid #304b60;
    border-radius: 8px;
    gridline-color: #2a4356;
    selection-background-color: #315f7a;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #1d3445;
    color: #dbe7ee;
    border: none;
    border-right: 1px solid #304b60;
    border-bottom: 1px solid #304b60;
    padding: 8px 10px;
    font-weight: 700;
}

QProgressBar {
    min-height: 18px;
    background-color: #111f2b;
    color: #ffffff;
    border: 1px solid #304b60;
    border-radius: 7px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #66c0f4;
    border-radius: 6px;
}

QLabel[state="success"], QLabel#StatusOpen {
    color: #75d58a;
}

QLabel#StatusActive {
    color: #66c0f4;
}

QLabel[state="warning"], QLabel#StatusLottery {
    color: #ffd166;
}

QLabel[state="error"], QLabel#WarningText, QLabel#StatusClosed {
    color: #ff7f87;
}

QLabel#PageText, QLabel#HomePlaceholder, QLabel#GlobalSearchEmpty {
    color: #a9bac7;
}

QToolTip {
    background-color: #243b4d;
    color: #ffffff;
    border: 1px solid #66c0f4;
    border-radius: 5px;
    padding: 6px 8px;
}

QFrame#OwnerEditionBanner {
    background-color: #6f2832;
    border-bottom: 2px solid #ffd166;
}

QFrame#OwnerEditionBanner QLabel {
    background: transparent;
    color: #ffffff;
    font-weight: 800;
}

QScrollBar:vertical, QScrollBar:horizontal {
    background: #0d1821;
    border: none;
    margin: 2px;
    border-radius: 5px;
}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #3c6882;
    min-height: 30px;
    min-width: 30px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #5790af;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui.application_dashboard_page import SourceInventorySection


class MonitoringCandidatePage(QFrame):
    """Monitoring inventory kept separate from confirmed application cards."""

    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("MonitoringCandidatePageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.page_scroll)

        content = QWidget()
        content.setObjectName("MonitoringCandidatePageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        title = QLabel("監視候補店舗 / 情報確認状況")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        note = QLabel(
            "応募案件一覧ではありません。保存済み情報から、確認中・現在応募なしを含む監視候補を表示します。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.inventory = SourceInventorySection(show_heading=False)
        layout.addWidget(self.inventory, 1)
        self.page_scroll.setWidget(content)

    def reload(self, report: dict | None = None):
        self.inventory.reload(report)

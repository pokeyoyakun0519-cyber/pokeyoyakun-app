from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.phase3_dashboard import ApplicationStatistics
from core.product_store import ProductStore


class StatisticsPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.store = ProductStore()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel("応募統計")
        title.setObjectName("PageTitle")
        refresh = QPushButton("統計を更新")
        refresh.setObjectName("AccentButton")
        refresh.clicked.connect(self.reload)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

        self.summary_grid = QGridLayout()
        self.summary_labels = {}
        for index, key in enumerate(("total", "wins", "losses", "waiting", "win_rate")):
            card = QFrame()
            card.setObjectName("DashboardCard")
            card_layout = QVBoxLayout(card)
            title_label = QLabel({"total": "応募総数", "wins": "当選数", "losses": "落選数", "waiting": "結果待ち", "win_rate": "当選率"}[key])
            value = QLabel("-")
            value.setObjectName("DashboardCardValue")
            card_layout.addWidget(title_label)
            card_layout.addWidget(value)
            self.summary_labels[key] = value
            self.summary_grid.addWidget(card, 0, index)
        layout.addLayout(self.summary_grid)
        self.reference = QLabel("")
        self.reference.setObjectName("WarningText")
        layout.addWidget(self.reference)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)
        self.reload()

    def reload(self):
        data = ApplicationStatistics().build(self.store.load_products())
        for key in ("total", "wins", "losses", "waiting"):
            self.summary_labels[key].setText(f'{data[key]}件')
        self.summary_labels["win_rate"].setText("-" if data["win_rate"] is None else f'{data["win_rate"]:.1f}%')
        self.reference.setText("データが少ないため参考値です。" if data["reference"] else "結果確定済みデータによる集計です。結果待ちは当選率の分母に含めません。")
        container = QWidget()
        sections = QVBoxLayout(container)
        for title, key in (("店舗別", "by_store"), ("TCG別", "by_tcg"), ("商品別", "by_product"), ("月別", "by_month")):
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            sections.addWidget(label)
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels([title.removesuffix("別"), "応募", "当選", "落選"])
            table.setRowCount(len(data[key]))
            for row, item in enumerate(data[key]):
                for column, value in enumerate((item["label"], item["total"], item["wins"], item["losses"])):
                    table.setItem(row, column, QTableWidgetItem(str(value)))
            table.setMinimumHeight(min(260, 70 + len(data[key]) * 30))
            sections.addWidget(table)
        sections.addStretch()
        self.scroll.setWidget(container)

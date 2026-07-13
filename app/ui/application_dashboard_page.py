import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.application_dashboard import ApplicationDashboard
from core.lottery_manager import LotteryManager
from core.product_store import ProductStore


class ApplicationRow(QFrame):
    def __init__(
        self,
        row: dict,
        store: ProductStore,
        reload_callback,
        applied_callback,
    ):
        super().__init__()
        self.row = row
        self.store = store
        self.reload_callback = reload_callback
        self.applied_callback = applied_callback
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            13,
            16,
            13,
        )
        layout.setSpacing(8)

        header = QHBoxLayout()

        title = QLabel(
            row.get(
                "product_name",
                "商品名未設定",
            )
        )
        title.setObjectName("ProductName")
        title.setWordWrap(True)

        state = QLabel(
            row.get(
                "application_state",
                "未応募",
            )
        )
        state.setObjectName(
            self._status_object_name(
                row.get(
                    "application_state",
                    "",
                )
            )
        )

        open_button = QPushButton(
            "応募・確認ページを開く"
        )
        open_button.setObjectName(
            "SmallButton"
        )
        open_button.clicked.connect(
            self._open_page
        )

        header.addWidget(title, 1)
        header.addWidget(state)
        header.addWidget(open_button)
        layout.addLayout(header)

        store_info = QLabel(
            f'店舗：{row.get("site_name", "店舗名未設定")}　'
            f'発売日：{row.get("release_date") or "未設定"}'
        )
        store_info.setObjectName("MutedText")
        layout.addWidget(store_info)

        schedule = QLabel(
            "応募期間："
            + (
                row.get("application_period")
                or "未取得"
            )
            + "　結果発表："
            + (
                row.get("result_date")
                or "未取得"
            )
            + "　購入期限："
            + (
                row.get("order_period")
                or "未取得"
            )
        )
        schedule.setObjectName("MutedText")
        schedule.setWordWrap(True)
        layout.addWidget(schedule)

        controls = QHBoxLayout()

        applied_button = QPushButton(
            "応募済みにする"
            if row.get("application_state") == "未応募"
            else "応募状態を解除"
        )
        applied_button.clicked.connect(
            self._toggle_applied
        )

        result = QComboBox()
        result.addItems(
            ["未確認", "当選", "落選"]
        )
        index = result.findText(
            row.get(
                "result_status",
                "未確認",
            )
        )
        if index >= 0:
            result.setCurrentIndex(index)
        result.currentTextChanged.connect(
            self._save_result
        )

        controls.addWidget(applied_button)
        controls.addWidget(QLabel("抽選結果："))
        controls.addWidget(result)
        controls.addStretch()

        layout.addLayout(controls)

    def _toggle_applied(self):
        currently_applied = (
            self.row.get("application_state")
            != "未応募"
        )
        new_applied = not currently_applied

        self.store.save_site_application_state(
            str(self.row.get("product_id", "")),
            str(self.row.get("site_key", "")),
            str(self.row.get("site_url", "")),
            new_applied,
        )

        if new_applied:
            self.applied_callback(self.row)
            return

        self.reload_callback()

    def _save_result(self, value: str):
        self.store.save_site_result(
            str(self.row.get("product_id", "")),
            str(self.row.get("site_key", "")),
            str(self.row.get("site_url", "")),
            value,
        )
        if value in {"当選", "落選"}:
            self.reload_callback()

    def _open_page(self):
        url = self.row.get("site_url", "")
        if url:
            webbrowser.open(url)

    @staticmethod
    def _status_object_name(
        status: str,
    ) -> str:
        if status in {
            "当選",
            "抽選受付完了",
        }:
            return "StatusOpen"
        if status == "抽選結果確認":
            return "StatusLottery"
        if status == "落選":
            return "StatusClosed"
        return "StatusOther"


class ApplicationDashboardPage(QFrame):
    open_lottery_page = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.dashboard = ApplicationDashboard()
        self.store = ProductStore()
        self.lottery_manager = LotteryManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("応募ダッシュボード")
        title.setObjectName("PageTitle")

        refresh = QPushButton("再読込")
        refresh.setObjectName("AccentButton")
        refresh.clicked.connect(self.reload)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

        self.summary = QLabel("")
        self.summary.setObjectName("SectionTitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        description = QLabel(
            "商品一覧にある店舗ごとの応募状況をまとめて表示します。"
            "結果確認日が来たものを上に表示し、"
            "当選・落選もここから記録できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("表示："))
        self.state_filter = QComboBox()
        self.state_filter.addItems(
            [
                "すべて",
                "未応募",
                "抽選受付完了",
                "抽選結果確認",
                "当選",
                "落選",
            ]
        )
        self.state_filter.currentTextChanged.connect(
            self.reload
        )

        filter_row.addWidget(self.state_filter)

        filter_row.addWidget(QLabel("並び順："))
        self.sort_mode = QComboBox()
        self.sort_mode.addItems(
            [
                "優先度順",
                "応募締切順",
                "結果発表順",
                "発売日順",
                "店舗名順",
            ]
        )
        self.sort_mode.currentTextChanged.connect(
            self.reload
        )
        filter_row.addWidget(self.sort_mode)

        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText(
            "商品名・店舗名で検索"
        )
        self.keyword.textChanged.connect(
            self.reload
        )
        filter_row.addWidget(self.keyword, 1)

        layout.addLayout(filter_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload()


    def _on_marked_applied(
        self,
        row: dict,
    ) -> None:
        product_name = str(
            row.get(
                "product_name",
                "商品名未設定",
            )
        )
        site_name = str(
            row.get(
                "site_name",
                "店舗名未設定",
            )
        )
        site_url = str(
            row.get(
                "site_url",
                "",
            )
        )

        self.lottery_manager.add_item(
            product_name,
            site_name,
            site_url,
        )

        self.reload()
        self.open_lottery_page.emit()

    def reload(self):
        data = self.dashboard.build(
            state_filter=self.state_filter.currentText(),
            sort_mode=self.sort_mode.currentText(),
            keyword=self.keyword.text(),
        )
        counts = data["counts"]

        self.summary.setText(
            f'未応募 {counts["未応募"]}件　'
            f'応募済み {counts["抽選受付完了"]}件　'
            f'結果確認 {counts["抽選結果確認"]}件　'
            f'当選 {counts["当選"]}件　'
            f'落選 {counts["落選"]}件'
        )

        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        list_layout.setSpacing(12)

        rows = data["rows"]
        self.summary.setText(
            self.summary.text()
            + f'　表示 {len(rows)}/{data["total_rows"]}件'
        )

        if not rows:
            empty = QLabel(
                "応募管理できる販売・抽選情報がありません。"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        else:
            for row in rows:
                list_layout.addWidget(
                    ApplicationRow(
                        row,
                        self.store,
                        self.reload,
                        self._on_marked_applied,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.product_store import ProductStore
from core.safe_product_url import can_open_product_url, open_product_url
from core.tcg_categories import display_name
from ui.product_detail_dialog import ProductDetailDialog
from ui.tcg_category_tabs import (
    TcgCategoryTabs,
    category_counts,
    filter_items_by_category,
)


class ProductCard(QFrame):
    def __init__(
        self,
        product: dict,
        store: ProductStore,
        detail_callback,
        reload_callback,
    ):
        super().__init__()
        self.product = product
        self.store = store
        self.detail_callback = detail_callback
        self.reload_callback = reload_callback
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        title = QLabel(
            f'{display_name(product.get("tcg_key"), product.get("tcg"))}  ｜  {product["name"]}'
        )
        title.setObjectName("ProductName")
        title.setWordWrap(True)

        status = QLabel(product["status"])
        status.setObjectName(
            self._status_object_name(product["status"])
        )

        detail_button = QPushButton("詳細を見る")
        detail_button.setObjectName("AccentButton")
        detail_button.clicked.connect(
            lambda: self.detail_callback(self.product)
        )

        top_row.addWidget(title, 1)
        top_row.addWidget(status)
        top_row.addWidget(detail_button)

        release_date = QLabel(
            f'発売日：{product["release_date"]}'
        )
        release_date.setObjectName("MutedText")

        layout.addLayout(top_row)
        layout.addWidget(release_date)
        reference_price = product.get("reference_price") or product.get("msrp")
        price_label = QLabel(
            f'定価：{int(reference_price):,}円'
            if isinstance(reference_price, (int, float)) and reference_price > 0
            else "定価：価格未確認"
        )
        price_label.setObjectName("MutedText")
        layout.addWidget(price_label)

        for site in product.get("sites", []):
            layout.addWidget(
                self._make_site_row(site)
            )

    def _make_site_row(self, site: dict) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SiteRow")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()

        site_name = QLabel(
            f'{site.get("name", "店舗")}：'
            f'{site.get("status", "情報あり")}'
        )

        state = QLabel(
            site.get("application_state", "未応募")
        )
        state.setObjectName(
            self._status_object_name(
                site.get("application_state", "")
            )
        )

        open_button = QPushButton("応募・商品ページを開く")
        open_button.setObjectName("SmallButton")
        open_button.setEnabled(can_open_product_url(site.get("url", "")))
        open_button.clicked.connect(
            lambda checked=False, url=site.get("url", ""):
            self._open_url(url)
        )

        header.addWidget(site_name)
        header.addStretch()
        header.addWidget(state)
        header.addWidget(open_button)
        layout.addLayout(header)

        sale_price = site.get("sale_price")
        price_text = (
            f'販売価格：{int(sale_price):,}円'
            if isinstance(sale_price, (int, float)) and sale_price > 0
            else "販売価格：価格未確認"
        )
        seller_text = str(site.get("seller", "販売元未確認"))
        retail_price = QLabel(price_text + "　販売元：" + seller_text)
        retail_price.setObjectName("MutedText")
        layout.addWidget(retail_price)

        notice = site.get("notice", "").strip()
        if notice:
            notice_label = QLabel(notice)
            notice_label.setObjectName("WarningText")
            notice_label.setWordWrap(True)
            layout.addWidget(notice_label)

        method = site.get("application_method", "")
        if method:
            method_label = QLabel(
                "応募方法：" + method
            )
            method_label.setObjectName("MutedText")
            layout.addWidget(method_label)

        workflow = QHBoxLayout()

        applied = QCheckBox("応募・予約受付完了")
        applied.setChecked(bool(site.get("applied", False)))
        applied.toggled.connect(
            lambda checked, current=site:
            self._save_applied(current, checked)
        )

        result_combo = QComboBox()
        result_combo.addItems(
            ["未確認", "当選", "落選"]
        )
        current_result = str(
            site.get("result_status", "未確認")
        )
        index = result_combo.findText(current_result)
        if index >= 0:
            result_combo.setCurrentIndex(index)
        result_combo.setEnabled(
            bool(site.get("applied", False))
        )
        result_combo.currentTextChanged.connect(
            lambda value, current=site:
            self._save_result(current, value)
        )

        result_date = QLabel(
            "結果発表："
            + (
                site.get("result_date")
                or "日付未取得"
            )
        )
        result_date.setObjectName("MutedText")

        workflow.addWidget(applied)
        workflow.addWidget(QLabel("抽選結果："))
        workflow.addWidget(result_combo)
        workflow.addStretch()
        workflow.addWidget(result_date)
        layout.addLayout(workflow)

        if (
            site.get("application_state")
            == "抽選結果確認"
        ):
            reminder = QLabel(
                "結果確認日です。アプリまたは会員ページを開き、"
                "確認後に「当選」「落選」を選択してください。"
            )
            reminder.setObjectName("WarningText")
            reminder.setWordWrap(True)
            layout.addWidget(reminder)

        return frame

    def _save_applied(
        self,
        site: dict,
        checked: bool,
    ) -> None:
        self.store.save_site_application_state(
            str(self.product.get("id", "")),
            str(site.get("site_key", "")),
            str(site.get("url", "")),
            checked,
        )
        self.reload_callback()

    def _save_result(
        self,
        site: dict,
        value: str,
    ) -> None:
        self.store.save_site_result(
            str(self.product.get("id", "")),
            str(site.get("site_key", "")),
            str(site.get("url", "")),
            value,
        )
        if value in {"当選", "落選"}:
            self.reload_callback()

    @staticmethod
    def _open_url(url: str) -> None:
        open_product_url(url)

    @staticmethod
    def _status_object_name(status: str) -> str:
        if "当選" in status or "受付完了" in status:
            return "StatusOpen"
        if "抽選" in status or "結果確認" in status:
            return "StatusLottery"
        if "終了" in status or "落選" in status:
            return "StatusClosed"
        return "StatusOther"


class ProductPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.store = ProductStore()
        self.log_manager = LogManager()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        self.main_layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("商品一覧")
        title.setObjectName("PageTitle")

        self.last_updated = QLabel()
        self.last_updated.setObjectName("MutedText")

        reload_button = QPushButton("一覧を再読込")
        reload_button.setObjectName("AccentButton")
        reload_button.clicked.connect(
            self.reload_saved_products
        )

        reset_button = QPushButton(
            "応募・結果状態をリセット"
        )
        reset_button.clicked.connect(
            self.reset_application_checks
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.last_updated)
        header.addWidget(reload_button)
        header.addWidget(reset_button)
        self.main_layout.addLayout(header)

        description = QLabel(
            "店舗ごとの「応募・予約受付完了」にチェックすると、"
            "結果発表日までは「抽選受付完了」、"
            "結果日以降は「抽選結果確認」と表示します。"
            "アプリ・会員ページ型の抽選結果は、確認後に当選・落選を選択します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        self.main_layout.addWidget(description)

        self.category_tabs = TcgCategoryTabs()
        self.category_tabs.category_changed.connect(self._apply_category_filter)
        self.main_layout.addWidget(self.category_tabs)
        self._all_products: list[dict] = []

        self.result_label = QLabel("")
        self.result_label.setObjectName("MutedText")
        self.result_label.setWordWrap(True)
        self.main_layout.addWidget(self.result_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.main_layout.addWidget(self.scroll)

        self.reload_saved_products()

    def reload_saved_products(self) -> None:
        products = self.store.load_products()
        self._all_products = products
        self.category_tabs.set_counts(category_counts(products))
        self.result_label.setText(
            "保存済みの商品・販売情報を読み込みました。"
        )
        self._apply_category_filter(self.category_tabs.selected_key)
        self._update_timestamp()

    def _apply_category_filter(self, category_key: str) -> None:
        self._show_products(
            list(filter_items_by_category(self._all_products, category_key))
        )

    def _show_products(
        self,
        products: list[dict],
    ) -> None:
        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        if not products:
            empty = QLabel(
                "表示できる商品がありません。\n"
                "新弾候補の販売・抽選情報検索で情報が見つかると追加されます。"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        else:
            for product in products:
                list_layout.addWidget(
                    ProductCard(
                        product,
                        self.store,
                        self.open_product_detail,
                        self.reload_saved_products,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

    def open_product_detail(
        self,
        product: dict,
    ) -> None:
        ProductDetailDialog(
            product,
            self,
        ).exec()

    def _update_timestamp(self) -> None:
        self.last_updated.setText(
            "最終更新："
            + datetime.now().strftime(
                "%Y/%m/%d %H:%M:%S"
            )
        )

    def reset_application_checks(self) -> None:
        answer = QMessageBox.question(
            self,
            "応募状態のリセット",
            "すべての応募・抽選結果状態をリセットしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            state = self.store._load_user_state()
            state["site_applications"] = {}
            self.store._save_user_state(state)
            self.log_manager.write(
                "応募・抽選結果状態をリセットしました。"
            )
            self.reload_saved_products()

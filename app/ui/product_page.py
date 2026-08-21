from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.startup_diagnostics import StartupDiagnostics
from core.data_pipeline_diagnostics import DataPipelineDiagnostics
from core.favorites_manager import FavoritesManager
from core.phase3_dashboard import is_new, product_priority
from core.product_store import ProductStore
from core.product_record_policy import product_records
from core.tcg_categories import categories, display_name
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
        self.favorites = FavoritesManager(getattr(store, "root", None))
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
        priority = product_priority(product)
        priority_label = QLabel(f'{priority["stars"]} {priority["label"]}')
        priority_label.setObjectName("MutedText")
        top_row.addWidget(priority_label)
        if is_new(product.get("created_at")):
            new_label = QLabel("NEW")
            new_label.setObjectName("StatusOpen")
            top_row.addWidget(new_label)
        top_row.addWidget(status)
        favorite_button = QPushButton("★ お気に入り" if self.favorites.is_favorite("product", product.get("product_id", product.get("id"))) else "☆ お気に入り")
        favorite_button.setCheckable(True)
        favorite_button.setChecked(self.favorites.is_favorite("product", product.get("product_id", product.get("id"))))
        favorite_button.clicked.connect(lambda checked: self._toggle_favorite(checked))
        top_row.addWidget(favorite_button)
        if product.get("auto_monitored"):
            remove_auto_button = QPushButton("自動監視を解除")
            remove_auto_button.setObjectName("DangerButton")
            remove_auto_button.clicked.connect(self._exclude_auto_monitor)
            top_row.addWidget(remove_auto_button)
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

    def _exclude_auto_monitor(self) -> None:
        if self.store.exclude_auto_monitored_product(str(self.product.get("id", ""))):
            self.reload_callback()

    def _toggle_favorite(self, enabled: bool) -> None:
        self.favorites.set_favorite(
            "product", self.product.get("product_id", self.product.get("id", "")), enabled
        )
        self.reload_callback()

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
        self.favorites = FavoritesManager(self.store.root)
        self.log_manager = LogManager()
        self.startup_diagnostics = StartupDiagnostics()
        self._last_diagnostic_signature = None

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

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.last_updated)
        header.addWidget(reload_button)
        self.main_layout.addLayout(header)

        description = QLabel(
            "ここではカード商品だけを確認できます。"
            "店舗ごとの抽選・予約・販売情報は「応募ダッシュボード」で確認してください。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        self.main_layout.addWidget(description)

        self.category_tabs = TcgCategoryTabs()
        self.category_tabs.category_changed.connect(self._apply_category_filter)
        self.main_layout.addWidget(self.category_tabs)
        self.favorite_only = QCheckBox("お気に入りだけ表示")
        self.favorite_only.toggled.connect(lambda _checked: self._apply_category_filter(self.category_tabs.selected_key))
        self.main_layout.addWidget(self.favorite_only)
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
        saved_products = self.store.load_products()
        products = product_records(saved_products)
        self._all_products = products
        details = self.store.last_load_diagnostics
        pipeline = DataPipelineDiagnostics(self.store.root).build(
            visible_products=products
        )
        pipeline_signature = tuple(
            (
                item.key,
                tuple(sorted(
                    (
                        key,
                        tuple(sorted(value.items()))
                        if isinstance(value, dict)
                        else value,
                    )
                    for key, value in pipeline["by_tcg"][item.key].items()
                )),
            )
            for item in categories()
        )
        signature = (
            details.get("raw_count", 0),
            details.get("visible_count", 0),
            tuple(sorted(details.get("per_tcg", {}).items())),
            pipeline_signature,
        )
        if signature != self._last_diagnostic_signature:
            self._last_diagnostic_signature = signature
            self.startup_diagnostics.write(
                "Loaded products: "
                f'raw={details.get("raw_count", 0)} '
                f'normalized={details.get("normalized_count", 0)} '
                f'available={details.get("visible_count", 0)} '
                f'path={details.get("storage_path", self.store.products_path)}'
            )
            tcg_counts = details.get("per_tcg", {})
            self.startup_diagnostics.write(
                "Loaded products by TCG: "
                + " ".join(
                    f"{item.key}={tcg_counts.get(item.key, 0)}"
                    for item in categories()
                )
            )
            self.startup_diagnostics.write(
                "Product UI input: "
                f'{len(products)} excluded_products='
                f'{len(details.get("excluded_products", []))} '
                "excluded_retail_offers="
                f'{len(details.get("excluded_retail_offers", []))}'
            )
            for line in DataPipelineDiagnostics.format_lines(pipeline):
                self.startup_diagnostics.write(line)
        self.category_tabs.set_counts(category_counts(products))
        self.result_label.setText(
            f"保存済み商品のうち商品 {len(products)}件を表示します。"
        )
        self._apply_category_filter(self.category_tabs.selected_key)
        self._update_timestamp()

    def _apply_category_filter(self, category_key: str) -> None:
        before_filters = len(self._all_products)
        products = list(filter_items_by_category(self._all_products, category_key))
        if self.favorite_only.isChecked():
            favorite_ids = set(self.favorites.load()["products"])
            products = [item for item in products if str(item.get("product_id", item.get("id", ""))) in favorite_ids]
        products.sort(key=lambda item: (-product_priority(item)["level"], str(item.get("release_date", "9999-99-99")), str(item.get("name", ""))))
        self.startup_diagnostics.write(
            "Product UI display: "
            f"category={category_key} before={before_filters} "
            f"after_filters={len(products)}"
        )
        self._show_products(products)

    def _show_products(
        self,
        products: list[dict],
    ) -> None:
        self.startup_diagnostics.write(
            f"Product UI render: count={len(products)}"
        )
        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        if not products:
            empty = QLabel(
                "表示できる商品がありません。\n"
                "公式商品情報が見つかると追加されます。"
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

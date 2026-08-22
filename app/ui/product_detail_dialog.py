from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout,
)

from core.favorites_manager import FavoritesManager
from core.product_image_cache import ProductImageCache
# Kept as an import-compatible seam for existing extensions/tests; store data is
# intentionally no longer rendered in this product-only dialog.
from core.site_master_manager import SiteMasterManager
from core.safe_product_url import can_open_product_url, open_product_url
from core.tcg_categories import display_name


class ProductDetailDialog(QDialog):
    """商品そのものの公式情報を表示する画面。"""

    def __init__(self, product: dict, parent=None):
        super().__init__(parent)
        self.product = product
        self.favorites = FavoritesManager()
        self.image_cache = ProductImageCache()

        self.setWindowTitle(f'{product.get("name", "商品詳細")} - ポケヨヤ君')
        self.resize(820, 650)
        self.setMinimumSize(680, 520)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(self.product.get("name", "名称未設定"))
        title.setObjectName("PageTitle")
        title.setWordWrap(True)

        status = QLabel(self.product.get("status", "状態不明"))
        status.setObjectName(self._status_object_name(self.product.get("status", "")))

        header.addWidget(title, 1)
        header.addWidget(status)
        root.addLayout(header)

        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        image_url = str(self.product.get("image_url", self.product.get("product_image_url", "")))
        image_version = str(self.product.get("image_version", self.product.get("image_updated_at", "")))
        cached = self.image_cache.cached_path(
            self.product.get("product_id", self.product.get("id", "")), image_url,
            version=image_version,
        )
        if cached:
            self._show_image(cached)
            root.addWidget(self.image_label)
        elif image_url:
            image_button = QPushButton("商品画像を取得")
            image_button.setObjectName("SmallButton")
            image_button.clicked.connect(lambda: self._load_image(image_url, image_version, image_button))
            root.addWidget(image_button)
            root.addWidget(self.image_label)

        info = QLabel(
            f'TCG：{display_name(self.product.get("tcg_key"), self.product.get("tcg"))}\n'
            f'発売日：{self.product.get("release_date", "未設定")}'
        )
        info.setObjectName("PageText")
        root.addWidget(info)

        flags = QHBoxLayout()
        reserved = QCheckBox("予約済み")
        reserved.setChecked(bool(self.product.get("reserved", False)))
        reserved.setEnabled(False)
        favorite = QCheckBox("お気に入り")
        product_id = self.product.get("product_id", self.product.get("id", ""))
        favorite.setChecked(self.favorites.is_favorite("product", product_id))
        favorite.toggled.connect(lambda enabled: self.favorites.set_favorite("product", product_id, enabled))
        flags.addWidget(reserved); flags.addWidget(favorite); flags.addStretch()
        root.addLayout(flags)

        official_url = str(self.product.get("official_url", ""))
        official_button = QPushButton("公式商品ページを開く")
        official_button.setObjectName("AccentButton")
        official_button.setEnabled(can_open_product_url(official_url))
        official_button.clicked.connect(lambda: open_product_url(official_url))
        root.addWidget(official_button)
        note = QLabel("店舗ごとの抽選・予約・販売情報は「応募ダッシュボード」で確認できます。")
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)
        close_row = QHBoxLayout(); close_row.addStretch()
        close_button = QPushButton("閉じる"); close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button); root.addLayout(close_row)

    def _load_image(self, image_url: str, version: str, button: QPushButton) -> None:
        try:
            path = self.image_cache.get(
                self.product.get("product_id", self.product.get("id", "")),
                image_url,
                version=version,
            )
        except (OSError, ValueError):
            path = None
        if path:
            self._show_image(path)
            button.setVisible(False)
        else:
            button.setText("画像を取得できませんでした")
            button.setEnabled(False)

    def _show_image(self, path) -> None:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap.scaled(360, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @staticmethod
    def _status_object_name(status: str) -> str:
        if "予約受付中" in status or "当選" in status: return "StatusOpen"
        if "抽選" in status or "結果待ち" in status: return "StatusLottery"
        if "終了" in status or "落選" in status: return "StatusClosed"
        return "StatusOther"

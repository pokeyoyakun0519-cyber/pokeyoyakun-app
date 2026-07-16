import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.site_master_manager import SiteMasterManager
from core.tcg_categories import display_name


class ProductDetailDialog(QDialog):
    """商品1件の詳細と、販売サイトごとの条件を表示する画面。"""

    def __init__(self, product: dict, parent=None):
        super().__init__(parent)
        self.product = product
        self.site_master = SiteMasterManager()

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
        favorite.setChecked(bool(self.product.get("favorite", False)))
        favorite.setEnabled(False)
        flags.addWidget(reserved); flags.addWidget(favorite); flags.addStretch()
        root.addLayout(flags)

        section = QLabel("販売サイト")
        section.setObjectName("SectionTitle")
        root.addWidget(section)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget(); list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0); list_layout.setSpacing(12)

        site_master_map = {site.get("id"): site for site in self.site_master.load_sites()}
        product_sites = self.product.get("sites", [])
        if not product_sites:
            empty = QLabel("販売サイト情報はまだありません。")
            empty.setAlignment(Qt.AlignCenter); empty.setObjectName("MutedText")
            list_layout.addWidget(empty)
        else:
            for site in product_sites:
                master = site_master_map.get(site.get("site_key", ""), {})
                list_layout.addWidget(self._make_site_card(site, master))

        list_layout.addStretch(); scroll.setWidget(container); root.addWidget(scroll, 1)
        close_row = QHBoxLayout(); close_row.addStretch()
        close_button = QPushButton("閉じる"); close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button); root.addLayout(close_row)

    def _make_site_card(self, site: dict, master: dict) -> QFrame:
        card = QFrame(); card.setObjectName("ProductCard")
        layout = QVBoxLayout(card); layout.setContentsMargins(16, 14, 16, 14); layout.setSpacing(8)
        header = QHBoxLayout()
        name = QLabel(site.get("name", master.get("name", "サイト名未設定"))); name.setObjectName("ProductName")
        status_text = site.get("status", "状態不明")
        status = QLabel(status_text); status.setObjectName(self._status_object_name(status_text))
        url = site.get("url", "")
        open_button = QPushButton("商品ページを開く"); open_button.setObjectName("SmallButton")
        open_button.setEnabled(bool(url)); open_button.clicked.connect(lambda: webbrowser.open(url) if url else None)
        header.addWidget(name); header.addStretch(); header.addWidget(status); header.addWidget(open_button)
        layout.addLayout(header)

        sales_type = master.get("sales_type")
        if sales_type:
            sales_label = QLabel(f"販売方式：{sales_type}"); sales_label.setObjectName("MutedText"); layout.addWidget(sales_label)

        warnings = []
        if master.get("purchase_history_required"):
            warnings.append("※注意※ 購入履歴が必要な場合があります。")
        if master.get("membership_required"):
            warnings.append("※注意※ 会員登録が必要です。")
        if master.get("notes", "").strip():
            warnings.append(f'※注意※ {master.get("notes").strip()}')
        if site.get("notice", "").strip():
            warnings.append(site.get("notice").strip())
        if warnings:
            warning = QLabel("\n".join(warnings)); warning.setObjectName("WarningText"); warning.setWordWrap(True)
            layout.addWidget(warning)
        return card

    @staticmethod
    def _status_object_name(status: str) -> str:
        if "予約受付中" in status or "当選" in status: return "StatusOpen"
        if "抽選" in status or "結果待ち" in status: return "StatusLottery"
        if "終了" in status or "落選" in status: return "StatusClosed"
        return "StatusOther"

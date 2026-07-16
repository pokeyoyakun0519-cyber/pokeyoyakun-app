import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.log_manager import LogManager
from core.lottery_manager import LotteryManager
from core.notification_manager import NotificationManager
from core.tcg_categories import display_name


class LotteryCard(QFrame):
    def __init__(self, item: dict, remove_callback):
        super().__init__()
        self.item = item
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()

        title = QLabel(
            f'{display_name(item.get("tcg_key"), item.get("tcg"))} ｜ '
            f'{item.get("product_name", "商品名未設定")}  ｜  '
            f'{item.get("site_name", "サイト名未設定")}'
        )
        title.setObjectName("ProductName")

        status = QLabel(item.get("status", "未確認"))
        status.setObjectName(self._status_object_name(item.get("status", "")))

        open_button = QPushButton("結果ページを開く")
        open_button.setObjectName("SmallButton")
        open_button.clicked.connect(
            lambda: webbrowser.open(item.get("url", ""))
        )

        remove_button = QPushButton("削除")
        remove_button.setObjectName("DangerButton")
        remove_button.clicked.connect(
            lambda: remove_callback(item.get("id", ""))
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(status)
        header.addWidget(open_button)
        header.addWidget(remove_button)

        url_label = QLabel(item.get("url", ""))
        url_label.setObjectName("MutedText")
        url_label.setWordWrap(True)

        checked = QLabel(
            "最終確認：" + (item.get("last_checked") or "未確認")
        )
        checked.setObjectName("MutedText")

        page_title = QLabel(
            "ページタイトル：" + (item.get("last_title") or "未取得")
        )
        page_title.setWordWrap(True)

        matched = item.get("matched_keyword", "")
        keyword_label = QLabel(
            f"検出キーワード：{matched}" if matched
            else "検出キーワード：なし"
        )
        keyword_label.setObjectName("MutedText")

        layout.addLayout(header)
        layout.addWidget(url_label)
        layout.addWidget(page_title)
        layout.addWidget(keyword_label)
        layout.addWidget(checked)

    @staticmethod
    def _status_object_name(status: str) -> str:
        if status == "当選候補":
            return "StatusOpen"
        if status == "落選候補":
            return "StatusClosed"
        if status == "結果待ち候補":
            return "StatusLottery"
        return "StatusOther"


class LotteryPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.manager = LotteryManager()
        self.log_manager = LogManager()
        self.notification_manager = NotificationManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("抽選結果確認")
        title.setObjectName("PageTitle")

        check_button = QPushButton("登録ページを手動確認")
        check_button.setObjectName("AccentButton")
        check_button.clicked.connect(self.check_all)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(check_button)
        layout.addLayout(header)

        description = QLabel(
            "応募済みの商品はこの画面へ追加されます。"
            "Gmail連携済みの場合はメール件名・本文・送信元から"
            "商品名、店舗名、当選・落選を照合して反映します。"
            "Web結果ページの手動確認も補助機能として利用できます。"
            "ログインが必要なページ、CAPTCHA、メールのみの結果通知には対応しません。"
            "表示はあくまで候補なので、必ず公式ページで最終確認してください。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        add_card = QFrame()
        add_card.setObjectName("SettingsCard")
        add_layout = QVBoxLayout(add_card)

        add_title = QLabel("抽選結果ページを登録")
        add_title.setObjectName("SectionTitle")

        fields = QHBoxLayout()

        self.product_input = QLineEdit()
        self.product_input.setPlaceholderText("商品名")

        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("サイト名")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("結果ページのURL")

        add_button = QPushButton("登録")
        add_button.clicked.connect(self.add_item)

        fields.addWidget(self.product_input, 1)
        fields.addWidget(self.site_input, 1)
        fields.addWidget(self.url_input, 2)
        fields.addWidget(add_button)

        add_layout.addWidget(add_title)
        add_layout.addLayout(fields)
        layout.addWidget(add_card)

        self.result_label = QLabel("")
        self.result_label.setObjectName("MutedText")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload_items()

    def add_item(self) -> None:
        product = self.product_input.text().strip()
        site = self.site_input.text().strip()
        url = self.url_input.text().strip()

        if not product or not site:
            QMessageBox.warning(
                self,
                "入力不足",
                "商品名とサイト名を入力してください。",
            )
            return

        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self,
                "URLを確認してください",
                "http:// または https:// から始まるURLを入力してください。",
            )
            return

        self.manager.add_item(product, site, url)
        self.log_manager.write(
            f"抽選結果ページを登録しました: {product} / {site}"
        )

        self.product_input.clear()
        self.site_input.clear()
        self.url_input.clear()
        self.reload_items()

    def remove_item(self, item_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "登録を削除",
            "この抽選結果ページを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.manager.remove_item(item_id)
            self.log_manager.write("抽選結果ページを削除しました。")
            self.reload_items()

    def check_all(self) -> None:
        items = self.manager.load_items()

        if not items:
            QMessageBox.information(
                self,
                "登録なし",
                "先に抽選結果ページを登録してください。",
            )
            return

        checked_items, newly_won = self.manager.check_all()

        self.result_label.setText(
            f"{len(checked_items)}件を確認しました。"
            f"新しい当選候補：{len(newly_won)}件"
        )

        self.log_manager.write(
            f"抽選結果を手動確認しました。件数: {len(checked_items)}"
        )

        if newly_won:
            names = "\n".join(
                f'・{item.get("product_name")}（{item.get("site_name")}）'
                for item in newly_won
            )
            self.notification_manager.notify(
                self,
                "当選候補を検知しました",
                f"次の抽選で当選を示す語を検知しました。\n"
                f"必ず公式ページで確認してください。\n\n{names}",
            )

        self.reload_items()

    def reload_items(self) -> None:
        items = self.manager.load_items()

        container = QWidget()
        list_layout = QVBoxLayout(container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        if not items:
            empty = QLabel(
                "抽選結果ページはまだ登録されていません。\n"
                "結果発表があるときに登録してください。"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        else:
            for item in items:
                list_layout.addWidget(
                    LotteryCard(item, self.remove_item)
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

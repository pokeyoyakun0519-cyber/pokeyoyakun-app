from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

class HistoryPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        title = QLabel("更新履歴")
        title.setObjectName("PageTitle")
        text = QLabel(
            "Ver.1.25.0 RC4\n"
            "・User Editionのライセンス接続先を本番APIへ移行\n"
            "・接続失敗時のDNS、TLS、HTTP診断を改善\n\n"
            "Ver.1.25.0 RC3\n"
            "・certifi CAを使う共通TLS検証へ統一\n"
            "・ライセンス、Feedback、Roadmapの証明書検証を修正\n"
            "・CA欠損時の通信拒否とfrozen自己診断を追加\n\n"
            "Ver.1.25.0 RC2\n"
            "・遊戯王OCGカテゴリと商品表示に対応\n"
            "・遊戯王OCG公式の商品情報取得に対応\n"
            "・Gmail抽選結果の遊戯王判定に対応\n"
            "・店舗検索とTCG誤分類防止を強化\n\n"
            "Ver.1.25.0 RC1\n"
            "・HTTPS固定のオンラインライセンス認証を統合\n"
            "・ご意見・ご要望／店舗追加依頼画面を追加\n"
            "・人気要望・開発状況画面を追加\n"
            "・ETag、5分キャッシュ、オフライン表示に対応\n"
            "・User Edition配布物のセキュリティ監査を強化\n\n"
            "Ver.1.23.0 RC\n"
            "・サブスクリプション管理基盤を追加\n"
            "・先行ユーザー月額300円、通常月額500円\n"
            "・ID/PASS方式とPBKDF2ハッシュ保存\n"
            "・1アカウント1PC紐付け基盤\n"
            "・更新、解約、決済失敗イベント処理\n"
            "・解約後90日保持と自動削除\n"
            "・管理画面へサブスク一覧を追加\n"
            "・Stripe接続前のローカル試験Webhookを追加\n\n"
            "Ver.1.22.2 RC\n"
            "・SQLiteロック問題を根本修正"
        )
        text.setObjectName("PageText")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(text)
        layout.addStretch()

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

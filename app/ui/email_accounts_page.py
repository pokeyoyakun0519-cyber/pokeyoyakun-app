import webbrowser
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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

from core.gmail_result_service import GmailResultService
from core.tcg_categories import display_name
from core.email_account_manager import (
    EmailAccountManager,
)


class EmailAccountsPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.manager = EmailAccountManager()
        self.gmail_service = GmailResultService()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        title = QLabel("メールアカウント")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "抽選結果メールを確認するためのアカウントを"
            "最大3件まで登録できます。"
            "Google OAuthでGmailの読取専用アクセスを許可し、"
            "応募済みの商品・店舗に一致する抽選結果メールを検索します。"
            "パスワードは保存せず、最大3アカウントまで利用できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        add_card = QFrame()
        add_card.setObjectName("SettingsCard")
        add_layout = QHBoxLayout(add_card)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(
            "表示名（例：ポケカ用）"
        )
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText(
            "Gmailアドレス"
        )

        self.add_button = QPushButton(
            "アカウントを追加"
        )
        self.add_button.setObjectName(
            "AccentButton"
        )
        self.add_button.clicked.connect(
            self.add_account
        )

        add_layout.addWidget(self.name_input, 1)
        add_layout.addWidget(self.email_input, 2)
        add_layout.addWidget(self.add_button)
        layout.addWidget(add_card)

        setup_note = QLabel(
            "初回設定：Google Cloudのデスクトップアプリ用OAuthクライアントを作成し、"
            "google_client_secret.json をアプリの設定フォルダーへ配置してください。"
        )
        setup_note.setObjectName("MutedText")
        setup_note.setWordWrap(True)
        layout.addWidget(setup_note)

        action_row = QHBoxLayout()
        self.scan_all_button = QPushButton(
            "連携済みメールをすべて確認"
        )
        self.scan_all_button.setObjectName(
            "AccentButton"
        )
        self.scan_all_button.clicked.connect(
            self.scan_all_accounts
        )
        action_row.addWidget(
            self.scan_all_button
        )
        action_row.addStretch()
        layout.addLayout(action_row)

        self.summary = QLabel("")
        self.summary.setObjectName("MutedText")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload_accounts()

    def add_account(self) -> None:
        try:
            self.manager.add_account(
                self.name_input.text(),
                self.email_input.text(),
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                "登録できません",
                str(error),
            )
            return

        self.name_input.clear()
        self.email_input.clear()
        self.reload_accounts()

    def reload_accounts(self) -> None:
        accounts = self.manager.load_accounts()
        self.summary.setText(
            f"登録済み：{len(accounts)}/"
            f"{self.manager.MAX_ACCOUNTS}件"
        )
        self.add_button.setEnabled(
            len(accounts)
            < self.manager.MAX_ACCOUNTS
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

        if not accounts:
            empty = QLabel(
                "メールアカウントはまだ登録されていません。"
            )
            empty.setObjectName("PageText")
            empty.setAlignment(Qt.AlignCenter)
            list_layout.addWidget(empty)
        else:
            for account in accounts:
                list_layout.addWidget(
                    self._make_card(account)
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

    def _make_card(
        self,
        account: dict,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("ProductCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        layout.setSpacing(8)

        header = QHBoxLayout()

        name = QLabel(
            str(
                account.get(
                    "display_name",
                    "名称未設定",
                )
            )
        )
        name.setObjectName("ProductName")

        status = QLabel(
            str(
                account.get(
                    "connection_status",
                    "未連携",
                )
            )
        )
        status.setObjectName("StatusLottery")

        header.addWidget(name)
        header.addStretch()
        header.addWidget(status)

        email = QLabel(
            "メール："
            + str(account.get("email", ""))
            + "\n最終確認："
            + (
                str(account.get("last_checked", ""))
                or "未確認"
            )
        )
        email.setObjectName("MutedText")

        controls = QHBoxLayout()

        enabled = QCheckBox("自動確認対象")
        enabled.setChecked(
            bool(account.get("enabled", True))
        )
        enabled.toggled.connect(
            lambda checked, account_id=str(
                account.get("id", "")
            ): self._set_enabled(
                account_id,
                checked,
            )
        )

        connected = (
            account.get("connection_status")
            == "連携済み"
        )

        connect_button = QPushButton(
            "再連携"
            if connected
            else "Gmailと連携"
        )
        connect_button.clicked.connect(
            lambda checked=False, account_id=str(
                account.get("id", "")
            ): self._connect_account(
                account_id
            )
        )

        scan_button = QPushButton(
            "このメールを確認"
        )
        scan_button.setEnabled(connected)
        scan_button.clicked.connect(
            lambda checked=False, account_id=str(
                account.get("id", "")
            ): self._scan_account(
                account_id
            )
        )

        disconnect_button = QPushButton(
            "連携解除"
        )
        disconnect_button.setEnabled(connected)
        disconnect_button.clicked.connect(
            lambda checked=False, account_id=str(
                account.get("id", "")
            ): self._disconnect_account(
                account_id
            )
        )

        delete_button = QPushButton("削除")
        delete_button.setObjectName(
            "DangerButton"
        )
        delete_button.clicked.connect(
            lambda checked=False, account_id=str(
                account.get("id", "")
            ), label=str(
                account.get(
                    "display_name",
                    "",
                )
            ): self._remove_account(
                account_id,
                label,
            )
        )

        controls.addWidget(enabled)
        controls.addWidget(connect_button)
        controls.addWidget(scan_button)
        controls.addWidget(disconnect_button)
        controls.addStretch()
        controls.addWidget(delete_button)

        layout.addLayout(header)
        layout.addWidget(email)
        layout.addLayout(controls)
        return card


    def _connect_account(
        self,
        account_id: str,
    ) -> None:
        try:
            self.gmail_service.connect_account(
                account_id
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "Gmail連携に失敗",
                str(error),
            )
            return

        QMessageBox.information(
            self,
            "Gmail連携完了",
            "読取専用でGmailと連携しました。",
        )
        self.reload_accounts()

    def _disconnect_account(
        self,
        account_id: str,
    ) -> None:
        answer = QMessageBox.question(
            self,
            "Gmail連携を解除",
            "保存された認証トークンを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.gmail_service.disconnect_account(
            account_id
        )
        self.reload_accounts()

    def _scan_account(
        self,
        account_id: str,
    ) -> None:
        try:
            results = self.gmail_service.scan_account(
                account_id
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "メール確認に失敗",
                str(error),
            )
            return

        self._show_scan_result(results)
        self.reload_accounts()

    def scan_all_accounts(self) -> None:
        results = (
            self.gmail_service
            .scan_all_enabled()
        )
        self._show_scan_result(results)
        self.reload_accounts()

    def _show_scan_result(
        self,
        results: list[dict],
    ) -> None:
        wins = sum(
            1
            for item in results
            if item.get("status") == "当選"
        )
        losses = sum(
            1
            for item in results
            if item.get("status") == "落選"
        )
        reviews = sum(
            1
            for item in results
            if item.get("status") == "要確認"
        )
        errors = sum(
            1
            for item in results
            if item.get("status") == "エラー"
        )
        tcg_counts: dict[str, int] = {}
        for item in results:
            label = display_name(item.get("tcg_key"), item.get("tcg"))
            tcg_counts[label] = tcg_counts.get(label, 0) + 1
        tcg_summary = "　".join(
            f"{label} {count}件" for label, count in tcg_counts.items()
        )

        self.summary.setText(
            f"メール確認完了：{len(results)}件　"
            f"当選 {wins}件　落選 {losses}件　"
            f"要確認 {reviews}件　エラー {errors}件"
            + (f"\nTCG：{tcg_summary}" if tcg_summary else "")
        )

        QMessageBox.information(
            self,
            "抽選結果メール確認",
            self.summary.text()
            + "\\n\\n一致した当選・落選は"
            "応募ダッシュボードと抽選結果確認へ反映しました。",
        )

    def _set_enabled(
        self,
        account_id: str,
        enabled: bool,
    ) -> None:
        self.manager.set_enabled(
            account_id,
            enabled,
        )

    def _remove_account(
        self,
        account_id: str,
        label: str,
    ) -> None:
        answer = QMessageBox.question(
            self,
            "メールアカウントを削除",
            f"「{label}」を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.manager.remove_account(
            account_id
        )
        self.reload_accounts()

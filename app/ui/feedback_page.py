from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.feedback_api import (
    FeedbackApiClient,
    FeedbackApiError,
    FeedbackValidationError,
    MAX_EMAIL_LENGTH,
    MAX_STORE_NAME_LENGTH,
    MAX_SUBJECT_LENGTH,
    MAX_URL_LENGTH,
    SensitiveInputError,
    TCG_LABELS,
    build_feedback_payload,
    build_store_request_payload,
)
from core.feedback_history import FeedbackReceiptHistory


FEEDBACK_KINDS = (
    ("question", "使い方・質問"),
    ("bug", "不具合"),
    ("request", "機能要望"),
    ("store", "店舗追加依頼"),
    ("other", "その他"),
)
STATUS_LABELS = {
    "pending": "受付済み",
    "reviewing": "確認中",
    "resolved": "対応済み",
    "approved": "承認",
    "rejected": "見送り",
    "duplicate": "重複",
    "needs_information": "追加情報待ち",
}


class FeedbackPage(QFrame):
    def __init__(self, client=None, history=None):
        super().__init__()
        self.setObjectName("ContentPanel")
        self.client = client or FeedbackApiClient()
        self.history = history or FeedbackReceiptHistory()
        self._submitting = False
        self._build_ui()
        self.reload_history()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(14)

        title = QLabel("ご意見・ご要望")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        description = QLabel(
            "使い方のご質問、不具合、機能要望、店舗追加依頼を送信できます。"
            "送信内容は管理者が確認します。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_submission_tab(), "新規投稿")
        self.tabs.addTab(self._build_history_tab(), "受付履歴")
        layout.addWidget(self.tabs, 1)

    def _build_submission_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(12)

        kind_row = QFormLayout()
        self.kind_combo = QComboBox()
        for key, label in FEEDBACK_KINDS:
            self.kind_combo.addItem(label, key)
        self.kind_combo.currentIndexChanged.connect(self._switch_form)
        kind_row.addRow("投稿種別", self.kind_combo)
        layout.addLayout(kind_row)

        self.form_stack = QStackedWidget()
        self.form_stack.addWidget(self._build_normal_form())
        self.form_stack.addWidget(self._build_store_form())
        layout.addWidget(self.form_stack)

        warning = QLabel(
            "送信前に内容を確認してください。氏名・住所など不要な個人情報や、"
            "ライセンスキー、認証トークン、端末コードは絶対に記載しないでください。"
            "添付ファイルには対応していません。"
        )
        warning.setObjectName("MutedText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.send_button = QPushButton("内容を確認して送信")
        self.send_button.setObjectName("AccentButton")
        self.send_button.clicked.connect(self.submit_current)
        layout.addWidget(self.send_button, 0, Qt.AlignRight)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_normal_form(self):
        card = QFrame()
        card.setObjectName("SettingsCard")
        form = QFormLayout(card)
        self.subject = QLineEdit()
        self.subject.setMaxLength(MAX_SUBJECT_LENGTH)
        self.subject.setPlaceholderText("件名を入力")
        self.body = QTextEdit()
        self.body.setAcceptRichText(False)
        self.body.setPlaceholderText("内容を入力（最大10,000文字）")
        self.body.setMinimumHeight(170)
        self.feedback_tcg = QComboBox()
        self.feedback_tcg.addItem("指定なし", "")
        for key, label in TCG_LABELS.items():
            self.feedback_tcg.addItem(label, key)
        self.reply_requested = QCheckBox("返信を希望する")
        self.reply_email = QLineEdit()
        self.reply_email.setMaxLength(MAX_EMAIL_LENGTH)
        self.reply_email.setPlaceholderText("返信希望時にメールアドレスを入力")
        form.addRow("件名", self.subject)
        form.addRow("本文", self.body)
        form.addRow("対象TCG（任意）", self.feedback_tcg)
        form.addRow(self.reply_requested)
        form.addRow("返信先メール（任意）", self.reply_email)
        return card

    def _build_store_form(self):
        card = QFrame()
        card.setObjectName("SettingsCard")
        form = QFormLayout(card)
        self.store_name = QLineEdit()
        self.store_name.setMaxLength(MAX_STORE_NAME_LENGTH)
        self.official_url = QLineEdit()
        self.official_url.setMaxLength(MAX_URL_LENGTH)
        self.official_url.setPlaceholderText("https://公式サイト/")
        self.discovery_url = QLineEdit()
        self.discovery_url.setMaxLength(MAX_URL_LENGTH)
        self.discovery_url.setPlaceholderText("https://情報掲載ページ/")

        tcg_widget = QWidget()
        tcg_layout = QHBoxLayout(tcg_widget)
        tcg_layout.setContentsMargins(0, 0, 0, 0)
        self.store_tcg_checks = {}
        for key, label in TCG_LABELS.items():
            checkbox = QCheckBox(label)
            self.store_tcg_checks[key] = checkbox
            tcg_layout.addWidget(checkbox)
        tcg_layout.addStretch()

        self.sales_scope = QComboBox()
        self.sales_scope.addItem("予約", "reservation")
        self.sales_scope.addItem("抽選", "lottery")
        self.sales_scope.addItem("両方", "both")
        self.notes = QTextEdit()
        self.notes.setAcceptRichText(False)
        self.notes.setPlaceholderText("補足（最大5,000文字）")
        self.notes.setMinimumHeight(120)
        form.addRow("店舗名", self.store_name)
        form.addRow("公式URL", self.official_url)
        form.addRow("情報を発見したURL", self.discovery_url)
        form.addRow("対象TCG（1件以上）", tcg_widget)
        form.addRow("対象", self.sales_scope)
        form.addRow("補足", self.notes)

        note = QLabel("店舗定義への追加は、送信後に管理者が内容と公式情報を確認してから行います。")
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        form.addRow(note)
        return card

    def _build_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 14, 12, 14)
        note = QLabel(
            "受付番号と最終状態だけを保存します。投稿本文とメールアドレスは保存しません。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(
            ["種別", "受付番号", "投稿日時（UTC）", "最終確認状態"]
        )
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SingleSelection)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.history_table, 1)
        row = QHBoxLayout()
        reload_button = QPushButton("履歴を再読込")
        reload_button.clicked.connect(self.reload_history)
        self.status_button = QPushButton("選択した受付番号の状態を確認")
        self.status_button.setObjectName("AccentButton")
        self.status_button.clicked.connect(self.check_selected_status)
        row.addWidget(reload_button)
        row.addStretch()
        row.addWidget(self.status_button)
        layout.addLayout(row)
        return widget

    def _switch_form(self):
        self.form_stack.setCurrentIndex(
            1 if self.kind_combo.currentData() == "store" else 0
        )

    def submit_current(self):
        if self._submitting:
            return
        try:
            kind_key = str(self.kind_combo.currentData())
            kind_label = self.kind_combo.currentText()
            if kind_key == "store":
                payload = build_store_request_payload(
                    store_name=self.store_name.text(),
                    official_url=self.official_url.text(),
                    discovery_url=self.discovery_url.text(),
                    tcg_keys=[
                        key for key, checkbox in self.store_tcg_checks.items()
                        if checkbox.isChecked()
                    ],
                    sales_scope=str(self.sales_scope.currentData()),
                    notes=self.notes.toPlainText(),
                )
            else:
                tcg_key = str(self.feedback_tcg.currentData())
                payload = build_feedback_payload(
                    feedback_type=kind_key,
                    subject=self.subject.text(),
                    body=self.body.toPlainText(),
                    tcg_keys=[tcg_key] if tcg_key else [],
                    reply_requested=self.reply_requested.isChecked(),
                    reply_email=self.reply_email.text(),
                )
        except SensitiveInputError as error:
            QMessageBox.warning(self, "秘密情報を削除してください", str(error))
            return
        except FeedbackValidationError as error:
            QMessageBox.warning(self, "入力内容を確認してください", str(error))
            return

        answer = QMessageBox.question(
            self,
            "送信前確認",
            f"「{kind_label}」として送信します。\n"
            "個人情報やライセンスキーが含まれていないことを確認しましたか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._set_submitting(True)
        try:
            result = (
                self.client.submit_store_request(payload)
                if kind_key == "store"
                else self.client.submit_feedback(payload)
            )
            receipt_id = str(result.get("receipt_id", "")).strip()
            status = str(result.get("status", "pending"))
            if not receipt_id:
                raise FeedbackApiError("受付番号を確認できませんでした。")
            self._clear_successful_form(kind_key)
            try:
                self.history.add(kind_label, receipt_id, status)
                self.reload_history()
            except OSError as history_error:
                QMessageBox.warning(
                    self,
                    "受付完了（履歴保存失敗）",
                    f"送信は受け付けられました。\n受付番号: {receipt_id}\n\n"
                    f"ローカル履歴だけを保存できませんでした: {history_error}",
                )
                return
            QMessageBox.information(
                self,
                "受付完了",
                f"送信を受け付けました。\n受付番号: {receipt_id}",
            )
        except FeedbackApiError as error:
            QMessageBox.warning(
                self,
                "送信できませんでした",
                f"{error}\n\n入力内容は保持されています。自動再送は行いません。",
            )
        finally:
            self._set_submitting(False)

    def _set_submitting(self, value: bool):
        self._submitting = value
        self.send_button.setEnabled(not value)
        self.send_button.setText("送信中…" if value else "内容を確認して送信")

    def _clear_successful_form(self, kind_key: str):
        if kind_key == "store":
            self.store_name.clear()
            self.official_url.clear()
            self.discovery_url.clear()
            self.notes.clear()
            for checkbox in self.store_tcg_checks.values():
                checkbox.setChecked(False)
        else:
            self.subject.clear()
            self.body.clear()
            self.feedback_tcg.setCurrentIndex(0)
            self.reply_requested.setChecked(False)
            self.reply_email.clear()

    def reload_history(self):
        items = self.history.load()
        self.history_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (
                item["kind"],
                item["receipt_id"],
                item["submitted_at"],
                STATUS_LABELS.get(item["last_status"], item["last_status"]),
            )
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def check_selected_status(self):
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "受付状態確認", "確認する受付番号を選択してください。")
            return
        kind = self.history_table.item(row, 0).text()
        receipt_id = self.history_table.item(row, 1).text()
        self.status_button.setEnabled(False)
        try:
            result = self.client.receipt_status(kind, receipt_id)
            status = str(result.get("status", ""))
            if not status:
                raise FeedbackApiError("受付状態を確認できませんでした。")
            self.history.update_status(receipt_id, status)
            self.reload_history()
            QMessageBox.information(
                self,
                "受付状態",
                f"受付番号: {receipt_id}\n状態: {STATUS_LABELS.get(status, status)}",
            )
        except (FeedbackApiError, FeedbackValidationError, OSError) as error:
            QMessageBox.warning(self, "状態確認に失敗しました", str(error))
        finally:
            self.status_button.setEnabled(True)

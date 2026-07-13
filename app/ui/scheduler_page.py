from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.scheduler_config import SchedulerConfig


class SchedulerPage(QFrame):
    def __init__(self, scheduler):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.scheduler = scheduler
        self.config_manager = SchedulerConfig()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        title = QLabel("自動監視")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(
            "登録した公式情報ページと抽選結果ページを、"
            "指定した間隔でバックグラウンド確認します。\n"
            "短時間の過剰アクセスを避けるため、最短間隔は5分です。"
            "ログイン突破・CAPTCHA回避・自動応募は行いません。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        settings_card = QFrame()
        settings_card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(settings_card)
        card_layout.setSpacing(12)

        self.enabled = QCheckBox("自動監視を有効にする")

        interval_row = QHBoxLayout()
        interval_label = QLabel("確認間隔")
        self.interval = QSpinBox()
        self.interval.setRange(5, 1440)
        self.interval.setSuffix(" 分")
        interval_row.addWidget(interval_label)
        interval_row.addWidget(self.interval)
        interval_row.addStretch()

        self.check_sources = QCheckBox("公式情報ソースを確認")
        self.check_lotteries = QCheckBox("抽選結果ページを確認")
        self.check_candidate_retail = QCheckBox(
            "新弾候補の販売・抽選情報を自動検索"
        )
        self.check_gmail_results = QCheckBox(
            "連携済みGmailから抽選結果を自動確認"
        )

        candidate_interval_row = QHBoxLayout()
        candidate_interval_label = QLabel(
            "販売情報の再検索間隔"
        )
        self.candidate_interval = QSpinBox()
        self.candidate_interval.setRange(15, 1440)
        self.candidate_interval.setSuffix(" 分")
        candidate_interval_row.addWidget(
            candidate_interval_label
        )
        candidate_interval_row.addWidget(
            self.candidate_interval
        )
        candidate_interval_row.addStretch()

        buttons = QHBoxLayout()

        save_button = QPushButton("設定を保存")
        save_button.setObjectName("AccentButton")
        save_button.clicked.connect(self.save_settings)

        run_button = QPushButton("今すぐ確認")
        run_button.clicked.connect(self.run_now)

        buttons.addWidget(save_button)
        buttons.addWidget(run_button)
        buttons.addStretch()

        card_layout.addWidget(self.enabled)
        card_layout.addLayout(interval_row)
        card_layout.addWidget(self.check_sources)
        card_layout.addWidget(self.check_lotteries)
        card_layout.addWidget(
            self.check_candidate_retail
        )
        card_layout.addWidget(
            self.check_gmail_results
        )
        card_layout.addLayout(
            candidate_interval_row
        )
        card_layout.addLayout(buttons)

        layout.addWidget(settings_card)

        self.status = QLabel("")
        self.status.setObjectName("SectionTitle")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        note = QLabel(
            "自動監視はポケヨヤ君を起動している間だけ動作します。"
            "Windows起動時の自動起動は、次の段階で追加します。"
        )
        note.setObjectName("MutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

        self.scheduler.status_changed.connect(self.status.setText)
        self.scheduler.run_completed.connect(self._on_run_completed)

        self.load_settings()

    def load_settings(self):
        config = self.config_manager.load()

        self.enabled.setChecked(
            bool(config.get("enabled", False))
        )
        self.interval.setValue(
            int(config.get("interval_minutes", 30))
        )
        self.check_sources.setChecked(
            bool(config.get("check_sources", True))
        )
        self.check_lotteries.setChecked(
            bool(config.get("check_lotteries", True))
        )
        self.check_candidate_retail.setChecked(
            bool(
                config.get(
                    "check_candidate_retail",
                    True,
                )
            )
        )
        self.candidate_interval.setValue(
            int(
                config.get(
                    "candidate_retail_interval_minutes",
                    30,
                )
            )
        )
        self.check_gmail_results.setChecked(
            bool(
                config.get(
                    "check_gmail_results",
                    True,
                )
            )
        )

        last_run = str(config.get("last_run", "")).strip()
        self.status.setText(
            f"最終確認：{last_run or '未実行'}"
        )

    def save_settings(self):
        if (
            not self.check_sources.isChecked()
            and not self.check_lotteries.isChecked()
            and not self.check_candidate_retail.isChecked()
            and not self.check_gmail_results.isChecked()
        ):
            QMessageBox.warning(
                self,
                "監視対象なし",
                "少なくとも1つの監視対象を選択してください。",
            )
            return

        config = self.config_manager.load()
        config.update(
            {
                "enabled": self.enabled.isChecked(),
                "interval_minutes": self.interval.value(),
                "check_sources": self.check_sources.isChecked(),
                "check_lotteries": self.check_lotteries.isChecked(),
                "check_candidate_retail": (
                    self.check_candidate_retail.isChecked()
                ),
                "candidate_retail_interval_minutes": (
                    self.candidate_interval.value()
                ),
                "check_gmail_results": (
                    self.check_gmail_results.isChecked()
                ),
            }
        )
        self.config_manager.save(config)
        self.scheduler.reload_config()

        QMessageBox.information(
            self,
            "保存完了",
            "自動監視設定を保存しました。",
        )

    def run_now(self):
        self.status.setText("手動確認を開始します…")
        self.scheduler.run_now()

    def _on_run_completed(self, result: dict):
        self.status.setText(
            "確認完了："
            f"情報ソース{result.get('source_count', 0)}件、"
            f"抽選{result.get('lottery_count', 0)}件、"
            f"変更{len(result.get('changed_sources', []))}件、"
            f"当選候補{len(result.get('newly_won', []))}件、"
            f"販売情報検索"
            f"{result.get('candidate_search', {}).get('searched_count', 0)}件、"
            f"Gmail結果{len(result.get('gmail_results', []))}件"
        )

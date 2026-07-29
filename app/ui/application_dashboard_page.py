from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from core.application_dashboard import ApplicationDashboard
from core.config_manager import ConfigManager
from core.startup_diagnostics import StartupDiagnostics
from core.lottery_manager import LotteryManager
from core.product_store import ProductStore
from core.safe_product_url import can_open_product_url, open_product_url
from core.tcg_categories import categories


class ApplicationRow(QFrame):
    def __init__(
        self,
        row: dict,
        store: ProductStore,
        reload_callback,
        applied_callback,
    ):
        super().__init__()
        self.row = row
        self.store = store
        self.reload_callback = reload_callback
        self.applied_callback = applied_callback
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            13,
            16,
            13,
        )
        layout.setSpacing(8)

        header = QHBoxLayout()

        title = QLabel(
            row.get(
                "product_name",
                "商品名未設定",
            )
        )
        title.setObjectName("ProductName")
        title.setWordWrap(True)

        state = QLabel(
            row.get(
                "application_state",
                "未応募",
            )
        )
        state.setObjectName(
            self._status_object_name(
                row.get(
                    "application_state",
                    "",
                )
            )
        )

        product_button = QPushButton("商品ページを開く")
        product_button.setObjectName("SmallButton")
        product_button.setEnabled(can_open_product_url(row.get("product_url")))
        product_button.clicked.connect(self._open_product_page)

        application_button = QPushButton("応募ページを開く")
        application_button.setObjectName("SmallButton")
        application_button.setEnabled(can_open_product_url(row.get("application_url")))
        application_button.clicked.connect(self._open_application_page)

        header.addWidget(title, 1)
        if row.get("is_new"):
            new_label = QLabel("NEW")
            new_label.setObjectName("StatusOpen")
            header.addWidget(new_label)
        header.addWidget(state)
        header.addWidget(product_button)
        header.addWidget(application_button)
        layout.addLayout(header)

        store_info = QLabel(
            f'TCG：{row.get("tcg", "その他")}　'
            f'店舗：{row.get("site_name", "店舗名未設定")}　'
            f'発売日：{row.get("release_date") or "未設定"}'
        )
        store_info.setObjectName("MutedText")
        layout.addWidget(store_info)

        warnings = row.get("condition_warnings", [])
        warning_label = QLabel(
            "応募条件: "
            + (" / ".join(str(item.get("display", "")) for item in warnings) if warnings else "特記事項なし")
        )
        warning_label.setObjectName("StatusLottery" if warnings else "MutedText")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        changes = row.get("changes", {})
        change_label = QLabel(
            "変更: " + " / ".join(
                f'{item.get("label", "項目")} {item.get("before") or "未取得"} → {item.get("after") or "未取得"}'
                for item in changes.values()
            )
        )
        change_label.setObjectName("StatusOpen")
        change_label.setWordWrap(True)
        change_label.setVisible(bool(changes))
        layout.addWidget(change_label)

        detail_button = QPushButton("詳細を表示")
        detail_button.setObjectName("SmallButton")
        layout.addWidget(detail_button)

        schedule = QLabel(
            f'状態：{row.get("period_status", "未確認")} '
            f'（{row.get("remaining_text", "")}）\n'
            f'応募開始：{row.get("application_start_at") or "未取得"}　'
            f'応募締切：{row.get("application_end_at") or "未取得"}　'
            f'結果発表予定：{row.get("result_announcement_at") or row.get("result_date") or "未取得"}\n'
            f'受付方式：{row.get("application_method") or "未取得"}　'
            f'応募条件：{row.get("application_conditions") or "未取得"}'
            + (f'　終了理由：{row.get("end_reason")}' if row.get("end_reason") else "")
        )
        schedule.setObjectName("MutedText")
        schedule.setWordWrap(True)
        layout.addWidget(schedule)

        history = QLabel(
            "応募／予約日時："
            + (row.get("application_datetime") or "未記録")
            + "　結果確認日時："
            + (row.get("result_checked_at") or "未確認")
            + ("　受付・注文番号：" + row["masked_reference"]
               if row.get("masked_reference") else "")
        )
        history.setObjectName("MutedText")
        history.setWordWrap(True)
        layout.addWidget(history)

        related_url = QLabel(
            "関連URL：" + (row.get("related_url") or "未登録")
        )
        related_url.setObjectName("MutedText")
        related_url.setWordWrap(True)
        related_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(related_url)

        controls_widget = QWidget()
        controls = QHBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)

        applied_button = QPushButton(
            "応募済みにする"
            if row.get("application_state") == "未応募"
            else "応募状態を解除"
        )
        applied_button.clicked.connect(
            self._toggle_applied
        )

        result = QComboBox()
        result.addItems(
            ["未確認", "当選", "落選", "予約完了", "注文受付", "キャンセル", "その他"]
        )
        index = result.findText(
            row.get(
                "result_status",
                "未確認",
            )
        )
        if index >= 0:
            result.setCurrentIndex(index)
        result.currentTextChanged.connect(
            self._save_result
        )

        controls.addWidget(applied_button)
        controls.addWidget(QLabel("抽選結果："))
        controls.addWidget(result)
        controls.addStretch()

        layout.addWidget(controls_widget)

        self.detail_widgets = [product_button, schedule, history, related_url, controls_widget]
        for widget in self.detail_widgets:
            widget.setVisible(False)
        detail_button.clicked.connect(
            lambda: self._toggle_details(detail_button)
        )

    def _toggle_details(self, button: QPushButton):
        visible = not self.detail_widgets[0].isVisible()
        for widget in self.detail_widgets:
            widget.setVisible(visible)
        button.setText("詳細を閉じる" if visible else "詳細を表示")

    def _toggle_applied(self):
        currently_applied = (
            self.row.get("application_state")
            != "未応募"
        )
        new_applied = not currently_applied

        self.store.save_site_application_state(
            str(self.row.get("product_id", "")),
            str(self.row.get("site_key", "")),
            str(self.row.get("site_url", "")),
            new_applied,
            str(self.row.get("tcg_key", "other")),
            str(self.row.get("tcg", "その他")),
        )

        if new_applied:
            self.applied_callback(self.row)
            return

        self.reload_callback()

    def _save_result(self, value: str):
        self.store.save_site_result(
            str(self.row.get("product_id", "")),
            str(self.row.get("site_key", "")),
            str(self.row.get("site_url", "")),
            value,
        )
        if value != "未確認":
            self.reload_callback()

    def _open_product_page(self):
        open_product_url(self.row.get("product_url", ""))

    def _open_application_page(self):
        open_product_url(self.row.get("application_url", ""))

    @staticmethod
    def _status_object_name(
        status: str,
    ) -> str:
        if status in {
            "当選",
            "抽選受付完了",
        }:
            return "StatusOpen"
        if status == "抽選結果確認":
            return "StatusLottery"
        if status == "落選":
            return "StatusClosed"
        return "StatusOther"


class ApplicationProductGroup(QFrame):
    def __init__(self, group: dict, store: ProductStore, reload_callback, applied_callback):
        super().__init__()
        self.setObjectName("SettingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel(
            f'{group.get("product_name", "商品名未設定")}　'
            f'{group.get("tcg", "その他")}　応募先 {len(group.get("rows", []))}件'
        )
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        for row in group.get("rows", []):
            layout.addWidget(
                ApplicationRow(row, store, reload_callback, applied_callback)
            )


class ApplicationDashboardPage(QFrame):
    open_lottery_page = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.dashboard = ApplicationDashboard()
        self.startup_diagnostics = StartupDiagnostics()
        self._last_diagnostic_signature = None
        self.store = ProductStore()
        self.config_manager = ConfigManager()
        self.lottery_manager = LotteryManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("応募ダッシュボード")
        title.setObjectName("PageTitle")

        refresh = QPushButton("再読込")
        refresh.setObjectName("AccentButton")
        refresh.clicked.connect(self.reload)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

        self.summary = QLabel("")
        self.summary.setObjectName("SectionTitle")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        description = QLabel(
            "商品一覧にある店舗ごとの応募状況をまとめて表示します。"
            "結果確認日が来たものを上に表示し、"
            "当選・落選もここから記録できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.tcg_tabs = QTabBar()
        self.tcg_tabs.setExpanding(False)
        self.tcg_tabs.addTab("すべて 0")
        self.tcg_tabs.setTabData(0, "all")
        for item in categories():
            index = self.tcg_tabs.addTab(f"{item.short_name} 0")
            self.tcg_tabs.setTabData(index, item.key)
        self.tcg_tabs.currentChanged.connect(self.reload)
        layout.addWidget(self.tcg_tabs)

        self.state_tabs = QTabBar()
        self.state_tabs.setExpanding(False)
        for state in (
            "すべて", "未応募", "応募済み", "本日締切",
            "結果待ち", "当選", "落選", "終了済み",
        ):
            index = self.state_tabs.addTab(f"{state} 0")
            self.state_tabs.setTabData(index, state)
        self.state_tabs.currentChanged.connect(self.reload)
        layout.addWidget(self.state_tabs)

        filter_row = QHBoxLayout()

        filter_row.addWidget(QLabel("並び順："))
        self.sort_mode = QComboBox()
        self.sort_mode.addItems(
            [
                "優先度順",
                "応募締切順",
                "結果発表順",
                "発売日順",
                "店舗名順",
            ]
        )
        self.sort_mode.setCurrentText("応募締切順")
        self.sort_mode.currentTextChanged.connect(
            self.reload
        )
        filter_row.addWidget(self.sort_mode)

        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText(
            "商品名・店舗名で検索"
        )
        self.keyword.textChanged.connect(
            self.reload
        )
        filter_row.addWidget(self.keyword, 1)

        self.show_ended = QCheckBox("終了済みを表示")
        self.show_ended.setChecked(bool(
            self.config_manager.load().get("general", {}).get(
                "show_ended_applications", False
            )
        ))
        self.show_ended.toggled.connect(self._toggle_show_ended)
        filter_row.addWidget(self.show_ended)

        self.group_by_product = QCheckBox("商品ごとにまとめる")
        self.group_by_product.setChecked(bool(
            self.config_manager.load().get("application_assistant", {}).get(
                "group_by_product", True
            )
        ))
        self.group_by_product.toggled.connect(self._toggle_group_by_product)
        filter_row.addWidget(self.group_by_product)

        layout.addLayout(filter_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self.reload()
        self.period_timer = QTimer(self)
        self.period_timer.setInterval(60_000)
        self.period_timer.timeout.connect(self.reload)
        self.period_timer.start()


    def _on_marked_applied(
        self,
        row: dict,
    ) -> None:
        product_name = str(
            row.get(
                "product_name",
                "商品名未設定",
            )
        )
        site_name = str(
            row.get(
                "site_name",
                "店舗名未設定",
            )
        )
        site_url = str(
            row.get(
                "site_url",
                "",
            )
        )

        self.lottery_manager.add_item(
            product_name,
            site_name,
            site_url,
            str(row.get("tcg_key", "other")),
            str(row.get("tcg", "その他")),
        )

        self.reload()
        self.open_lottery_page.emit()

    def _toggle_show_ended(self, enabled: bool):
        config = self.config_manager.load()
        config.setdefault("general", {})["show_ended_applications"] = bool(enabled)
        self.config_manager.save(config)
        self.reload()

    def _toggle_group_by_product(self, enabled: bool):
        config = self.config_manager.load()
        config.setdefault("application_assistant", {})["group_by_product"] = bool(enabled)
        self.config_manager.save(config)
        self.reload()

    def reload(self, *_args):
        selected_state = str(
            self.state_tabs.tabData(self.state_tabs.currentIndex()) or "未応募"
        )
        data = self.dashboard.build(
            state_filter=selected_state,
            sort_mode=self.sort_mode.currentText(),
            keyword=self.keyword.text(),
            tcg_filter=str(
                self.tcg_tabs.tabData(self.tcg_tabs.currentIndex()) or "all"
            ),
            show_ended=self.show_ended.isChecked() or selected_state == "終了済み",
        )
        diagnostics = data.get("diagnostics", {})
        diagnostics_by_tcg = data.get("diagnostics_by_tcg", {})
        signature = (
            tuple(sorted(diagnostics.items())),
            tuple(
                (
                    item.key,
                    tuple(sorted(diagnostics_by_tcg.get(item.key, {}).items())),
                )
                for item in categories()
            ),
            selected_state,
            str(self.tcg_tabs.tabData(self.tcg_tabs.currentIndex()) or "all"),
            self.keyword.text(),
            self.show_ended.isChecked(),
        )
        if signature != self._last_diagnostic_signature:
            self._last_diagnostic_signature = signature
            exclusion_keys = (
                "excluded_no_application_evidence",
                "excluded_ended",
                "excluded_tcg_filter",
                "excluded_state_filter",
                "excluded_keyword",
            )
            exclusion_text = " ".join(
                f"{key}={diagnostics.get(key, 0)}"
                for key in exclusion_keys
            )
            self.startup_diagnostics.write(
                "Application dashboard: "
                f'products={diagnostics.get("loaded_products", 0)} '
                f'sites={diagnostics.get("loaded_sites", 0)} '
                f'evidence={diagnostics.get("application_evidence", 0)} '
                f'eligible={diagnostics.get("eligible_rows", 0)} '
                f'displayed={diagnostics.get("displayed_rows", 0)} '
                + exclusion_text
            )
            for item in categories():
                values = diagnostics_by_tcg.get(item.key, {})
                self.startup_diagnostics.write(
                    f"Application dashboard {item.key}: "
                    f'products={values.get("loaded_products", 0)} '
                    f'sites={values.get("loaded_sites", 0)} '
                    f'evidence={values.get("application_evidence", 0)} '
                    f'eligible={values.get("eligible_rows", 0)} '
                    f'displayed={values.get("displayed_rows", 0)} '
                    f'no_evidence={values.get("excluded_no_application_evidence", 0)} '
                    f'ended={values.get("excluded_ended", 0)} '
                    f'tcg_filter={values.get("excluded_tcg_filter", 0)} '
                    f'state_filter={values.get("excluded_state_filter", 0)} '
                    f'keyword={values.get("excluded_keyword", 0)}'
                )
        counts = data["counts"]
        state_counts = data.get("state_counts", {})

        self.state_tabs.blockSignals(True)
        for index in range(self.state_tabs.count()):
            state = str(self.state_tabs.tabData(index))
            count = data["total_rows"] if state == "すべて" else state_counts.get(state, 0)
            self.state_tabs.setTabText(index, f"{state} {count}")
        self.state_tabs.blockSignals(False)

        tcg_counts = data["tcg_counts"]
        self.tcg_tabs.blockSignals(True)
        self.tcg_tabs.setTabText(0, f'すべて {data["total_rows"]}')
        for index, item in enumerate(categories(), start=1):
            self.tcg_tabs.setTabText(
                index, f'{item.short_name} {tcg_counts.get(item.key, 0)}'
            )
        self.tcg_tabs.blockSignals(False)

        self.summary.setText(
            f'未応募 {state_counts.get("未応募", counts.get("未応募", 0))}件　'
            f'応募済み {state_counts.get("応募済み", counts.get("応募済み", 0))}件　'
            f'本日締切 {state_counts.get("本日締切", 0)}件　'
            f'結果待ち {state_counts.get("結果待ち", counts.get("抽選結果待ち", 0))}件　'
            f'当選 {state_counts.get("当選", counts.get("当選", 0))}件　'
            f'落選 {state_counts.get("落選", counts.get("落選", 0))}件'
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

        rows = data["rows"]
        self.summary.setText(
            self.summary.text()
            + f'　表示 {len(rows)}/{data["total_rows"]}件'
            + f'　終了済み {data.get("ended_rows", 0)}件'
        )

        if not rows:
            empty = QLabel(
                "応募管理できる販売・抽選情報がありません。"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        elif self.group_by_product.isChecked():
            for group in data.get("groups", []):
                list_layout.addWidget(
                    ApplicationProductGroup(
                        group, self.store, self.reload, self._on_marked_applied
                    )
                )
        else:
            for row in rows:
                list_layout.addWidget(
                    ApplicationRow(
                        row,
                        self.store,
                        self.reload,
                        self._on_marked_applied,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

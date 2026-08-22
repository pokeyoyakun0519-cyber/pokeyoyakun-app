import re

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
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
from core.product_categories import PRODUCT_CATEGORY_LABELS
from core.application_filters import (
    REGION_NAMES,
    sales_channel_matches,
)
from ui.tcg_category_tabs import (
    ALL_CATEGORY_KEY,
    TcgCategoryTabs,
    category_counts,
    filter_items_by_category,
)


class ApplicationRow(QFrame):
    def __init__(
        self,
        row: dict,
        store: ProductStore,
        reload_callback,
        applied_callback,
        favorite_callback=None,
        favorite_store_keys=None,
    ):
        super().__init__()
        self.row = row
        self.store = store
        self.reload_callback = reload_callback
        self.applied_callback = applied_callback
        self.favorite_callback = favorite_callback
        self.favorite_store_keys = set(favorite_store_keys or [])
        self.setObjectName("CandidateCard" if row.get("is_candidate") else "ProductCard")

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

        display_state = (
            "確認中" if row.get("is_candidate")
            else "当選" if row.get("dashboard_state") == "当選"
            else "落選" if row.get("dashboard_state") == "落選"
            else "応募期間終了" if row.get("period_ended")
            else row.get("application_state", "未応募")
        )
        state = QLabel(display_state)
        state.setObjectName(
            self._status_object_name(display_state)
        )

        product_button = QPushButton("商品ページを開く")
        product_button.setObjectName("SmallButton")
        product_button.setEnabled(can_open_product_url(row.get("product_url")))
        product_button.clicked.connect(self._open_product_page)

        application_button = QPushButton("応募ページを開く")
        application_button.setObjectName("AccentButton")
        application_button.setEnabled(
            can_open_product_url(row.get("application_url")) and not row.get("is_candidate")
        )
        if row.get("is_candidate"):
            application_button.setToolTip("公式確認が完了するまで応募操作は利用できません")
        application_button.clicked.connect(self._open_application_page)

        header.addWidget(title, 1)
        if row.get("is_new"):
            new_label = QLabel("NEW")
            new_label.setObjectName("StatusOpen")
            header.addWidget(new_label)
        if row.get("changes"):
            changed_label = QLabel("更新あり")
            changed_label.setObjectName("StatusLottery")
            header.addWidget(changed_label)
        favorite_button = QPushButton(
            "★ お気に入り店舗" if row.get("store_key") in self.favorite_store_keys
            else "☆ お気に入り店舗"
        )
        favorite_button.setObjectName("SmallButton")
        favorite_button.setEnabled(bool(row.get("store_key")) and favorite_callback is not None)
        favorite_button.clicked.connect(
            lambda: favorite_callback(row) if favorite_callback is not None else None
        )
        header.addWidget(favorite_button)
        header.addWidget(state)
        header.addWidget(application_button)
        layout.addLayout(header)

        store_info = QLabel(
            f'店舗：{row.get("site_name", "店舗名未設定")}　'
            f'受付開始：{row.get("application_start_at") or "未取得"}　'
            f'締切：{self._deadline_label(row)}'
            f'（{row.get("remaining_text") or "締切日時不明"}）　'
            f'方式：{self._sales_mode_label(row.get("sales_mode"))}　'
            f'地域：{self._prefecture_label(row.get("prefecture"))}　'
            f'応募状態：{"確認中" if row.get("is_candidate") else row.get("application_state", "未応募")}'
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
        warning_label.setVisible(bool(warnings))
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
        layout.addWidget(product_button)

        schedule = QLabel(
            f'状態：{row.get("period_status", "未確認")} '
            f'（{row.get("remaining_text", "")}）\n'
            f'応募開始：{row.get("application_start_at") or "未取得"}　'
            f'応募締切：{self._deadline_label(row)}　'
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

        technical = QLabel(
            f'支店：{row.get("branch") or "未登録"}　住所：{row.get("address") or "未登録"}\n'
            f'chain：{row.get("chain") or "未登録"}　city：{row.get("city") or "未登録"}　'
            f'location source：{row.get("location_source") or "未登録"}\n'
            f'source type：{row.get("source_type") or "未登録"}　'
            f'verification：{row.get("verification_status") or "未登録"}\n'
            f'evidence：{self._evidence_text(row.get("evidence"))}　'
            f'details：{row.get("verification_details") or "未登録"}'
        )
        technical.setObjectName("MutedText")
        technical.setWordWrap(True)
        layout.addWidget(technical)

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
        applied_button.setEnabled(not row.get("is_candidate"))
        result.setEnabled(not row.get("is_candidate"))

        controls.addWidget(applied_button)
        controls.addWidget(QLabel("抽選結果："))
        controls.addWidget(result)
        controls.addStretch()

        layout.addWidget(controls_widget)

        self.detail_widgets = [product_button, change_label, schedule,
                               history, related_url, technical, controls_widget]
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
        if status == "確認中":
            return "StatusLottery"
        if status in {
            "当選",
            "抽選受付完了",
        }:
            return "StatusOpen"
        if status == "抽選結果確認":
            return "StatusLottery"
        if status == "落選":
            return "StatusClosed"
        if status != "応募期間終了":
            return "StatusActive"
        return "StatusOther"

    @staticmethod
    def _sales_mode_label(value: str) -> str:
        return {"ONLINE": "🌐 ネット販売", "STORE": "🏪 店舗販売",
                "HYBRID": "🏪🌐 店舗＋ネット",
                "UNKNOWN": "販売方法 未確認"}.get(str(value), "販売方法 未確認")

    @staticmethod
    def _deadline_label(row: dict) -> str:
        value = str(
            row.get("application_end_at") or row.get("application_end") or ""
        ).strip()
        if not value:
            return "未取得"
        date_match = re.match(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?", value)
        display = (
            f"{date_match.group(1)}/{int(date_match.group(2)):02d}/"
            f"{int(date_match.group(3)):02d}"
            if date_match else value
        )
        time_match = re.search(r"(?:T|\s)(\d{1,2}):(\d{2})", value)
        if row.get("application_end_time_confirmed", True) and time_match:
            display += f" {int(time_match.group(1)):02d}:{time_match.group(2)}"
        elif not row.get("application_end_time_confirmed", True):
            display += "（時刻未確認）"
        return display

    @staticmethod
    def _prefecture_label(value: str) -> str:
        return "地域不明" if str(value or "UNKNOWN") == "UNKNOWN" else str(value)

    @staticmethod
    def _evidence_text(value) -> str:
        if isinstance(value, list):
            return " / ".join(str(item.get("url") or item) if isinstance(item, dict) else str(item)
                              for item in value) or "未登録"
        return str(value or "未登録")


class ApplicationProductGroup(QFrame):
    def __init__(self, group: dict, store: ProductStore, reload_callback, applied_callback,
                 favorite_callback=None, favorite_store_keys=None):
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
                ApplicationRow(
                    row, store, reload_callback, applied_callback,
                    favorite_callback, favorite_store_keys,
                )
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
        refresh.clicked.connect(lambda: self.reload(force=True))

        header.addWidget(title)
        header.addStretch()
        header.addWidget(refresh)
        layout.addLayout(header)

        self.summary = QLabel("")
        self.summary.setObjectName("PageText")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        description = QLabel(
            "各店舗・公式サイトの抽選、予約、応募受付情報をまとめて表示します。"
            "結果確認日が来たものを上に表示し、"
            "当選・落選もここから記録できます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.sales_tabs = QTabBar()
        self.sales_tabs.setExpanding(False)
        for label, value in (
            ("すべて 0", "all"),
            ("ネット販売 0", "online"),
            ("店舗販売 0", "store"),
        ):
            index = self.sales_tabs.addTab(label)
            self.sales_tabs.setTabData(index, value)
        self.sales_tabs.currentChanged.connect(self._apply_filters)
        layout.addWidget(self.sales_tabs)

        self.region_tabs = QTabBar()
        self.region_tabs.setExpanding(False)
        for value in REGION_NAMES:
            index = self.region_tabs.addTab(value)
            self.region_tabs.setTabData(index, "all" if value == "全国" else value)
        self.region_tabs.currentChanged.connect(self._apply_filters)
        self.region_tabs.setVisible(False)
        layout.addWidget(self.region_tabs)

        self.period_tabs = QTabBar()
        self.period_tabs.setExpanding(False)
        for label, value in (("受付中 0", "active"), ("応募期間終了 0", "ended")):
            index = self.period_tabs.addTab(label)
            self.period_tabs.setTabData(index, value)
        self.period_tabs.currentChanged.connect(self._apply_filters)

        self.tcg_tabs = TcgCategoryTabs()
        self.tcg_tabs.category_changed.connect(self._on_tcg_category_changed)
        layout.addWidget(self.tcg_tabs)
        layout.addWidget(self.period_tabs)

        filter_header = QHBoxLayout()
        self.filter_toggle = QPushButton("絞り込みを表示")
        self.filter_toggle.setObjectName("SmallButton")
        self.filter_toggle.clicked.connect(self._toggle_filters)
        filter_header.addWidget(self.filter_toggle)
        filter_header.addStretch()
        layout.addLayout(filter_header)

        self.filter_panel = QWidget()
        filter_layout = QVBoxLayout(self.filter_panel)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        filter_row = QHBoxLayout()
        # 過去のUIテスト・内部操作との互換用。画面上の選択は常設タブへ集約する。
        self.tcg_filter = QComboBox()
        self.tcg_filter.addItem("すべて", "all")
        for item in categories(enabled_only=True):
            self.tcg_filter.addItem(item.short_name, item.key)
        self.tcg_filter.setVisible(False)
        self.tcg_filter.currentIndexChanged.connect(self._on_legacy_tcg_filter_changed)

        self.sales_mode_filter = QComboBox()
        for label, value in (("すべて", "all"), ("🌐 ネット販売", "ONLINE"),
                             ("🏪 店舗販売", "STORE"),
                             ("🏪🌐 店舗＋ネット", "HYBRID"),
                             ("販売方法 未確認", "UNKNOWN")):
            self.sales_mode_filter.addItem(label, value)
        self.sales_mode_filter.currentIndexChanged.connect(self._apply_filters)
        self.sales_mode_filter.setVisible(False)

        filter_row.addWidget(QLabel("都道府県："))
        self.prefecture_filter = QComboBox()
        self.prefecture_filter.addItem("すべて", "all")
        self.prefecture_filter.addItem("地域不明", "UNKNOWN")
        self.prefecture_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.prefecture_filter)
        filter_row.addStretch()
        filter_layout.addLayout(filter_row)

        filter_row2 = QHBoxLayout()
        filter_row2.addWidget(QLabel("商品カテゴリ："))
        self.product_category_filter = QComboBox()
        self.product_category_filter.addItem("すべて", "all")
        for value, label in PRODUCT_CATEGORY_LABELS.items():
            self.product_category_filter.addItem(label, value)
        self.product_category_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row2.addWidget(self.product_category_filter)

        filter_row2.addWidget(QLabel("応募状態："))
        self.application_state_filter = QComboBox()
        for state in ("すべて", "未応募", "応募済み", "結果待ち", "当選", "落選", "確認中"):
            self.application_state_filter.addItem(state, state)
        self.application_state_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row2.addWidget(self.application_state_filter)

        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("商品名・店舗名で検索")
        self.keyword.textChanged.connect(self._apply_filters)
        filter_row2.addWidget(self.keyword, 1)

        filter_row2.addWidget(QLabel("並び順："))
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
            self._apply_filters
        )
        filter_row2.addWidget(self.sort_mode)

        self.group_by_product = QCheckBox("商品ごとにまとめる")
        self.group_by_product.setChecked(bool(
            self.config_manager.load().get("application_assistant", {}).get(
                "group_by_product", True
            )
        ))
        self.group_by_product.toggled.connect(self._toggle_group_by_product)
        filter_row2.addWidget(self.group_by_product)
        filter_layout.addLayout(filter_row2)

        favorites_input_row = QHBoxLayout()
        favorites_input_row.addWidget(QLabel("お気に入り都道府県："))
        assistant = self.config_manager.load().get("application_assistant", {})
        self.favorite_prefectures_input = QLineEdit()
        self.favorite_prefectures_input.setPlaceholderText("東京都, 大阪府（明示名のみ）")
        self.favorite_prefectures_input.setText(
            ", ".join(str(value) for value in assistant.get("favorite_prefectures", []))
        )
        favorites_input_row.addWidget(self.favorite_prefectures_input, 1)
        save_favorites = QPushButton("地域を保存")
        save_favorites.setObjectName("SmallButton")
        save_favorites.clicked.connect(self._save_favorite_prefectures)
        favorites_input_row.addWidget(save_favorites)
        filter_layout.addLayout(favorites_input_row)
        self.favorite_prefectures_only = QCheckBox("お気に入り地域のみ")
        self.favorite_stores_only = QCheckBox("お気に入り店舗のみ")
        self.new_only = QCheckBox("新着のみ")
        self.deadline_soon_only = QCheckBox("締切間近（72時間以内）")
        quick_filters = QGridLayout()
        for index, checkbox in enumerate((
            self.favorite_prefectures_only, self.favorite_stores_only,
            self.new_only, self.deadline_soon_only,
        )):
            checkbox.toggled.connect(self._apply_filters)
            quick_filters.addWidget(checkbox, index // 2, index % 2)
        filter_layout.addLayout(quick_filters)
        self.filter_panel.setVisible(False)
        layout.addWidget(self.filter_panel)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self._snapshot = None
        self._reload_favorites()
        self.reload(force=True)
        self.period_timer = QTimer(self)
        self.period_timer.setInterval(60_000)
        self.period_timer.timeout.connect(lambda: self.reload(force=True))
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

        self.reload(force=True)
        self.open_lottery_page.emit()

    def _toggle_filters(self):
        visible = not self.filter_panel.isVisible()
        self.filter_panel.setVisible(visible)
        self.filter_toggle.setText("絞り込みを隠す" if visible else "絞り込みを表示")

    def _toggle_group_by_product(self, enabled: bool):
        config = self.config_manager.load()
        config.setdefault("application_assistant", {})["group_by_product"] = bool(enabled)
        self.config_manager.save(config)
        self._apply_filters()

    def _reload_favorites(self):
        assistant = self.config_manager.load().get("application_assistant", {})
        self.favorite_prefectures = {
            str(value).strip() for value in assistant.get("favorite_prefectures", [])
            if str(value).strip()
        }
        self.favorite_store_keys = {
            str(value).strip() for value in assistant.get("favorite_stores", [])
            if str(value).strip()
        }

    def _save_favorite_prefectures(self):
        values = [
            value.strip()
            for value in self.favorite_prefectures_input.text().replace("、", ",").split(",")
            if value.strip()
        ]
        config = self.config_manager.load()
        config.setdefault("application_assistant", {})["favorite_prefectures"] = values
        self.config_manager.save(config)
        self._reload_favorites()
        self._apply_filters()

    def _toggle_favorite_store(self, row: dict):
        key = str(row.get("store_key") or "").strip()
        if not key:
            return
        config = self.config_manager.load()
        assistant = config.setdefault("application_assistant", {})
        values = {str(value) for value in assistant.get("favorite_stores", [])}
        if key in values:
            values.remove(key)
        else:
            values.add(key)
        assistant["favorite_stores"] = sorted(values)
        self.config_manager.save(config)
        self._reload_favorites()
        self._apply_filters()

    def _on_tcg_category_changed(self, key: str):
        index = self.tcg_filter.findData(key)
        self.tcg_filter.blockSignals(True)
        self.tcg_filter.setCurrentIndex(max(0, index))
        self.tcg_filter.blockSignals(False)
        self._apply_filters()

    def _on_legacy_tcg_filter_changed(self, _index: int):
        self.tcg_tabs.select_category(
            str(self.tcg_filter.currentData() or ALL_CATEGORY_KEY)
        )

    def reload(self, *_args, force: bool = False):
        if force or self._snapshot is None:
            self._snapshot = self.dashboard.build(state_filter="すべて", show_ended=True)
            self._refresh_prefectures(self._snapshot.get("rows", []))
            self._write_diagnostics(self._snapshot)
        self._apply_filters()

    def _write_diagnostics(self, data: dict):
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
                    f'ended={values.get("ended_rows", 0)} '
                    f'tcg_filter={values.get("excluded_tcg_filter", 0)} '
                    f'state_filter={values.get("excluded_state_filter", 0)} '
                    f'keyword={values.get("excluded_keyword", 0)}'
                )

    def _refresh_prefectures(self, rows: list[dict]):
        current = self.prefecture_filter.currentData() or "all"
        values = sorted({str(row.get("prefecture")) for row in rows
                         if row.get("prefecture") not in {None, "", "UNKNOWN"}})
        self.prefecture_filter.blockSignals(True)
        self.prefecture_filter.clear()
        self.prefecture_filter.addItem("すべて", "all")
        for value in values:
            self.prefecture_filter.addItem(value, value)
        self.prefecture_filter.addItem("地域不明", "UNKNOWN")
        index = self.prefecture_filter.findData(current)
        self.prefecture_filter.setCurrentIndex(max(0, index))
        self.prefecture_filter.blockSignals(False)

    def _apply_filters(self, *_args):
        if self._snapshot is None:
            return
        all_rows = self._snapshot.get("rows", [])
        active_count = sum(not row.get("period_ended") for row in all_rows)
        ended_count = sum(bool(row.get("period_ended")) for row in all_rows)
        self.period_tabs.blockSignals(True)
        self.period_tabs.setTabText(0, f"受付中 {active_count}")
        self.period_tabs.setTabText(1, f"応募期間終了 {ended_count}")
        self.period_tabs.blockSignals(False)

        state_filter = str(self.application_state_filter.currentData() or "すべて")
        period_filter = str(self.period_tabs.tabData(self.period_tabs.currentIndex()) or "active")
        favorite_filter = (
            "any" if self.favorite_prefectures_only.isChecked() and self.favorite_stores_only.isChecked()
            else "prefecture" if self.favorite_prefectures_only.isChecked()
            else "store" if self.favorite_stores_only.isChecked()
            else "all"
        )
        rows_before_sales = self.dashboard.filter_cached(
            all_rows, period_filter=period_filter,
            state_filter="すべて" if state_filter == "確認中" else state_filter,
            keyword=self.keyword.text(),
            tcg_filter=ALL_CATEGORY_KEY,
            sales_mode_filter=str(self.sales_mode_filter.currentData() or "all"),
            prefecture_filter=str(self.prefecture_filter.currentData() or "all"),
            product_category_filter=str(
                self.product_category_filter.currentData() or "all"
            ),
            favorites_filter=favorite_filter,
            favorite_prefectures=self.favorite_prefectures,
            favorite_store_keys=self.favorite_store_keys,
            new_only=self.new_only.isChecked(),
            deadline_soon_only=self.deadline_soon_only.isChecked(),
            sort_mode=self.sort_mode.currentText(),
        )
        if state_filter == "確認中":
            rows_before_sales = [
                row for row in rows_before_sales if row.get("is_candidate")
            ]
        sales_counts = {
            key: sum(sales_channel_matches(row.get("sales_mode"), key) for row in rows_before_sales)
            for key in ("all", "online", "store")
        }
        for index, label in enumerate(("すべて", "ネット販売", "店舗販売")):
            key = str(self.sales_tabs.tabData(index))
            self.sales_tabs.setTabText(index, f"{label} {sales_counts[key]}")
        sales_channel = str(self.sales_tabs.tabData(self.sales_tabs.currentIndex()) or "all")
        rows_after_sales = [
            row for row in rows_before_sales
            if sales_channel_matches(row.get("sales_mode"), sales_channel)
        ]
        self.region_tabs.setVisible(sales_channel == "store")
        region_filter = str(self.region_tabs.tabData(self.region_tabs.currentIndex()) or "all")
        rows_without_tcg = [
            row for row in rows_after_sales
            if sales_channel != "store" or region_filter == "all"
            or row.get("region") == region_filter
        ]
        self.tcg_tabs.set_counts(category_counts(rows_without_tcg))
        rows = list(filter_items_by_category(
            rows_without_tcg, self.tcg_tabs.selected_key
        ))

        state_counts = {state: sum(row.get("dashboard_state") == state for row in all_rows)
                        for state in ("未応募", "応募済み", "当選", "落選")}
        self.summary.setText(
            f'受付中 {active_count}　終了 {ended_count}　'
            f'未応募 {state_counts["未応募"]}　応募済み {state_counts["応募済み"]}　'
            f'当選 {state_counts["当選"]}　落選 {state_counts["落選"]}　'
            f'表示 {len(rows)}'
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

        if not rows:
            empty = QLabel(
                "応募管理できる販売・抽選情報がありません。"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("PageText")
            list_layout.addWidget(empty)
        elif self.group_by_product.isChecked():
            for group in self.dashboard._group_rows(rows):
                list_layout.addWidget(
                    ApplicationProductGroup(
                        group, self.store, lambda: self.reload(force=True), self._on_marked_applied,
                        self._toggle_favorite_store, self.favorite_store_keys,
                    )
                )
        else:
            for row in rows:
                list_layout.addWidget(
                    ApplicationRow(
                        row,
                        self.store,
                        lambda: self.reload(force=True),
                        self._on_marked_applied,
                        self._toggle_favorite_store,
                        self.favorite_store_keys,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

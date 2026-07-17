import time
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.candidate_manager import CandidateManager
from core.log_manager import LogManager
from core.retail_search_manager import RetailSearchManager
from core.source_manager import SourceManager
from core.tcg_categories import categories, display_name
from ui.tcg_category_tabs import (
    TcgCategoryTabs,
    category_counts,
    filter_items_by_category,
)


class RetailSearchWorker(QObject):
    progress = Signal(int, int, str)
    candidate_completed = Signal(str, list, list)
    completed = Signal(int, int)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        candidates: list[dict],
    ):
        super().__init__()
        self.candidates = candidates
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    @Slot()
    def run(self):
        try:
            searcher = RetailSearchManager()
            total = len(self.candidates)
            total_hits = 0

            for index, candidate in enumerate(
                self.candidates,
                start=1,
            ):
                if self._cancel_requested:
                    self.cancelled.emit()
                    return

                name = str(
                    candidate.get(
                        "name",
                        "名称未設定",
                    )
                )
                self.progress.emit(
                    index - 1,
                    total,
                    f"検索中：{name}",
                )

                hits, messages = searcher.search_candidate(
                    candidate
                )
                total_hits += len(hits)

                self.candidate_completed.emit(
                    str(candidate.get("id", "")),
                    hits,
                    messages,
                )

                self.progress.emit(
                    index,
                    total,
                    f"完了：{name}（{len(hits)}件）",
                )

            self.completed.emit(
                total,
                total_hits,
            )

        except Exception as error:
            self.failed.emit(str(error))


class CandidateCard(QFrame):
    def __init__(
        self,
        candidate: dict,
        search_callback,
        delete_callback,
        searching: bool,
    ):
        super().__init__()
        self.candidate = candidate
        self.setObjectName("ProductCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        layout.setSpacing(9)

        header = QHBoxLayout()

        title = QLabel(
            f'{display_name(candidate.get("tcg_key"), candidate.get("tcg"))} ｜ '
            + candidate.get(
                "name",
                "名称未設定",
            )
        )
        title.setObjectName("ProductName")
        title.setWordWrap(True)

        status = QLabel(
            candidate.get(
                "status",
                "検索待ち",
            )
        )
        status.setObjectName(
            "StatusOpen"
            if candidate.get("retail_hits")
            else "StatusLottery"
        )

        search_button = QPushButton(
            "販売・抽選情報を検索"
        )
        search_button.setObjectName(
            "AccentButton"
        )
        search_button.setEnabled(
            not searching
        )
        search_button.clicked.connect(
            lambda: search_callback(
                candidate.get("id", "")
            )
        )

        delete_button = QPushButton(
            "候補を削除"
        )
        delete_button.setObjectName(
            "DangerButton"
        )
        delete_button.setEnabled(
            not searching
        )
        delete_button.clicked.connect(
            lambda: delete_callback(
                candidate.get("id", "")
            )
        )

        header.addWidget(title, 1)
        header.addWidget(status)
        header.addWidget(search_button)
        header.addWidget(delete_button)

        source = QLabel(
            "情報元："
            + candidate.get(
                "source_name",
                "名称未設定",
            )
        )
        source.setObjectName("MutedText")

        release = QLabel(
            "発売日："
            + (
                candidate.get("release_date")
                or "未設定"
            )
        )
        release.setObjectName("MutedText")

        kind_and_added = QLabel(
            "商品種別："
            + str(candidate.get("product_kind", "その他"))
            + "　候補追加日時："
            + str(candidate.get("created_at", "未記録"))
        )
        kind_and_added.setObjectName("MutedText")

        confidence = float(
            candidate.get(
                "candidate_confidence",
                1.0,
            )
        )
        confidence_label = QLabel(
            f"商品候補の信頼度：{confidence:.0%}"
        )
        confidence_label.setObjectName(
            "MutedText"
        )

        last_searched = QLabel(
            "販売情報の最終検索："
            + (
                candidate.get("last_searched")
                or "未実行"
            )
        )
        last_searched.setObjectName(
            "MutedText"
        )

        layout.addLayout(header)
        layout.addWidget(source)
        layout.addWidget(release)
        layout.addWidget(kind_and_added)
        layout.addWidget(confidence_label)
        layout.addWidget(last_searched)

        official_url = candidate.get(
            "official_url",
            "",
        )
        if official_url:
            official = QLabel(
                "公式商品ページ："
                + official_url
            )
            official.setObjectName(
                "MutedText"
            )
            official.setWordWrap(True)
            official.setTextInteractionFlags(
                Qt.TextSelectableByMouse
            )
            layout.addWidget(official)

        hits = candidate.get(
            "retail_hits",
            [],
        )

        if hits:
            hit_title = QLabel(
                "検出した販売・抽選情報"
            )
            hit_title.setObjectName(
                "SectionTitle"
            )
            layout.addWidget(hit_title)

            for hit in hits:
                confidence = hit.get(
                    "confidence",
                    None,
                )
                confidence_text = (
                    f"（信頼度 {float(confidence):.0%}）"
                    if confidence is not None
                    else ""
                )

                hit_label = QLabel(
                    "・"
                    + hit.get(
                        "name",
                        "販売サイト",
                    )
                    + "："
                    + hit.get(
                        "status",
                        "情報あり",
                    )
                    + confidence_text
                    + "\n  "
                    + str(hit.get("price_status", "価格未確認"))
                    + " / 販売元: "
                    + str(hit.get("seller", "未確認"))
                    + (
                        "\n  "
                        + hit.get(
                            "notice",
                            "",
                        ).replace(
                            "\n",
                            "\n  ",
                        )
                        if hit.get("notice")
                        else ""
                    )
                )
                hit_label.setWordWrap(True)
                layout.addWidget(hit_label)

        diagnostics = candidate.get("search_diagnostics", {})
        if diagnostics:
            diagnostic_label = QLabel(
                "検索診断："
                f'検索店舗 {diagnostics.get("searched_store_count", 0)} / '
                f'発見 {diagnostics.get("found_store_count", 0)} / '
                f'正規販売 {diagnostics.get("regular_retail_count", 0)} / '
                f'除外 {diagnostics.get("excluded_count", 0)} / '
                f'新規店舗候補 {diagnostics.get("new_store_candidate_count", 0)}\n'
                "最終確認：" + str(diagnostics.get("checked_at", "未実行"))
            )
            diagnostic_label.setObjectName("MutedText")
            diagnostic_label.setWordWrap(True)
            layout.addWidget(diagnostic_label)

        search_message = candidate.get(
            "search_message",
            "",
        )
        if search_message:
            result = QLabel(search_message)
            result.setObjectName("MutedText")
            result.setWordWrap(True)
            layout.addWidget(result)


class CandidatesPage(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("ContentPanel")

        self.candidate_manager = CandidateManager()
        self.source_manager = SourceManager()
        self.log_manager = LogManager()

        self.search_thread = None
        self.search_worker = None
        self.searching = False
        self.search_summary: list[str] = []
        self.search_started_at = 0.0
        self.search_total_candidates = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            28,
            26,
            28,
            26,
        )
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("新弾候補")
        title.setObjectName("PageTitle")

        self.detect_button = QPushButton(
            "公式情報から候補を再読込"
        )
        self.detect_button.clicked.connect(
            self.detect_candidates
        )

        self.search_all_button = QPushButton(
            "全候補の販売情報を検索"
        )
        self.search_all_button.setObjectName(
            "AccentButton"
        )
        self.search_all_button.clicked.connect(
            self.search_all_candidates
        )

        self.cancel_button = QPushButton(
            "検索をキャンセル"
        )
        self.cancel_button.setObjectName(
            "DangerButton"
        )
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(
            self.cancel_search
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.detect_button)
        header.addWidget(self.search_all_button)
        header.addWidget(self.cancel_button)
        layout.addLayout(header)

        description = QLabel(
            "販売・抽選情報の検索はバックグラウンドで実行します。"
            "全候補検索は商品数や店舗数によって5～20分程度かかる場合があります。"
            "検索中も画面の移動や他の操作ができます。"
        )
        description.setObjectName("MutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        manual_card = QFrame()
        manual_card.setObjectName(
            "SettingsCard"
        )
        manual_layout = QHBoxLayout(
            manual_card
        )

        self.manual_name = QLineEdit()
        self.manual_name.setPlaceholderText(
            "候補の商品名"
        )
        self.manual_tcg = QComboBox()
        for category in categories(enabled_only=True):
            self.manual_tcg.addItem(category.display_name, category.key)

        self.manual_add_button = QPushButton(
            "候補を手動追加"
        )
        self.manual_add_button.clicked.connect(
            self.add_manual_candidate
        )

        manual_layout.addWidget(
            self.manual_name,
            1,
        )
        manual_layout.addWidget(self.manual_tcg)
        manual_layout.addWidget(
            self.manual_add_button
        )
        layout.addWidget(manual_card)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.category_tabs = TcgCategoryTabs()
        self.category_tabs.category_changed.connect(self._apply_category_filter)
        layout.addWidget(self.category_tabs)
        self._all_candidates: list[dict] = []

        self.result_label = QLabel("")
        self.result_label.setObjectName(
            "MutedText"
        )
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(
            QFrame.NoFrame
        )
        layout.addWidget(self.scroll, 1)

        self.reload_candidates()

    def detect_candidates(self) -> None:
        if self.searching:
            return

        sources = (
            self.source_manager.load_sources()
        )

        if not sources:
            QMessageBox.information(
                self,
                "情報ソースなし",
                "先に公式情報ソースを登録・確認してください。",
            )
            return

        new_items = (
            self.candidate_manager
            .build_candidates_from_sources(
                sources
            )
        )
        self.result_label.setText(
            f"{len(new_items)}件の候補を追加しました。"
        )
        self.reload_candidates()

    def search_candidate(
        self,
        candidate_id: str,
    ) -> None:
        if self.searching:
            return

        candidate = next(
            (
                item
                for item
                in self.candidate_manager
                .load_candidates()
                if item.get("id")
                == candidate_id
            ),
            None,
        )

        if candidate is None:
            return

        self._start_background_search(
            [candidate]
        )

    def search_all_candidates(self) -> None:
        if self.searching:
            return

        candidates = (
            self.candidate_manager
            .load_candidates()
        )

        if not candidates:
            QMessageBox.information(
                self,
                "候補なし",
                "検索対象の新弾候補がありません。",
            )
            return

        count = len(candidates)
        estimated_min = max(1, count)
        estimated_max = max(5, count * 4)

        message = QMessageBox(self)
        message.setIcon(
            QMessageBox.Warning
        )
        message.setWindowTitle(
            "全候補の販売情報を検索"
        )
        message.setText(
            "新弾候補に登録されている"
            f"{count}件すべての販売・抽選情報を検索します。"
        )
        message.setInformativeText(
            "商品数や各サイトの応答速度によっては、"
            f"およそ{estimated_min}～{estimated_max}分、"
            "またはそれ以上かかる場合があります。\n\n"
            "検索はバックグラウンドで実行されるため、"
            "検索中も他の画面を利用できます。\n"
            "途中で「検索をキャンセル」することもできます。"
        )
        start_button = message.addButton(
            "検索開始",
            QMessageBox.AcceptRole,
        )
        message.addButton(
            "キャンセル",
            QMessageBox.RejectRole,
        )
        message.setDefaultButton(
            start_button
        )
        message.exec()

        if message.clickedButton() is not start_button:
            return

        self._start_background_search(
            candidates
        )
    def _start_background_search(
        self,
        candidates: list[dict],
    ) -> None:
        self.searching = True
        self.search_summary = []
        self.search_started_at = time.monotonic()
        self.search_total_candidates = len(candidates)
        self._set_search_controls(True)

        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(
            max(1, len(candidates))
        )
        self.progress_bar.setValue(0)

        self.result_label.setText(
            f"販売・抽選情報をバックグラウンドで検索中です。"
            f"対象：{len(candidates)}件\n"
            "時間がかかる場合がありますが、他の画面は利用できます。"
        )

        self.search_thread = QThread(self)
        self.search_worker = RetailSearchWorker(
            candidates
        )
        self.search_worker.moveToThread(
            self.search_thread
        )

        self.search_thread.started.connect(
            self.search_worker.run
        )
        self.search_worker.progress.connect(
            self._on_search_progress
        )
        self.search_worker.candidate_completed.connect(
            self._on_candidate_completed
        )
        self.search_worker.completed.connect(
            self._on_search_completed
        )
        self.search_worker.failed.connect(
            self._on_search_failed
        )
        self.search_worker.cancelled.connect(
            self._on_search_cancelled
        )

        self.search_worker.completed.connect(
            self.search_thread.quit
        )
        self.search_worker.failed.connect(
            self.search_thread.quit
        )
        self.search_worker.cancelled.connect(
            self.search_thread.quit
        )
        self.search_thread.finished.connect(
            self._cleanup_search_thread
        )

        self.search_thread.start()

    @Slot(int, int, str)
    def _on_search_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        self.progress_bar.setMaximum(
            max(1, total)
        )
        self.progress_bar.setValue(current)

        elapsed = self._format_elapsed(
            time.monotonic()
            - self.search_started_at
        )
        percent = int(
            (current / max(1, total)) * 100
        )
        self.result_label.setText(
            f"{message}\n"
            f"進捗：{current}/{total}件（{percent}%）\n"
            f"経過時間：{elapsed}\n"
            "検索中も他の画面を利用できます。"
        )

    @Slot(str, list, list)
    def _on_candidate_completed(
        self,
        candidate_id: str,
        hits: list,
        messages: list,
    ) -> None:
        updated = (
            self.candidate_manager
            .update_search_result(
                candidate_id,
                hits=hits,
                messages=messages,
            )
        )

        name = (
            updated.get("name", "")
            if updated
            else candidate_id
        )
        self.search_summary.append(
            f"{name}: {len(hits)}件"
        )

        self.log_manager.write(
            f"バックグラウンド販売情報検索: "
            f"{name} / {len(hits)}件"
        )

        self.reload_candidates()

    @Slot(int, int)
    def _on_search_completed(
        self,
        total: int,
        total_hits: int,
    ) -> None:
        self.progress_bar.setValue(
            self.progress_bar.maximum()
        )
        elapsed = self._format_elapsed(
            time.monotonic()
            - self.search_started_at
        )
        summary_text = (
            "\n".join(self.search_summary)
            or "検索結果はありません。"
        )
        self.result_label.setText(
            f"検索完了（所要時間：{elapsed}）\n"
            + summary_text
        )
        QMessageBox.information(
            self,
            "販売情報検索完了",
            f"検索対象：{total}件\n"
            f"検出した販売・抽選情報：{total_hits}件\n"
            f"所要時間：{elapsed}",
        )
        self._finish_search()

    @Slot(str)
    def _on_search_failed(
        self,
        message: str,
    ) -> None:
        self.log_manager.write(
            f"バックグラウンド販売情報検索失敗: {message}",
            level="ERROR",
        )
        QMessageBox.critical(
            self,
            "検索エラー",
            "販売・抽選情報の検索中に"
            f"エラーが発生しました。\n\n{message}",
        )
        self.result_label.setText(
            "検索に失敗しました。"
        )
        self._finish_search()

    @Slot()
    def _on_search_cancelled(self) -> None:
        elapsed = self._format_elapsed(
            time.monotonic()
            - self.search_started_at
        )
        self.result_label.setText(
            f"検索をキャンセルしました。経過時間：{elapsed}"
        )
        self._finish_search()

    def cancel_search(self) -> None:
        if self.search_worker is None:
            return

        self.cancel_button.setEnabled(False)
        self.result_label.setText(
            "現在の店舗検索が終わり次第、"
            "キャンセルします..."
        )
        self.search_worker.request_cancel()

    def _finish_search(self) -> None:
        self.searching = False
        self._set_search_controls(False)
        self.reload_candidates()

    def _set_search_controls(
        self,
        active: bool,
    ) -> None:
        self.detect_button.setEnabled(
            not active
        )
        self.search_all_button.setEnabled(
            not active
        )
        self.manual_add_button.setEnabled(
            not active
        )
        self.manual_name.setEnabled(
            not active
        )
        self.cancel_button.setVisible(active)
        self.cancel_button.setEnabled(active)

    @Slot()
    def _cleanup_search_thread(self) -> None:
        if self.search_worker is not None:
            self.search_worker.deleteLater()
        if self.search_thread is not None:
            self.search_thread.deleteLater()

        self.search_worker = None
        self.search_thread = None


    @staticmethod
    def _format_elapsed(
        seconds: float,
    ) -> str:
        total_seconds = max(
            0,
            int(seconds),
        )
        minutes, remaining = divmod(
            total_seconds,
            60,
        )
        hours, minutes = divmod(
            minutes,
            60,
        )

        if hours:
            return (
                f"{hours}時間"
                f"{minutes}分"
                f"{remaining}秒"
            )
        if minutes:
            return (
                f"{minutes}分"
                f"{remaining}秒"
            )
        return f"{remaining}秒"

    def add_manual_candidate(self) -> None:
        if self.searching:
            return

        name = self.manual_name.text().strip()

        if not name:
            QMessageBox.warning(
                self,
                "商品名が空です",
                "候補の商品名を入力してください。",
            )
            return

        self.candidate_manager.add_manual_candidate(
            name,
            tcg_key=str(self.manual_tcg.currentData()),
        )
        self.manual_name.clear()
        self.result_label.setText(
            "候補を手動追加しました。"
        )
        self.reload_candidates()

    def delete_candidate(
        self,
        candidate_id: str,
    ) -> None:
        if self.searching:
            return

        answer = QMessageBox.question(
            self,
            "候補を削除",
            "この候補を削除しますか？",
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer == QMessageBox.Yes:
            self.candidate_manager.delete_candidate(
                candidate_id
            )
            self.reload_candidates()

    def reload_candidates(self) -> None:
        candidates = (
            self.candidate_manager
            .load_candidates()
        )
        self._all_candidates = candidates
        self.category_tabs.set_counts(category_counts(candidates))
        self._apply_category_filter(self.category_tabs.selected_key)

    def _apply_category_filter(self, category_key: str) -> None:
        candidates = list(
            filter_items_by_category(self._all_candidates, category_key)
        )

        container = QWidget()
        list_layout = QVBoxLayout(
            container
        )
        list_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        list_layout.setSpacing(12)

        if not candidates:
            empty = QLabel(
                "新弾候補はまだありません。\n"
                "公式情報ソースを手動確認すると、"
                "商品名と発売日がここへ追加されます。"
            )
            empty.setAlignment(
                Qt.AlignCenter
            )
            empty.setObjectName(
                "PageText"
            )
            list_layout.addWidget(empty)
        else:
            for candidate in candidates:
                list_layout.addWidget(
                    CandidateCard(
                        candidate,
                        self.search_candidate,
                        self.delete_candidate,
                        self.searching,
                    )
                )

        list_layout.addStretch()
        self.scroll.setWidget(container)

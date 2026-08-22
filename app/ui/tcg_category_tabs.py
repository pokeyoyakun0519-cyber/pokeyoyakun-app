from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabBar, QVBoxLayout, QWidget

from core.tcg_categories import categories, category_for_key, normalize_key


ALL_CATEGORY_KEY = "all"


def record_category_keys(record: Mapping[str, Any]) -> set[str]:
    raw_keys = record.get("tcg_keys")
    if not isinstance(raw_keys, (list, tuple, set)):
        raw_keys = [record.get("tcg_key")]
    output: set[str] = set()
    for raw_key in raw_keys:
        key, unknown = normalize_key(raw_key, record.get("tcg"))
        output.add("other" if unknown else key)
    return output or {"other"}


def filter_items_by_category(
    items: Iterable[Mapping[str, Any]], category_key: str
) -> list[Mapping[str, Any]]:
    values = list(items)
    if category_key == ALL_CATEGORY_KEY:
        return values
    return [item for item in values if category_key in record_category_keys(item)]


def category_counts(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    values = list(items)
    counts = {ALL_CATEGORY_KEY: len(values)}
    counts.update({category.key: 0 for category in categories(enabled_only=True)})
    for item in values:
        for key in record_category_keys(item):
            if key in counts:
                counts[key] += 1
    return counts


class TcgCategoryTabs(QWidget):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_key = ALL_CATEGORY_KEY
        self._keys = [ALL_CATEGORY_KEY] + [
            category.key for category in categories(enabled_only=True)
        ]
        self._counts = {key: 0 for key in self._keys}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setMovable(False)
        for key in self._keys:
            index = self.tab_bar.addTab(self._label(key, 0))
            self.tab_bar.setTabData(index, key)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        layout.addWidget(self.tab_bar)

    @property
    def selected_key(self) -> str:
        return self._selected_key

    def set_counts(self, counts: Mapping[str, int]) -> None:
        self._counts = {key: max(0, int(counts.get(key, 0))) for key in self._keys}
        for index, key in enumerate(self._keys):
            self.tab_bar.setTabText(index, self._label(key, self._counts[key]))
            self.tab_bar.setTabVisible(index, True)
        selected_index = self._keys.index(self._selected_key)
        if self.tab_bar.currentIndex() != selected_index:
            self.tab_bar.setCurrentIndex(selected_index)

    def select_category(self, key: str) -> None:
        if key not in self._keys:
            key = ALL_CATEGORY_KEY
        self._selected_key = key
        self.tab_bar.setTabVisible(self._keys.index(key), True)
        self.tab_bar.setCurrentIndex(self._keys.index(key))

    def _on_current_changed(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self._selected_key = self._keys[index]
            self.category_changed.emit(self._selected_key)

    @staticmethod
    def _label(key: str, count: int) -> str:
        if key == ALL_CATEGORY_KEY:
            name = "すべて"
        else:
            category = category_for_key(key)
            name = category.short_name if key == "yugioh" else category.display_name
        return f"{name} ({count})"

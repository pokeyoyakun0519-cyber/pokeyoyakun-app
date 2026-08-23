import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

from ui.application_dashboard_page import ApplicationDashboardPage
from ui.monitoring_candidate_page import MonitoringCandidatePage


WINDOW_SIZES = ((1280, 720), (1280, 800), (1366, 768), (1920, 1080))


def _inventory_report(count=149):
    states = (
        "NO_CURRENT_APPLICATION", "APP_REQUIRED", "SNS_ONLY",
        "ROBOTS_BLOCKED", "PARSER_NEEDED",
    )
    return {
        "generated_at": "2026-08-23T12:00:00+09:00",
        "inventory": [
            {
                "tcg": "pokemon" if index % 2 == 0 else "one_piece",
                "chain": f"chain_{index}",
                "display_name": (
                    "非常に長い正式チェーン店舗名称テスト株式会社"
                    if index == 0 else f"監視店舗 {index}"
                ),
                "official_url": f"https://example.com/store/{index}",
                "state": "STATUS_WITH_A_VERY_LONG_UNKNOWN_LABEL" if index == 1 else states[index % len(states)],
                "prefectures": ["東京都"] if index % 3 == 0 else [],
                "last_check": "2026-08-23T12:00:00+09:00",
                "monitoring_type": "WEB_DIRECT",
                "discovered_from": "RETAILER",
            }
            for index in range(count)
        ],
        "applications": [],
    }


def _application_rows(count=16):
    return [
        {
            "product_id": f"product-{index}",
            "product_name": f"応募商品 {index}",
            "tcg": "Pokemon",
            "tcg_key": "pokemon",
            "site_key": f"site-{index}",
            "site_name": f"応募店舗 {index}",
            "site_url": f"https://example.com/application/{index}",
            "application_url": f"https://example.com/application/{index}",
            "application_end_at": "2026-08-30T23:59:59+09:00",
            "remaining_text": "残り7日",
            "sales_mode": "ONLINE",
            "prefecture": "UNKNOWN",
            "application_state": "未応募",
            "dashboard_state": "未応募",
            "period_ended": False,
            "period_status": "受付中",
            "product_category": "CARD",
            "verification_status": "confirmed",
            "is_candidate": False,
            "is_restricted": False,
        }
        for index in range(count)
    ]


def _page_rect(widget: QWidget, page: QWidget) -> QRect:
    top_left = widget.mapTo(page, widget.rect().topLeft())
    return QRect(top_left, widget.size())


def _overlap_count(widgets, page):
    rects = [_page_rect(widget, page) for widget in widgets if widget.isVisible()]
    return sum(
        rects[left].intersects(rects[right])
        for left in range(len(rects))
        for right in range(left + 1, len(rects))
    )


class ResponsiveApplicationAndMonitoringLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dashboard_16_rows_and_empty_state_are_responsive(self):
        for count in (16, 0):
            snapshot = {
                "rows": _application_rows(count),
                "diagnostics": {},
                "diagnostics_by_tcg": {},
            }
            with self.subTest(application_count=count), tempfile.TemporaryDirectory() as root, patch.dict(
                os.environ, {"POKEYOYA_DATA_ROOT": root}, clear=False
            ), patch(
                "ui.application_dashboard_page.ApplicationDashboard.build",
                return_value=snapshot,
            ):
                page = ApplicationDashboardPage()
                self.assertFalse(hasattr(page, "source_inventory"))
                page.filter_panel.setVisible(True)
                for width, height in WINDOW_SIZES:
                    page.resize(width - 310, height - 70)
                    page.show()
                    self.app.processEvents()
                    self.assertEqual(
                        0,
                        _overlap_count(
                            (
                                page.prefecture_filter,
                                page.product_category_filter,
                                page.application_state_filter,
                            ),
                            page,
                        ),
                        (count, width, height, "primary filters"),
                    )
                    self.assertEqual(
                        0,
                        _overlap_count(
                            (page.verification_filter, page.sort_mode, page.group_by_product),
                            page,
                        ),
                        (count, width, height, "secondary filters"),
                    )
                    self.assertEqual(
                        Qt.ScrollBarAlwaysOff,
                        page.scroll.horizontalScrollBarPolicy(),
                    )
                    if count == 0:
                        self.assertLessEqual(page.scroll.height(), 120)
                    else:
                        self.assertGreaterEqual(page.scroll.height(), 220)
                page.period_timer.stop()
                page.close()

    def test_candidate_149_and_zero_rows_are_usable_at_supported_sizes(self):
        for count in (149, 0):
            report = _inventory_report(count)
            with self.subTest(candidate_count=count), patch(
                "ui.application_dashboard_page.load_saved_coverage",
                return_value=report,
            ):
                page = MonitoringCandidatePage()
                page.reload(report)
                self.assertEqual(count, page.inventory.table.rowCount())
                for width, height in WINDOW_SIZES:
                    page.resize(width - 310, height - 70)
                    page.show()
                    self.app.processEvents()
                    filters = (
                        page.inventory.state_filter,
                        page.inventory.tcg_filter,
                        page.inventory.region_filter,
                        page.inventory.prefecture_filter,
                        page.inventory.chain_filter,
                    )
                    self.assertEqual(0, _overlap_count(filters, page))
                    self.assertEqual(0, page.page_scroll.horizontalScrollBar().maximum())
                    if count:
                        row_height = max(1, page.inventory.table.rowHeight(0))
                        visible_rows = page.inventory.table.viewport().height() // row_height
                        self.assertGreaterEqual(visible_rows, 5, (width, height))
                        total_column_width = sum(
                            page.inventory.table.columnWidth(column)
                            for column in range(page.inventory.table.columnCount())
                        )
                        self.assertLessEqual(
                            total_column_width,
                            page.inventory.table.viewport().width() + 2,
                        )
                    else:
                        self.assertEqual(
                            "該当する監視候補はありません。",
                            page.inventory.detail.text(),
                        )
                if count:
                    long_name = next(
                        page.inventory.table.item(row, 0)
                        for row in range(count)
                        if page.inventory.table.item(row, 0).text().startswith("非常に長い")
                    )
                    self.assertEqual(long_name.text(), long_name.toolTip())
                    unknown = next(
                        page.inventory.table.item(row, 4)
                        for row in range(count)
                        if page.inventory.table.item(row, 0).text() == "監視店舗 1"
                    )
                    self.assertEqual("確認状況不明", unknown.toolTip())
                page.close()


if __name__ == "__main__":
    unittest.main()

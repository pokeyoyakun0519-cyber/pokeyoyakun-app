from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from PySide6.QtWidgets import QApplication

from core.public_roadmap import (
    CACHE_TTL_SECONDS,
    PUBLIC_ITEM_FIELDS,
    PUBLIC_ROADMAP_ORIGIN,
    STATUS_LABELS,
    TCG_LABELS,
    PublicRoadmapCache,
    PublicRoadmapClient,
    PublicRoadmapError,
    PublicRoadmapHttpsRedirectHandler,
    PublicRoadmapValidationError,
    RoadmapResult,
)
from ui.public_roadmap_page import PublicRoadmapPage


def public_item(cluster_id=7, **overrides):
    value = {
        "cluster_id": cluster_id,
        "title": "検索機能の改善",
        "summary": "商品を絞り込みやすくします。",
        "tcg_keys": ["pokemon"],
        "message_count": 12,
        "status": "in_development",
        "updated_at": "2026-07-17T10:00:00+00:00",
    }
    value.update(overrides)
    return value


def list_payload(items=None):
    items = [public_item()] if items is None else items
    return {
        "total": len(items),
        "page": 1,
        "page_size": 100,
        "generated_at": "2026-07-17T10:00:00+00:00",
        "categories": list(TCG_LABELS),
        "items": items,
    }


class FakeResponse:
    def __init__(self, data, *, status=200, headers=None):
        self.body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class QueueOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class MutableClock:
    def __init__(self, value=1_000.0):
        self.value = value

    def __call__(self):
        return self.value


class PublicRoadmapClientTest(unittest.TestCase):
    def make_client(self, directory, opener, clock=None):
        return PublicRoadmapClient(
            cache=PublicRoadmapCache(Path(directory) / "roadmap.json"),
            opener=opener,
            clock=clock or MutableClock(),
        )

    def test_list_uses_fixed_https_endpoint_and_allowed_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = QueueOpener(FakeResponse(list_payload(), headers={"ETag": '"v1"'}))
            client = self.make_client(directory, opener)
            result = client.list_roadmap("pokemon", "in_development")
            self.assertEqual(result.payload["items"][0]["title"], "検索機能の改善")
            url = opener.requests[0].full_url
            self.assertTrue(url.startswith(PUBLIC_ROADMAP_ORIGIN + "/api/v1/public/roadmap?"))
            self.assertIn("tcg_key=pokemon", url)
            self.assertIn("status=in_development", url)
            self.assertNotIn("license", url.lower())

    def test_unknown_filter_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = QueueOpener()
            client = self.make_client(directory, opener)
            with self.assertRaises(PublicRoadmapValidationError):
                client.list_roadmap("unknown", "")
            with self.assertRaises(PublicRoadmapValidationError):
                client.list_roadmap("", "private")
            self.assertEqual(opener.requests, [])

    def test_detail_uses_cluster_endpoint_and_public_allowlist(self):
        value = public_item(
            submitter_email="private@example.com",
            admin_note="internal",
            ai_prompt="secret prompt",
        )
        with tempfile.TemporaryDirectory() as directory:
            opener = QueueOpener(FakeResponse(value))
            result = self.make_client(directory, opener).roadmap_detail(7)
            self.assertEqual(set(result.payload), PUBLIC_ITEM_FIELDS)
            self.assertEqual(
                opener.requests[0].full_url,
                PUBLIC_ROADMAP_ORIGIN + "/api/v1/public/roadmap/7",
            )

    def test_five_minute_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = MutableClock()
            opener = QueueOpener(FakeResponse(list_payload()))
            client = self.make_client(directory, opener, clock)
            client.list_roadmap()
            clock.value += CACHE_TTL_SECONDS - 1
            result = client.list_roadmap()
            self.assertTrue(result.from_cache)
            self.assertFalse(result.offline)
            self.assertEqual(len(opener.requests), 1)

    def test_etag_is_sent_and_304_revalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = MutableClock()
            opener = QueueOpener(
                FakeResponse(list_payload(), headers={"ETag": '"roadmap-v1"'}),
                FakeResponse({}, status=304, headers={"ETag": '"roadmap-v1"'}),
            )
            client = self.make_client(directory, opener, clock)
            client.list_roadmap()
            clock.value += CACHE_TTL_SECONDS + 1
            result = client.list_roadmap()
            self.assertTrue(result.from_cache)
            self.assertFalse(result.offline)
            self.assertEqual(
                opener.requests[1].get_header("If-none-match"), '"roadmap-v1"'
            )
            clock.value += CACHE_TTL_SECONDS - 1
            client.list_roadmap()
            self.assertEqual(len(opener.requests), 2)

    def test_offline_uses_latest_stale_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = MutableClock()
            opener = QueueOpener(
                FakeResponse(list_payload()),
                urllib.error.URLError("offline"),
            )
            client = self.make_client(directory, opener, clock)
            client.list_roadmap()
            clock.value += CACHE_TTL_SECONDS + 1
            result = client.list_roadmap()
            self.assertTrue(result.from_cache)
            self.assertTrue(result.offline)
            self.assertEqual(result.payload["items"][0]["cluster_id"], 7)

    def test_network_failure_without_cache_is_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = QueueOpener(urllib.error.URLError("offline"))
            with self.assertRaisesRegex(PublicRoadmapError, "接続できません"):
                self.make_client(directory, opener).list_roadmap()

    def test_corrupt_cache_does_not_break_network_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.json"
            path.write_text(
                json.dumps({"schema_version": 1, "lists": [], "details": None}),
                encoding="utf-8",
            )
            client = PublicRoadmapClient(
                cache=PublicRoadmapCache(path),
                opener=QueueOpener(FakeResponse(list_payload())),
                clock=MutableClock(),
            )
            result = client.list_roadmap()
            self.assertEqual(result.payload["items"][0]["cluster_id"], 7)

    def test_cache_never_saves_private_or_internal_fields(self):
        unsafe = public_item(
            body="private body",
            reply_email="private@example.com",
            submitter_ip="192.0.2.1",
            admin_note="do not save",
            ai_internal={"confidence": 0.9},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roadmap.json"
            client = PublicRoadmapClient(
                cache=PublicRoadmapCache(path),
                opener=QueueOpener(FakeResponse(list_payload([unsafe]))),
                clock=MutableClock(),
            )
            client.list_roadmap()
            saved = path.read_text(encoding="utf-8")
            for forbidden in (
                "private body",
                "private@example.com",
                "submitter_ip",
                "admin_note",
                "ai_internal",
                "confidence",
            ):
                self.assertNotIn(forbidden, saved)
            data = json.loads(saved)
            cached_item = next(iter(data["lists"].values()))["payload"]["items"][0]
            self.assertEqual(set(cached_item), PUBLIC_ITEM_FIELDS)

    def test_http_other_host_and_other_port_redirects_are_rejected(self):
        handler = PublicRoadmapHttpsRedirectHandler()
        request = urllib.request.Request(PUBLIC_ROADMAP_ORIGIN + "/api/v1/public/roadmap")
        unsafe = (
            "http://pokeyoyakun.duckdns.org/api/v1/public/roadmap",
            "https://other.duckdns.org/api/v1/public/roadmap",
            "https://pokeyoyakun.duckdns.org:8443/api/v1/public/roadmap",
        )
        for target in unsafe:
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.URLError):
                    handler.redirect_request(request, None, 302, "redirect", {}, target)

    def test_all_public_status_and_tcg_labels_are_defined(self):
        self.assertEqual(
            list(STATUS_LABELS.values()),
            ["受付済み", "検討中", "実装予定", "開発中", "完成", "見送り"],
        )
        self.assertEqual(
            set(TCG_LABELS), {"pokemon", "onepiece", "yugioh", "gundam", "other"}
        )


class StaticClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def list_roadmap(self, tcg_key, status, *, force):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def roadmap_detail(self, cluster_id, *, force=False):
        return RoadmapResult(public_item(cluster_id))


class PublicRoadmapPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_has_all_filters_and_renders_public_columns(self):
        client = StaticClient(RoadmapResult(list_payload()))
        page = PublicRoadmapPage(client=client)
        page.reload_data(force=False)
        self.assertEqual(page.tcg_filter.count(), 6)
        self.assertEqual(page.status_filter.count(), 7)
        self.assertEqual(page.table.columnCount(), 6)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 4).text(), "開発中")

    def test_empty_state_is_explicit(self):
        page = PublicRoadmapPage(
            client=StaticClient(RoadmapResult(list_payload([])))
        )
        page.reload_data(force=False)
        self.assertEqual(page.table.rowCount(), 0)
        self.assertIn("該当する人気要望はありません", page.notice.text())

    def test_failure_keeps_existing_rows_and_allows_reload(self):
        client = StaticClient(RoadmapResult(list_payload()))
        page = PublicRoadmapPage(client=client)
        page.reload_data(force=False)
        client.error = PublicRoadmapError("一時的な通信失敗")
        page.reload_data(force=True)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertIn("再試行", page.notice.text())
        self.assertTrue(page.reload_button.isEnabled())
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()

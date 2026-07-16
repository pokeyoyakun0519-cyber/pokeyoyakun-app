from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from PySide6.QtWidgets import QApplication, QMessageBox

from core.feedback_api import (
    FEEDBACK_API_ORIGIN,
    FeedbackApiClient,
    FeedbackApiError,
    FeedbackHttpsRedirectHandler,
    FeedbackValidationError,
    SensitiveInputError,
    build_feedback_payload,
    build_store_request_payload,
)
from core.feedback_history import ALLOWED_FIELDS, FeedbackReceiptHistory
from ui.feedback_page import FeedbackPage


class FakeResponse:
    def __init__(self, data: dict):
        self.body = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class FakeOpener:
    def __init__(self, response: dict):
        self.response = FakeResponse(response)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return self.response


class FeedbackApiClientTest(unittest.TestCase):
    @patch("core.feedback_api.urllib.request.build_opener")
    def test_normal_feedback_submission(self, build_opener):
        opener = FakeOpener({"receipt_id": "FB-20260717-ABCDEF123456", "status": "pending"})
        build_opener.return_value = opener
        payload = build_feedback_payload(
            feedback_type="question",
            subject=" 使い方について ",
            body=" 操作方法を教えてください。 ",
            tcg_keys=["pokemon"],
            reply_requested=True,
            reply_email="user@example.com",
        )
        result = FeedbackApiClient().submit_feedback(payload)
        self.assertEqual(result["receipt_id"], "FB-20260717-ABCDEF123456")
        request = opener.requests[0]
        self.assertEqual(request.full_url, FEEDBACK_API_ORIGIN + "/api/v1/feedback")
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["message_type"], "other")
        self.assertEqual(sent["tcg_keys"], ["pokemon"])

    @patch("core.feedback_api.urllib.request.build_opener")
    def test_store_request_submission(self, build_opener):
        opener = FakeOpener({"receipt_id": "SR-20260717-ABCDEF123456", "status": "pending"})
        build_opener.return_value = opener
        payload = build_store_request_payload(
            store_name="カードショップ",
            official_url="https://shop.example.com/",
            discovery_url="https://example.net/news",
            tcg_keys=["onepiece", "gundam"],
            sales_scope="both",
            notes="予約と抽選を確認しました。",
        )
        FeedbackApiClient().submit_store_request(payload)
        request = opener.requests[0]
        self.assertEqual(
            request.full_url,
            FEEDBACK_API_ORIGIN + "/api/v1/store-requests",
        )
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["sales_scope"], "both")
        self.assertEqual(sent["tcg_keys"], ["onepiece", "gundam"])

    def test_store_request_requires_tcg(self):
        with self.assertRaises(FeedbackValidationError):
            build_store_request_payload(
                store_name="店舗",
                official_url="",
                discovery_url="",
                tcg_keys=[],
                sales_scope="reservation",
                notes="",
            )

    def test_whitespace_only_required_text_is_rejected(self):
        with self.assertRaises(FeedbackValidationError):
            build_feedback_payload(
                feedback_type="other",
                subject="   ",
                body="本文",
                tcg_keys=[],
                reply_requested=False,
                reply_email="",
            )

    def test_invalid_external_url_is_rejected(self):
        for value in (
            "broken",
            "ftp://example.com",
            "http://127.0.0.1/store",
            "https://example.com:bad/store",
        ):
            with self.subTest(value=value):
                with self.assertRaises(FeedbackValidationError):
                    build_store_request_payload(
                        store_name="店舗",
                        official_url=value,
                        discovery_url="",
                        tcg_keys=["pokemon"],
                        sales_scope="lottery",
                        notes="",
                    )

    def test_unknown_tcg_key_is_never_sent(self):
        with self.assertRaises(FeedbackValidationError):
            build_feedback_payload(
                feedback_type="bug",
                subject="件名",
                body="本文",
                tcg_keys=["unknown"],
                reply_requested=False,
                reply_email="",
            )

    def test_secret_like_input_is_warned_and_rejected(self):
        with self.assertRaises(SensitiveInputError):
            build_feedback_payload(
                feedback_type="bug",
                subject="認証できません",
                body="license_key=PKY-SECRET-VALUE",
                tcg_keys=[],
                reply_requested=False,
                reply_email="",
            )

    def test_http_other_host_and_other_port_redirects_are_rejected(self):
        handler = FeedbackHttpsRedirectHandler()
        request = urllib.request.Request(FEEDBACK_API_ORIGIN + "/api/v1/feedback")
        unsafe = (
            "http://pokeyoyakun.duckdns.org/api/v1/feedback",
            "https://other.duckdns.org/api/v1/feedback",
            "https://pokeyoyakun.duckdns.org:8443/api/v1/feedback",
        )
        for target in unsafe:
            with self.subTest(target=target):
                with self.assertRaises(urllib.error.URLError):
                    handler.redirect_request(request, None, 307, "redirect", {}, target)

    @patch("core.feedback_api.urllib.request.build_opener")
    def test_receipt_status_uses_kind_specific_endpoint(self, build_opener):
        opener = FakeOpener(
            {
                "receipt_id": "SR-20260717-ABCDEF123456",
                "status": "reviewing",
                "created_at": "2026-07-17T00:00:00+00:00",
                "updated_at": "2026-07-17T01:00:00+00:00",
                "body": "must not be returned",
            }
        )
        build_opener.return_value = opener
        result = FeedbackApiClient().receipt_status(
            "店舗追加依頼", "SR-20260717-ABCDEF123456"
        )
        self.assertEqual(set(result), {"receipt_id", "status", "created_at", "updated_at"})
        self.assertEqual(
            opener.requests[0].full_url,
            FEEDBACK_API_ORIGIN
            + "/api/v1/store-requests/receipts/SR-20260717-ABCDEF123456",
        )


class FeedbackHistoryTest(unittest.TestCase):
    def test_receipt_history_saves_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.json"
            history = FeedbackReceiptHistory(path)
            history.add("不具合", "FB-20260717-ABCDEF123456", "pending")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(data[0]), set(ALLOWED_FIELDS))
            serialized = json.dumps(data, ensure_ascii=False)
            self.assertNotIn("body", serialized)
            self.assertNotIn("email", serialized)
            history.update_status("FB-20260717-ABCDEF123456", "reviewing")
            self.assertEqual(history.load()[0]["last_status"], "reviewing")


class FailingClient:
    def __init__(self):
        self.calls = 0

    def submit_feedback(self, payload):
        self.calls += 1
        raise FeedbackApiError("通信に失敗しました。")


class ReentrantClient:
    def __init__(self):
        self.calls = 0
        self.page = None

    def submit_feedback(self, payload):
        self.calls += 1
        self.page.submit_current()
        return {"receipt_id": "FB-20260717-ABCDEF123456", "status": "pending"}


class FeedbackPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, client, directory):
        history = FeedbackReceiptHistory(Path(directory) / "receipts.json")
        return FeedbackPage(client=client, history=history)

    def test_page_exposes_five_submission_types_and_store_tcg_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            page = self.make_page(FailingClient(), directory)
            self.assertEqual(page.kind_combo.count(), 5)
            self.assertEqual(
                {page.kind_combo.itemText(index) for index in range(5)},
                {"使い方・質問", "不具合", "機能要望", "店舗追加依頼", "その他"},
            )
            self.assertEqual(
                set(page.store_tcg_checks),
                {"pokemon", "onepiece", "yugioh", "gundam", "other"},
            )

    def test_network_failure_keeps_input_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FailingClient()
            page = self.make_page(client, directory)
            page.subject.setText("消してはいけない件名")
            page.body.setPlainText("消してはいけない本文")
            with (
                patch("ui.feedback_page.QMessageBox.question", return_value=QMessageBox.Yes),
                patch("ui.feedback_page.QMessageBox.warning"),
            ):
                page.submit_current()
            self.assertEqual(client.calls, 1)
            self.assertEqual(page.subject.text(), "消してはいけない件名")
            self.assertEqual(page.body.toPlainText(), "消してはいけない本文")
            self.assertTrue(page.send_button.isEnabled())

    def test_reentrant_double_submission_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            client = ReentrantClient()
            page = self.make_page(client, directory)
            client.page = page
            page.subject.setText("件名")
            page.body.setPlainText("本文")
            with (
                patch("ui.feedback_page.QMessageBox.question", return_value=QMessageBox.Yes),
                patch("ui.feedback_page.QMessageBox.information"),
            ):
                page.submit_current()
            self.assertEqual(client.calls, 1)
            self.assertEqual(page.history.load()[0]["receipt_id"], "FB-20260717-ABCDEF123456")


if __name__ == "__main__":
    unittest.main()

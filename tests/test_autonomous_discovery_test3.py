from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from core.application_action import application_action
from core.application_dashboard import ApplicationDashboard
from core.application_status import JST
from core.config_manager import ConfigManager
from core.product_store import ProductStore
from core.pokemon_coverage_expansion import PokemonCoverageExpansionMonitor
from ui.application_dashboard_page import ApplicationRow


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=JST)
LIVEPOCKET = "https://livepocket.jp/e/cux1_"
OTAKARA = "https://www.otakarasouko.com/information/97450154"


def _verified(url: str) -> list[dict]:
    return [{
        "source_type": "OFFICIAL_APPLICATION_PAGE",
        "source_url": url,
        "trust": 100,
        "verification_status": "confirmed",
        "extracted_fields": {"application_url": url},
    }]


def _product(site: dict, *, tcg_key: str = "pokemon") -> dict:
    return {
        "id": f"p-{site['site_key']}",
        "name": "拡張パック「ストームエメラルダ」",
        "tcg_key": tcg_key,
        "release_date": "2026-08-08",
        "sites": [site],
    }


def _yellow_row() -> dict:
    return {
        "site_key": "yellow_submarine",
        "name": "イエローサブマリン",
        "url": LIVEPOCKET,
        "application_url": LIVEPOCKET,
        "application_path_type": "DIRECT_APPLICATION",
        "application_method": "Web抽選",
        "application_end_at": "2026-08-23T20:05:00+09:00",
        "status": "抽選受付中",
        "verification_status": "confirmed",
        "confirmed": True,
        "source_type": "OFFICIAL_APPLICATION_PAGE",
        "evidence": _verified(LIVEPOCKET),
    }


def _otakara_row() -> dict:
    return {
        "site_key": "otakarasouko",
        "name": "お宝創庫",
        "url": OTAKARA,
        "application_url": OTAKARA,
        "official_detail_url": OTAKARA,
        "application_path_type": "APP_REQUIRED",
        "application_method": "公式アプリで応募・店舗受取",
        "application_end_at": "2026-08-23T23:45:00+09:00",
        "status": "抽選受付中",
        "verification_status": "confirmed",
        "confirmed": True,
        "source_type": "OFFICIAL_STORE_PAGE",
        "evidence": [{"source_type": "OFFICIAL_STORE_PAGE", "source_url": OTAKARA,
                      "trust": 100, "verification_status": "confirmed"}],
    }


def test_yellow_submarine_livepocket_is_clickable_only_with_verified_evidence():
    action = application_action(_yellow_row())
    assert action == {
        "application_path_type": "DIRECT_APPLICATION",
        "application_action_label": "応募ページを開く",
        "application_action_url": LIVEPOCKET,
        "application_action_enabled": True,
        "application_action_guidance": "",
    }
    unverified = _yellow_row()
    unverified["evidence"] = []
    assert application_action(unverified)["application_action_enabled"] is False


def test_otakarasouko_uses_official_guidance_not_direct_application():
    action = application_action(_otakara_row())
    assert action["application_path_type"] == "APP_REQUIRED"
    assert action["application_action_label"] == "公式案内を開く"
    assert action["application_action_url"] == OTAKARA
    assert action["application_action_enabled"] is True
    assert action["application_action_guidance"] == "応募は公式アプリが必要"


def test_action_url_policy_rejects_dangerous_and_unverified_external_urls():
    for value in (
        "javascript:alert(1)", "file:///C:/Windows/win.ini",
        "https://localhost/apply", "https://127.0.0.1/apply",
        "https://livepocket.jp:444/e/test",
    ):
        row = _yellow_row()
        row["application_url"] = value
        assert application_action(row)["application_action_enabled"] is False


def test_stale_lawson_is_hidden_without_deleting_saved_data_and_open_unknown_stays():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        stale = {
            "site_key": "lawson_loppi", "name": "ローソン / Loppi",
            "url": "https://www.lawson.co.jp/lab/entertainment/",
            "status": "抽選情報あり", "application_method": "Loppi / 店頭 / Web",
            "verification_status": "confirmed",
            "last_verified_at": (NOW - timedelta(days=20)).isoformat(),
        }
        current = {
            "site_key": "current_unknown", "name": "現在受付店",
            "url": "https://www.pokemon-card.com/info/current",
            "status": "抽選受付中", "application_method": "店頭抽選",
            "verification_status": "confirmed",
            "last_verified_at": (NOW - timedelta(days=1)).isoformat(),
        }
        store = ProductStore(root)
        products = [_product(stale), _product(current)]
        store._save_product_file(products)
        before = (root / "data" / "products.json").read_bytes()
        result = ApplicationDashboard(store, ConfigManager(root)).build(
            now=NOW, show_ended=True,
        )
        assert [row["site_key"] for row in result["rows"]] == ["current_unknown"]
        assert result["diagnostics"]["excluded_stale_unknown"] == 1
        assert result["stale_exclusions"] == [{
            "tcg_key": "pokemon",
            "site_key": "lawson_loppi",
            "product_name": "拡張パック「ストームエメラルダ」",
            "site_name": "ローソン / Loppi",
            "reason": "last_verified_atから14日超更新なし",
            "reference_at": (NOW - timedelta(days=20)).isoformat(),
        }]
        assert (root / "data" / "products.json").read_bytes() == before


def test_unknown_deadline_seven_days_is_reverify_but_remains_visible():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        site = {
            "site_key": "review", "name": "再確認店",
            "url": "https://www.pokemon-card.com/info/review",
            "status": "抽選情報あり", "application_method": "店頭抽選",
            "verification_status": "confirmed",
            "detected_at": (NOW - timedelta(days=8)).isoformat(),
        }
        store = ProductStore(root)
        store._save_product_file([_product(site)])
        row = ApplicationDashboard(store, ConfigManager(root)).build(now=NOW)["rows"][0]
        assert row["freshness_status"] == "REVERIFY_UNKNOWN"
        assert row["reverify_unknown"] is True


def test_phase1_extractor_sets_path_type_and_verification_time():
    yellow, reason = PokemonCoverageExpansionMonitor.verify_official_document(
        """<meta property='og:title' content='ストームエメラルダ購入権抽選'>
        <main>販売元 イエローサブマリン ポケモンカードゲーム MEGA 拡張パック
        「ストームエメラルダ」 販売受付期間 2026年8月17日 09:00 ～
        2026年8月23日 20:05</main>""",
        LIVEPOCKET,
        discovery_url="https://pokesoku.com/lottery-2026-08/",
        observed_at=NOW,
    )
    assert reason == ""
    assert yellow["hit"]["application_path_type"] == "DIRECT_APPLICATION"
    assert yellow["hit"]["last_verified_at"] == NOW.isoformat(timespec="seconds")


def test_application_row_labels_match_path_types():
    app = QApplication.instance() or QApplication([])
    del app
    with tempfile.TemporaryDirectory() as folder, patch.dict(
        os.environ, {"POKEYOYA_DATA_ROOT": folder}, clear=False
    ):
        yellow = ApplicationRow(_yellow_row(), Mock(), Mock(), Mock())
        otakara = ApplicationRow(_otakara_row(), Mock(), Mock(), Mock())
        yellow_buttons = {button.text(): button for button in yellow.findChildren(QPushButton)}
        otakara_buttons = {button.text(): button for button in otakara.findChildren(QPushButton)}
        assert yellow_buttons["応募ページを開く"].isEnabled()
        assert otakara_buttons["公式案内を開く"].isEnabled()
        assert any(
            label.text() == "応募は公式アプリが必要"
            for label in otakara.findChildren(QLabel)
        )
        yellow.close()
        otakara.close()

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from core.application_coverage_report import build_application_coverage
from core.application_dashboard import ApplicationDashboard
from core.candidate_manager import CandidateManager
from core.product_store import ProductStore
from core.pokemon_coverage_expansion import (
    JST,
    PokemonCoverageExpansionMonitor,
)


DISCOVERY = "https://pokesoku.com/lottery-2026-08/"
YELLOW = "https://livepocket.jp/e/cux1_"
HARERUYA = "https://livepocket.jp/e/jl2b2"
OTAKARA = "https://www.otakarasouko.com/information/97450154"


class _Fetcher:
    def __init__(self, documents: dict[str, str]) -> None:
        self.documents = documents
        self.calls: list[str] = []

    def fetch(self, url: str, **_kwargs):
        self.calls.append(url)
        html = self.documents.get(url)
        return {
            "ok": html is not None,
            "status": 200 if html is not None else "HTTP_ERROR",
            "url": url,
            "html": html or "",
        }

    def diagnostics(self):
        return {"request_count": len(self.calls)}


def _documents() -> dict[str, str]:
    return {
        DISCOVERY: f"""
            <main><a href="{YELLOW}">イエローサブマリン</a>
            <a href="{HARERUYA}">晴れる屋2</a>
            <a href="{OTAKARA}">お宝創庫</a>
            <a href="https://x.com/example">X</a></main>
        """,
        YELLOW: """
            <meta property="og:title" content="８月下旬再販：ポケモンカードゲーム『ストームエメラルダ』購入権抽選">
            <main>販売元 イエローサブマリン
            ポケモンカードゲーム MEGA 拡張パック「ストームエメラルダ」
            販売受付期間 2026年8月17日(月) 09:00 〜2026年8月23日(日) 20:05</main>
        """,
        HARERUYA: """
            <meta property="og:title" content="晴れる屋2 通販『スターターセットex』購入権">
            <main>販売元 株式会社晴れる屋 ポケモンカードゲーム スターターセットex
            抽選販売受付 販売受付期間 2026年8月18日(火) 17:00 〜2026年8月24日(月) 17:00</main>
        """,
        OTAKARA: """
            <meta property="og:title" content="【アプリ会員様限定】再版/ポケモンカードゲーム4種 抽選販売に関して">
            <main>ポケモンカードゲーム 再販4商品 抽選販売
            2026年08月20日(木) ひる12時 ～ 2026年08月23日(日) 23時45分
            ご応募は お宝創庫グループアプリ より。店舗で受取。</main>
        """,
    }


def _scan(root: Path):
    monitor = PokemonCoverageExpansionMonitor(
        root,
        fetcher=_Fetcher(_documents()),
        now=lambda: datetime(2026, 8, 23, 12, 0, tzinfo=JST),
    )
    return monitor.scan(force=True), monitor.diagnostics


def test_tier_b_only_discovers_and_three_official_pages_confirm():
    with tempfile.TemporaryDirectory() as folder:
        discoveries, diagnostics = _scan(Path(folder))
    assert {item["hit"]["site_key"] for item in discoveries} == {
        "yellow_submarine", "hareruya2", "otakarasouko",
    }
    assert all(item["hit"]["verification_status"] == "confirmed" for item in discoveries)
    assert all(item["hit"]["evidence"][0]["trust"] == 100 for item in discoveries)
    assert diagnostics["official_verified"] == 3
    assert diagnostics["new_verified_domains"] == [
        "livepocket.jp", "www.otakarasouko.com",
    ]


def test_unverified_livepocket_seller_and_unknown_deadline_are_not_confirmed():
    unknown_seller, reason = PokemonCoverageExpansionMonitor.verify_official_document(
        "<main>ポケモンカード 抽選 販売受付期間 2026年8月1日 10:00 ～2026年8月30日 10:00 販売元 不明店</main>",
        "https://livepocket.jp/e/unknown",
        discovery_url=DISCOVERY,
        observed_at=datetime(2026, 8, 23, tzinfo=JST),
    )
    assert unknown_seller is None
    assert reason == "seller_not_verified"

    no_deadline, reason = PokemonCoverageExpansionMonitor.verify_official_document(
        "<main>ポケモンカード 抽選販売 ご応募はお宝創庫グループアプリより</main>",
        "https://www.otakarasouko.com/information/1/",
        discovery_url=DISCOVERY,
        observed_at=datetime(2026, 8, 23, tzinfo=JST),
    )
    assert no_deadline is None
    assert reason == "deadline_unknown"


def test_non_card_labo_realistic_flow_reaches_product_store_and_dashboard():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        discoveries, _diagnostics = _scan(root)
        merged = CandidateManager(root).merge_application_discoveries(
            discoveries,
            matcher=lambda _candidate, _record: False,
        )
        assert merged == {"created": 3, "updated": 3, "ambiguous": 0}
        store = ProductStore(root)
        dashboard = ApplicationDashboard(store)
        result = dashboard.build(
            show_ended=False,
            now=datetime(2026, 8, 23, 12, 0, tzinfo=JST),
        )
        assert len(result["rows"]) == 3
        assert {row["site_key"] for row in result["rows"]} == {
            "yellow_submarine", "hareruya2", "otakarasouko",
        }
        assert all(row["verification_status"] == "confirmed" for row in result["rows"])

        coverage = build_application_coverage(
            discoveries,
            dashboard_rows=result["rows"],
            now=datetime(2026, 8, 23, 12, 0, tzinfo=JST),
        )["by_tcg"]["pokemon"]
        assert coverage["active_chain_count"] == 3
        assert coverage["dominant_chain_ratio"] == 0.333

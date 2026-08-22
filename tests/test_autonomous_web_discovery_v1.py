from __future__ import annotations

import json
import socket
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from core.autonomous_source_registry import OfficialSourceCandidateStore
from core.autonomous_web_discovery import AutonomousApplicationSourceDiscovery
from core.application_dashboard import ApplicationDashboard
from core.candidate_manager import CandidateManager
from core.generic_official_application_parser import GenericOfficialApplicationParser
from core.safe_discovery_fetcher import (
    MAX_RESPONSE_BYTES,
    RequestBudget,
    SafeDiscoveryFetcher,
    UnsafeDiscoveryUrl,
)
from core.product_store import ProductStore


def _seed_file(root: Path, seeds: list[dict]) -> Path:
    path = root / "seeds.json"
    path.write_text(json.dumps({"schema_version": 1, "seeds": seeds}), encoding="utf-8")
    return path


def _seed(
    source_id: str,
    url: str,
    *,
    tier: str = "TIER_A_OFFICIAL",
    tcg: str = "pokemon",
) -> dict:
    return {
        "id": source_id,
        "name": source_id,
        "base_url": url,
        "official_domains": [url.split("/")[2]],
        "seed_type": "MANUFACTURER" if "manufacturer" in source_id else "DISCOVERY",
        "trust_tier": tier,
        "supported_tcg": [tcg],
        "discovery_paths": ["/news/"],
        "enabled": True,
    }


class _FakeFetcher:
    def __init__(self, documents: dict[str, str]) -> None:
        self.documents = documents
        self.calls: list[str] = []

    def fetch(self, url: str, **_kwargs) -> dict:
        self.calls.append(url)
        html = self.documents.get(url)
        if html is None:
            return {"ok": False, "status": "HTTP_ERROR", "url": url, "html": ""}
        return {"ok": True, "status": 200, "url": url, "html": html}

    def mark_parsed(self, _url: str) -> None:
        return None

    def diagnostics(self) -> dict:
        return {"request_count": len(self.calls)}


class AutonomousWebDiscoveryE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _engine(self, seeds: list[dict], documents: dict[str, str]):
        registry = OfficialSourceCandidateStore(self.root, _seed_file(self.root, seeds))
        fetcher = _FakeFetcher(documents)
        return AutonomousApplicationSourceDiscovery(
            self.root,
            registry=registry,
            fetcher=fetcher,
            max_depth=2,
            max_urls_per_source=5,
        ), registry, fetcher

    def test_manual_registration_is_not_needed_for_seed_to_dashboard_discovery(self):
        seed_url = "https://manufacturer.example/stores"
        shop_url = "https://official-shop.example/news/lottery"
        engine, registry, fetcher = self._engine(
            [_seed("manufacturer_a", seed_url)],
            {
                seed_url: (
                    '<main>ポケモンカード 公認店一覧 '
                    f'<a href="{shop_url}">公式店舗B SHOP</a></main>'
                ),
                shop_url: (
                    '<article><h1>ポケモンカード 新商品「拡張パック テスト」抽選販売</h1>'
                    '<p>応募受付 2026年8月23日から2026年8月30日まで 店頭受取</p>'
                    '<a href="https://official-shop.example/apply/1">応募フォーム</a></article>'
                ),
            },
        )
        result = engine.run({"pokemon"})
        self.assertEqual(1, len(result["source_candidates"]))
        self.assertEqual(1, len(result["discoveries"]))
        hit = result["discoveries"][0]["hit"]
        self.assertTrue(hit["confirmed"])
        self.assertEqual("confirmed", hit["verification_status"])
        self.assertIn("official-shop.example", " ".join(fetcher.calls))
        learned = next(item for item in registry.records if item["id"].startswith("discovered_"))
        self.assertEqual("MONITORABLE", learned["source_state"])
        self.assertTrue(learned["enabled"])

        manager = CandidateManager(self.root)
        merged = manager.merge_application_discoveries(
            result["discoveries"], matcher=lambda _candidate, _record: False
        )
        self.assertEqual(1, merged["created"])
        store = ProductStore(self.root)
        products = store._load_product_file()
        self.assertEqual(1, len(products))
        dashboard_service = ApplicationDashboard()
        dashboard_service.store = store
        dashboard = dashboard_service.build(show_ended=False)
        self.assertEqual(1, len(dashboard["rows"]))
        self.assertEqual("confirmed", dashboard["rows"][0]["verification_status"])

    def test_third_party_only_never_confirms_or_auto_promotes(self):
        url = "https://discovery.example/article"
        destination = "https://unknown-shop.example/lottery"
        engine, registry, _fetcher = self._engine(
            [_seed("third_party", url, tier="TIER_B_DISCOVERY")],
            {url: (
                '<article>ポケモンカード「商品X」抽選販売 応募受付 2026/8/30まで '
                f'<a href="{destination}">公式店舗応募</a></article>'
            )},
        )
        result = engine.run({"pokemon"})
        self.assertEqual(1, len(result["discoveries"]))
        self.assertFalse(result["discoveries"][0]["hit"]["confirmed"])
        self.assertEqual([], result["source_candidates"])
        self.assertFalse(any(item["base_url"] == destination for item in registry.records))

    def test_official_page_to_external_form_uses_primary_and_secondary_evidence(self):
        url = "https://shop.example/news/1"
        engine, _registry, _fetcher = self._engine(
            [_seed("manufacturer_shop", url)],
            {url: (
                '<article>ポケモンカード「商品Y」抽選販売 応募受付 2026/8/30まで オンライン'
                '<a href="https://forms.gle/abcdef">Web抽選 応募フォーム</a></article>'
            )},
        )
        hit = engine.run({"pokemon"})["discoveries"][0]["hit"]
        self.assertTrue(hit["confirmed"])
        self.assertEqual("https://forms.gle/abcdef", hit["application_url"])
        self.assertEqual(
            ["OFFICIAL_MANUFACTURER", "OFFICIAL_LINKED_FORM"],
            [item["source_type"] for item in hit["evidence"]],
        )

    def test_false_positive_event_article_is_rejected(self):
        url = "https://manufacturer.example/news/event"
        engine, _registry, _fetcher = self._engine(
            [_seed("manufacturer_event", url)],
            {url: "<article>ポケモンカード 大会参加抽選 プレゼントキャンペーン 2026/8/30</article>"},
        )
        result = engine.run({"pokemon"})
        self.assertEqual([], result["discoveries"])
        self.assertGreaterEqual(result["diagnostics"]["rejection_reasons"]["false_positive_context"], 1)

    def test_same_application_from_two_sources_is_deduplicated(self):
        application = "https://forms.gle/same"
        seeds = [
            _seed("manufacturer_one", "https://one.example/news/1"),
            _seed("manufacturer_two", "https://two.example/news/2"),
        ]
        body = (
            '<article>ポケモンカード「同一商品」抽選販売 応募受付 2026/8/30まで 店舗受取'
            f'<a href="{application}">Web抽選 応募フォーム</a></article>'
        )
        engine, _registry, _fetcher = self._engine(
            seeds,
            {"https://one.example/news/1": body, "https://two.example/news/2": body},
        )
        result = engine.run({"pokemon"})
        self.assertEqual(1, len(result["discoveries"]))
        self.assertEqual(3, len(result["discoveries"][0]["hit"]["evidence"]))

    def test_parser_drift_requires_two_empty_successes(self):
        url = "https://manufacturer.example/news/1"
        registry = OfficialSourceCandidateStore(
            self.root, _seed_file(self.root, [_seed("manufacturer_drift", url)])
        )
        record = registry.records[0]
        record["successful_application_pages"] = 1
        self.assertEqual(
            "NO_CURRENT_APPLICATION",
            registry.observe_parser(record["id"], fetch_ok=True, application_count=0),
        )
        self.assertEqual(
            "PARSER_OUTDATED",
            registry.observe_parser(record["id"], fetch_ok=True, application_count=0),
        )

    def test_unknown_official_candidate_blocked_by_robots_stays_quarantined(self):
        seed_url = "https://manufacturer.example/stores"
        blocked_url = "https://blocked-shop.example/news/lottery"

        class BlockedFetcher(_FakeFetcher):
            def fetch(self, url: str, **_kwargs) -> dict:
                self.calls.append(url)
                if url == blocked_url:
                    return {"ok": False, "status": "ROBOTS_BLOCKED", "url": url, "html": ""}
                return super().fetch(url, **_kwargs)

        registry = OfficialSourceCandidateStore(
            self.root,
            _seed_file(self.root, [_seed("manufacturer_blocked", seed_url)]),
        )
        fetcher = BlockedFetcher({
            seed_url: (
                '<main>ポケモンカード 公認店一覧 '
                f'<a href="{blocked_url}">公式店舗 SHOP</a></main>'
            )
        })
        engine = AutonomousApplicationSourceDiscovery(
            self.root, registry=registry, fetcher=fetcher
        )
        result = engine.run({"pokemon"})
        candidate = next(item for item in registry.records if item["id"].startswith("discovered_"))
        self.assertEqual("BLOCKED_ROBOTS", candidate["source_state"])
        self.assertFalse(candidate["enabled"])
        self.assertEqual([], result["discoveries"])

    def test_social_share_link_never_becomes_an_official_source_candidate(self):
        seed_url = "https://manufacturer.example/stores"
        share_url = "https://twitter.com/intent/tweet?url=https%3A%2F%2Fshop.example%2Fstore"
        engine, registry, fetcher = self._engine(
            [_seed("manufacturer_social", seed_url)],
            {seed_url: (
                '<main>ポケモンカード 公式店舗一覧 '
                f'<a href="{share_url}">LINE ポスト</a></main>'
            )},
        )
        result = engine.run({"pokemon"})
        self.assertEqual([], result["source_candidates"])
        self.assertFalse(any(item["id"].startswith("discovered_") for item in registry.records))
        self.assertNotIn(share_url, fetcher.calls)

    def test_generic_official_outbound_link_needs_explicit_shop_context(self):
        seed_url = "https://manufacturer.example/news"
        unrelated_url = "https://publisher.example/campaign"
        engine, registry, _fetcher = self._engine(
            [_seed("manufacturer_links", seed_url)],
            {seed_url: (
                '<main>ポケモンカード 新着情報 '
                f'<a href="{unrelated_url}">詳しくはこちら</a></main>'
            )},
        )
        result = engine.run({"pokemon"})
        self.assertEqual([], result["source_candidates"])
        self.assertFalse(any(item["id"].startswith("discovered_") for item in registry.records))


class GenericOfficialParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = GenericOfficialApplicationParser()

    def test_extended_tcg_classification(self):
        cases = {
            "遊戯王OCG DUAD「商品A」抽選販売 応募受付 2026/8/30": "yugioh",
            "ガンダムカードゲーム GD01「商品B」抽選販売 応募受付 2026/8/30": "gundam",
            "UNION ARENA UA01BT「商品C」抽選販売 応募受付 2026/8/30": "union_arena",
            "デュエル・マスターズ DM25-RP1「商品D」抽選販売 応募受付 2026/8/30": "duelmasters",
            "ヴァイスシュヴァルツ「商品E」抽選販売 応募受付 2026/8/30": "weiss",
            "Magic: The Gathering MTG「商品F」抽選販売 応募受付 2026/8/30": "mtg",
        }
        for index, (text, expected) in enumerate(cases.items()):
            with self.subTest(tcg=expected):
                value = self.parser.parse(f"<article>{text}</article>", f"https://official.example/news/{index}")
                self.assertEqual(expected, value["tcg_key"])
                self.assertTrue(value["is_application"])

    def test_unknown_domain_content_stays_parser_result_not_official_decision(self):
        value = self.parser.parse(
            "<article>ポケモンカード「商品」抽選販売 応募受付 2026/8/30</article>",
            "https://unknown.example/news/1",
        )
        self.assertTrue(value["is_application"])
        self.assertNotIn("confirmed", value)

    def test_shop_index_cannot_combine_unrelated_page_fragments_into_application(self):
        value = self.parser.parse(
            '<main>デュエル・マスターズ 抽選販売 応募受付 2026/8/30 '
            'オンライン <a href="/apply">応募フォーム</a> '
            'おすすめ「LEGACYSOUL ミクロマン コマンド1号4体セット」</main>',
            "https://takaratomymall.example/shop/",
            tcg_hint=["duelmasters"],
        )
        self.assertEqual("index", value["page_kind"])
        self.assertFalse(value["is_application"])
        self.assertEqual("", value["product_code"])

    def test_product_code_identity_normalizes_compact_one_piece_code(self):
        value = self.parser.parse(
            '<article>ONE PIECE CARD GAME ブースターパック「世界最強の戦士」 OP17 '
            '抽選販売 応募受付 2026/8/30</article>',
            "https://official.example/news/op17-lottery",
        )
        self.assertEqual("OP-17", value["product_code"])
        self.assertEqual("世界最強の戦士", value["product_name"])


class _Response:
    def __init__(self, payload: bytes, *, final_url: str = "https://public.example/news", status: int = 200):
        self.payload = payload
        self.final_url = final_url
        self.status = status
        self.headers = Message()

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def geturl(self) -> str:
        return self.final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _public_resolver(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class SafeDiscoveryFetcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dangerous_schemes_and_local_addresses_are_rejected(self):
        fetcher = SafeDiscoveryFetcher(self.root, resolver=_public_resolver)
        for url in (
            "javascript:alert(1)", "file:///etc/passwd", "http://public.example/",
            "https://localhost/", "https://127.0.0.1/", "https://169.254.1.1/",
            "https://10.0.0.1/", "https://[::1]/", "https://[fe80::1]/",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeDiscoveryUrl):
                fetcher.validate_url(url)

    def test_private_dns_answer_is_rejected(self):
        resolver = lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", port))
        ]
        with self.assertRaises(UnsafeDiscoveryUrl):
            SafeDiscoveryFetcher(self.root, resolver=resolver).validate_url("https://public.example/")

    def test_redirect_to_localhost_is_rejected(self):
        fetcher = SafeDiscoveryFetcher(
            self.root,
            resolver=_public_resolver,
            opener=lambda *_args, **_kwargs: _Response(b"ok", final_url="https://127.0.0.1/private"),
        )
        result = fetcher.fetch("https://public.example/news", require_robots=False)
        self.assertEqual("SECURITY_REJECTED", result["status"])

    def test_oversized_response_is_rejected(self):
        fetcher = SafeDiscoveryFetcher(
            self.root,
            resolver=_public_resolver,
            opener=lambda *_args, **_kwargs: _Response(b"x" * (MAX_RESPONSE_BYTES + 1)),
        )
        result = fetcher.fetch("https://public.example/news", require_robots=False)
        self.assertEqual("RESPONSE_TOO_LARGE", result["status"])

    def test_shift_jis_is_decoded_and_budget_is_enforced(self):
        response = _Response("ポケモンカード 抽選".encode("cp932"))
        response.headers["Content-Type"] = "text/html; charset=shift_jis"
        fetcher = SafeDiscoveryFetcher(
            self.root,
            resolver=_public_resolver,
            opener=lambda *_args, **_kwargs: response,
            budget=RequestBudget(global_max=1, per_domain_max=1),
        )
        first = fetcher.fetch("https://public.example/news", require_robots=False)
        second = fetcher.fetch("https://other.example/news", require_robots=False)
        self.assertIn("ポケモンカード", first["html"])
        self.assertEqual("BUDGET_EXHAUSTED", second["status"])


if __name__ == "__main__":
    unittest.main()

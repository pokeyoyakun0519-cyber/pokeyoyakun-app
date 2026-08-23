from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.application_action import application_action
from core.pokemon_official_campaigns import (
    JST,
    PokemonOfficialCampaignMonitor,
)


NOW = datetime(2026, 8, 23, 10, 0, tzinfo=JST)
POKEMON_STORE_URL = "https://shop.pokemon.co.jp/ja/shop/common/news/202608/000451.html"
KIDS_URL = "https://www.kidsrepublic.jp/campaign/campaign_detail/20260916_pokemoncardgame"
FURUICHI_URL = "https://furu1.net/news/news_campaign/news_opensale_shin"


POKEMON_STORE_HTML = """
<meta property="og:title" content="ポケモンカードストア 事前抽選">
<p>対象商品 ・ポケモンカードゲーム MEGA 拡張パック「30th CELEBRATION」</p>
<p>商品の詳細をご覧ください。抽選 応募</p>
<p>お申し込み受付期間：8月21日（金）14時 ～ 9月8日（火）23時59分</p>
<p>店舗名：ポケモンカードストア in イオンモール旭川駅前</p>
<p>住所：北海道旭川市宮下通7丁目2-5 応募URL</p>
<a href="https://miniapp.line.me/a/events/one">応募</a>
<p>店舗名：ポケモンカードストア in イオンモール川口前川</p>
<p>住所：埼玉県川口市前川1丁目1-11 応募URL</p>
<a href="https://miniapp.line.me/a/events/two">応募</a>
"""

KIDS_HTML = """
<h1>ポケモンカードゲーム MEGA 拡張パック 30th CELEBRATION</h1>
<p>抽選 応募</p>
<p>対象商品 9/16発売予定 ポケモンカードゲーム MEGA 拡張パック
30th CELEBRATION</p>
<p>受取指定が可能な店舗 本州・四国のイオン・イオンスタイル・スーパーセンター
の直営おもちゃ売場</p>
<p>応募受付期間 8月21日(金) 11:00 ～ 8月27日(木) 19:59</p>
<p>キッズリパブリックアプリからの応募になります。</p>
"""

FURUICHI_HTML = """
<h1>ふるいちトップブックス新入善店</h1>
<p>抽選 応募 ポケモンカードゲーム</p>
<h2>第1弾・LivePocket抽選販売</h2>
<p>ポケモンカードゲーム MEGA スターターセットex イーブイex</p>
<p>ポケモンカードゲーム MEGA スターターセットex ゾロア＆ゾロアークex</p>
<p>抽選受付日時 2026.08.21㊎ ～08.23㊐ 店頭にてLivePocket抽選QR公開・受付</p>
<h2>第2弾・LivePocket抽選販売</h2>
"""


def parse(html: str, url: str, parser: str, now: datetime = NOW):
    return PokemonOfficialCampaignMonitor.parse_official_document(
        html, url, parser=parser, observed_at=now,
    )


def test_pokemon_card_store_extracts_only_explicit_branches():
    rows, reason = parse(POKEMON_STORE_HTML, POKEMON_STORE_URL, "pokemon_card_store")
    assert reason == ""
    assert [row["hit"]["branch"] for row in rows] == [
        "ポケモンカードストア in イオンモール旭川駅前",
        "ポケモンカードストア in イオンモール川口前川",
    ]
    assert [row["hit"]["prefecture"] for row in rows] == ["北海道", "埼玉県"]


def test_branch_count_mismatch_is_quarantined_instead_of_guessed():
    broken = POKEMON_STORE_HTML.replace(
        '<a href="https://miniapp.line.me/a/events/two">応募</a>', ""
    )
    rows, reason = parse(broken, POKEMON_STORE_URL, "pokemon_card_store")
    assert rows == []
    assert reason == "NO_CURRENT_OR_RECENT_APPLICATION"


def test_line_miniapp_is_openable_only_with_confirmed_official_evidence():
    rows, _ = parse(POKEMON_STORE_HTML, POKEMON_STORE_URL, "pokemon_card_store")
    action = application_action(rows[0]["hit"])
    assert action["application_action_enabled"] is True
    assert action["application_action_label"] == "応募ページを開く"
    unconfirmed = {**rows[0]["hit"], "verification_status": "candidate"}
    assert application_action(unconfirmed)["application_action_enabled"] is False


def test_kids_republic_is_one_nationwide_row_not_fabricated_branches():
    rows, reason = parse(KIDS_HTML, KIDS_URL, "kids_republic")
    assert reason == ""
    assert len(rows) == 1
    assert rows[0]["hit"]["branch"] == "対象店舗（本州・四国）"
    assert rows[0]["hit"]["prefecture"] == "全国"
    assert rows[0]["hit"]["application_path_type"] == "APP_REQUIRED"


def test_app_required_action_opens_official_guidance_not_fake_form():
    rows, _ = parse(KIDS_HTML, KIDS_URL, "kids_republic")
    action = application_action(rows[0]["hit"])
    assert action["application_action_enabled"] is True
    assert action["application_action_url"] == KIDS_URL
    assert action["application_action_guidance"] == "応募は公式アプリが必要"


def test_furuichi_current_store_only_application_is_confirmed():
    rows, reason = parse(FURUICHI_HTML, FURUICHI_URL, "furuichi")
    assert reason == ""
    assert len(rows) == 1
    hit = rows[0]["hit"]
    assert hit["site_key"] == "furuichi"
    assert hit["branch"] == "ふるいちトップブックス新入善店"
    assert hit["prefecture"] == "富山県"
    assert hit["status"] == "抽選受付中"


def test_recently_ended_is_kept_for_fourteen_days():
    now = datetime(2026, 8, 30, 12, 0, tzinfo=JST)
    rows, _ = parse(FURUICHI_HTML, FURUICHI_URL, "furuichi", now)
    assert len(rows) == 1
    assert rows[0]["hit"]["status"] == "応募期間終了"


def test_stale_official_application_is_excluded():
    now = datetime(2026, 9, 8, 0, 0, tzinfo=JST)
    rows, reason = parse(FURUICHI_HTML, FURUICHI_URL, "furuichi", now)
    assert rows == []
    assert reason == "NO_CURRENT_OR_RECENT_APPLICATION"


def test_source_trust_does_not_accept_wrong_official_host():
    class Fetcher:
        def fetch(self, url, *, force=False):
            return {"ok": True, "status": "OK", "url": "https://evil.example/page", "html": KIDS_HTML}

        def diagnostics(self):
            return {}

    monitor = PokemonOfficialCampaignMonitor(Path("."), fetcher=Fetcher(), now=lambda: NOW)
    assert monitor.scan() == []
    assert {row["status"] for row in monitor.diagnostics["source_outcomes"]} == {
        "UNVERIFIED_REDIRECT"
    }


def test_monitor_deduplicates_same_chain_branch_deadline():
    rows, _ = parse(KIDS_HTML, KIDS_URL, "kids_republic")
    assert len(PokemonOfficialCampaignMonitor._deduplicate(rows + rows)) == 1


def test_unknown_prefecture_is_not_inferred_from_ambiguous_branch():
    html = POKEMON_STORE_HTML.replace("北海道旭川市宮下通7丁目2-5", "旭川駅前4F")
    rows, _ = parse(html, POKEMON_STORE_URL, "pokemon_card_store")
    assert rows == []

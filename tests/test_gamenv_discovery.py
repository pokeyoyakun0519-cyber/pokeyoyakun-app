from datetime import datetime

from core.application_status import JST
from core.gamenv_discovery import GamenvDiscovery


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=JST)


def test_editorial_and_user_reference_are_separate_and_never_confirmed():
    html = """
    <article><a href="/tc/pokemon-lottery/">ポケカ 30周年 抽選受付まとめ</a></article>
    <aside><a href="/tc/community/">ワンピース抽選 コメント・ユーザー投稿</a></aside>
    <a href="https://evil.example/">遊戯王 抽選</a>
    """
    parser = GamenvDiscovery(now=lambda: NOW)
    rows = parser.parse_editorial_index(html)

    assert len(rows) == 2
    assert {item["trust_tier"] for item in rows} == {"TIER_B_DISCOVERY", "TIER_C_REFERENCE"}
    assert all(item["verification_status"] == "candidate" for item in rows)
    assert all(item["confirmed"] is False for item in rows)


def test_live_polling_is_disabled_by_terms():
    parser = GamenvDiscovery(now=lambda: NOW)
    assert parser.poll() == []
    assert parser.diagnostics()["adoption_status"] == "TERMS_RESTRICTED"
    assert parser.diagnostics()["prevented_fetch_count"] == 1

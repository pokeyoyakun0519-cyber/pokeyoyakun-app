from datetime import datetime

from core.application_coverage_report import build_application_coverage
from core.application_status import JST
from core.application_dashboard import ApplicationDashboard
from core.product_store import ProductStore
import tempfile
from pathlib import Path


def _item(chain: str, branch: str, *, confirmed=True):
    return {"record": {"tcg_key": "pokemon", "product_name": "商品A", "source_id": chain,
                       "article_url": f"https://{chain}.example/news/1", "application_evidence": True},
            "hit": {"tcg_key": "pokemon", "site_key": chain, "branch": branch,
                    "application_url": f"https://{chain}.example/apply/{branch}",
                    "application_end_at": "2026-08-30T23:59:59+09:00",
                    "verification_status": "confirmed" if confirmed else "candidate"}}


def test_article_event_chain_branch_and_dominance_are_separate():
    items = [_item("card_labo", f"店{i}") for i in range(8)] + [_item("other", "本店")]
    report = build_application_coverage(items, now=datetime(2026, 8, 23, tzinfo=JST))
    value = report["by_tcg"]["pokemon"]
    assert value["official_article_count"] == 2
    assert value["application_event_count"] == 9
    assert value["active_chain_count"] == 2
    assert value["active_branch_count"] == 9
    assert value["dominant_chain_ratio"] == 0.889
    assert value["chain_diversity_warning"] is True


def test_pending_gaps_and_false_negative_are_counted():
    confirmed = _item("one", "本店")
    pending = _item("two", "支店", confirmed=False)
    report = build_application_coverage(
        [confirmed, pending], known_current=[confirmed, pending],
        source_gaps=[{"reason": "APP_REQUIRED", "supported_tcg": ["pokemon"]}],
        now=datetime(2026, 8, 23, tzinfo=JST),
    )
    value = report["by_tcg"]["pokemon"]
    assert value["pending_count"] == 1
    assert value["app_required_count"] == 1
    assert report["totals"]["false_negative_count"] == 1
    assert report["totals"]["recall_estimate"] == 0.5


def test_deadline_unknown_candidate_is_not_counted_as_current():
    item = _item("discovery", "候補", confirmed=False)
    item["hit"].pop("application_end_at")
    report = build_application_coverage([item], now=datetime(2026, 8, 23, tzinfo=JST))
    assert report["by_tcg"]["pokemon"]["current_candidate_count"] == 0


def test_dashboard_reports_dominant_chain_warning():
    with tempfile.TemporaryDirectory() as folder:
        store = ProductStore(Path(folder))
        product = {"id": "p", "name": "商品A", "tcg_key": "pokemon", "sites": []}
        for index in range(5):
            product["sites"].append({
                "site_key": "card_labo", "name": f"カードラボ {index}",
                "application_url": f"https://official.example/{index}",
                "application_end_at": "2026-08-30T23:59:59+09:00",
                "verification_status": "confirmed", "application_evidence": True,
            })
        store._save_product_file([product])
        dashboard = ApplicationDashboard()
        dashboard.store = store
        result = dashboard.build(show_ended=False, now=datetime(2026, 8, 23, tzinfo=JST))
        assert result["coverage_by_tcg"]["pokemon"]["active_chain_count"] == 1
        assert result["coverage_by_tcg"]["pokemon"]["dominant_chain_ratio"] == 1.0
        assert result["coverage_by_tcg"]["pokemon"]["chain_diversity_warning"] is True

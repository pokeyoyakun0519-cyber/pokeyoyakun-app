import json
from pathlib import Path
from typing import Any


DEFAULT_SITES = [
    {
        "id": "pokemon_center",
        "name": "ポケモンセンターオンライン",
        "enabled": True,
        "sales_type": "抽選・通常販売",
        "purchase_history_required": False,
        "membership_required": True,
        "notes": "販売方式は商品ごとに異なります。",
    },
    {
        "id": "amazon",
        "name": "Amazon",
        "enabled": True,
        "sales_type": "通常販売・招待販売",
        "purchase_history_required": False,
        "membership_required": True,
        "notes": "招待販売の場合があります。",
    },
    {
        "id": "rakuten",
        "name": "楽天",
        "enabled": True,
        "sales_type": "通常販売",
        "purchase_history_required": False,
        "membership_required": True,
        "notes": "",
    },
    {
        "id": "yodobashi",
        "name": "ヨドバシ",
        "enabled": True,
        "sales_type": "抽選・通常販売",
        "purchase_history_required": True,
        "membership_required": True,
        "notes": "購入履歴や会員条件が設定される場合があります。",
    },
    {
        "id": "biccamera",
        "name": "ビックカメラ",
        "enabled": True,
        "sales_type": "抽選・通常販売",
        "purchase_history_required": True,
        "membership_required": True,
        "notes": "抽選条件は時期によって異なります。",
    },
    {
        "id": "amiami",
        "name": "あみあみ",
        "enabled": False,
        "sales_type": "通常販売",
        "purchase_history_required": False,
        "membership_required": False,
        "notes": "",
    },
]


class SiteMasterManager:
    """販売サイトの共通情報を管理する。"""

    def __init__(self):
        project_root = Path(__file__).resolve().parents[2]
        self.path = project_root / "config" / "site_master.json"

    def load_sites(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            self.save_sites(DEFAULT_SITES)
            return json.loads(json.dumps(DEFAULT_SITES))

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULT_SITES))

    def save_sites(self, sites: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(sites, file, ensure_ascii=False, indent=2)

    def add_site(self, site: dict[str, Any]) -> None:
        sites = self.load_sites()
        sites.append(site)
        self.save_sites(sites)

    def update_site(self, site_id: str, updated: dict[str, Any]) -> None:
        sites = self.load_sites()

        for index, site in enumerate(sites):
            if site.get("id") == site_id:
                sites[index] = updated
                break

        self.save_sites(sites)

    def delete_site(self, site_id: str) -> None:
        sites = [
            site
            for site in self.load_sites()
            if site.get("id") != site_id
        ]
        self.save_sites(sites)

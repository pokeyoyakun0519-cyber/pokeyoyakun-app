from __future__ import annotations

from datetime import datetime
from typing import Any

from core.config_manager import ConfigManager
from core.notification_store import NotificationStore
from core.site_master_manager import (
    LEGACY_SITE_ID_ALIASES,
    SiteMasterManager,
    canonical_site_id,
)


class SiteMonitorSync:
    """店舗マスタを監視設定へIDベースで補完し、既存選択を維持する。"""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        site_manager: SiteMasterManager | None = None,
        notification_store: NotificationStore | None = None,
    ):
        self.config_manager = config_manager or ConfigManager()
        self.site_manager = site_manager or SiteMasterManager()
        self.notification_store = notification_store

    def sync(self, *, notify: bool = True) -> dict[str, Any]:
        had_config = self.config_manager.config_path.exists()
        config = self.config_manager.load()
        settings = dict(config.get("sites", {}))

        for old_id, new_id in LEGACY_SITE_ID_ALIASES.items():
            if old_id in settings:
                settings[new_id] = bool(settings[old_id])
                settings.pop(old_id, None)

        master = self.site_manager.load_sites()
        sync_state = dict(config.get("site_sync", {}))
        known = {canonical_site_id(value) for value in sync_state.get("known_site_ids", [])}
        if not known and had_config:
            known = {canonical_site_id(value) for value in settings}

        new_sites = []
        for site in master:
            site_id = canonical_site_id(site.get("id"))
            if not site_id:
                continue
            if site_id not in settings:
                # 誤通知防止のため、新規店舗は必ずユーザー確認までOFF。
                settings[site_id] = False
            if had_config and site_id not in known:
                new_sites.append(site)

        all_ids = [canonical_site_id(site.get("id")) for site in master if site.get("id")]
        new_ids = [str(site.get("id")) for site in new_sites]
        config["sites"] = settings
        config["site_sync"] = {
            "known_site_ids": sorted(set(all_ids)),
            "new_site_ids": new_ids,
            "last_synced_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.config_manager.save(config)

        notify_enabled = bool(config.get("general", {}).get("notify_new_monitoring_sites", True))
        if new_sites and notify and notify_enabled:
            store = self.notification_store or NotificationStore()
            names = "、".join(str(site.get("name", "新規店舗")) for site in new_sites[:8])
            store.add(
                "新しい監視サイトが追加されました",
                f"{names} を監視設定へ追加しました。誤通知防止のため初期状態はOFFです。",
                "店舗",
            )

        return {
            "sites": master,
            "settings": settings,
            "new_site_ids": new_ids,
        }

    def set_all(self, enabled: bool, *, tcg_key: str = "all") -> None:
        config = self.config_manager.load()
        settings = dict(config.get("sites", {}))
        for site in self.site_manager.load_sites():
            if not site.get("active", site.get("enabled", True)):
                continue
            if not site.get("monitoring_supported", False):
                continue
            if tcg_key != "all" and tcg_key not in site.get("tcg_keys", []):
                continue
            settings[str(site.get("id"))] = bool(enabled)
        config["sites"] = settings
        self.config_manager.save(config)

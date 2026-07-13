from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


ALLOWED_MODES = {
    "dedicated",
    "public_html",
    "search_page",
    "manual_app",
}

ALLOWED_RESULT_MODES = {
    "account_page",
    "manual_app",
    "manual_store",
    "manual",
}


class RetailPluginLoader:
    """店舗検索用JSONプラグインを読み込み、検証する。"""

    def __init__(
        self,
        plugin_dir: Path | None = None,
    ):
        self.plugin_dir = (
            plugin_dir
            if plugin_dir is not None
            else app_root() / "plugins" / "retail"
        )

    def load_external_plugins(
        self,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        self.plugin_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        plugins: list[dict[str, Any]] = []
        messages: list[str] = []

        for path in sorted(
            self.plugin_dir.glob("*.json")
        ):
            try:
                raw = json.loads(
                    path.read_text(
                        encoding="utf-8",
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ) as error:
                messages.append(
                    f"{path.name}: JSON読込エラー ({error})"
                )
                continue

            entries = (
                raw
                if isinstance(raw, list)
                else [raw]
            )

            for index, entry in enumerate(entries):
                label = (
                    f"{path.name}[{index}]"
                    if len(entries) > 1
                    else path.name
                )

                if not isinstance(entry, dict):
                    messages.append(
                        f"{label}: オブジェクト形式ではありません"
                    )
                    continue

                normalized, error = self.validate_plugin(
                    entry
                )
                if error:
                    messages.append(
                        f"{label}: {error}"
                    )
                    continue

                normalized["source"] = "external_json"
                normalized["source_file"] = path.name
                plugins.append(normalized)
                messages.append(
                    f"{label}: 読込成功"
                )

        return plugins, messages

    @classmethod
    def validate_plugin(
        cls,
        plugin: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        plugin_id = str(
            plugin.get("id", "")
        ).strip()
        name = str(
            plugin.get("name", "")
        ).strip()
        mode = str(
            plugin.get("mode", "")
        ).strip()

        if not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{1,63}",
            plugin_id,
        ):
            return {}, (
                "idは英小文字・数字・_・-で"
                "2～64文字にしてください"
            )

        if not name:
            return {}, "nameが空です"

        if mode not in ALLOWED_MODES:
            return {}, (
                "modeが不正です: "
                + mode
            )

        if mode == "search_page":
            search_url = str(
                plugin.get("search_url", "")
            ).strip()
            if "{query}" not in search_url:
                return {}, (
                    "search_pageには{query}を含む"
                    "search_urlが必要です"
                )

        if mode == "public_html":
            index_url = str(
                plugin.get("index_url", "")
            ).strip()
            if not index_url.startswith(
                ("http://", "https://")
            ):
                return {}, (
                    "public_htmlにはindex_urlが必要です"
                )

        result_mode = str(
            plugin.get(
                "result_mode",
                "manual",
            )
        ).strip()
        if result_mode not in ALLOWED_RESULT_MODES:
            return {}, (
                "result_modeが不正です: "
                + result_mode
            )

        tcg = plugin.get("tcg", [])
        if not isinstance(tcg, list) or not tcg:
            return {}, "tcgは1件以上の配列にしてください"

        regions = plugin.get(
            "regions",
            ["全国"],
        )
        if not isinstance(regions, list) or not regions:
            regions = ["全国"]

        normalized = {
            "id": plugin_id,
            "name": name[:80],
            "mode": mode,
            "regions": [
                str(item)[:40]
                for item in regions
                if str(item).strip()
            ] or ["全国"],
            "tcg": [
                str(item).strip()
                for item in tcg
                if str(item).strip()
            ],
            "application_method": str(
                plugin.get(
                    "application_method",
                    "Web / 店頭",
                )
            )[:120],
            "result_mode": result_mode,
            "enabled": bool(
                plugin.get("enabled", True)
            ),
            "plugin_version": str(
                plugin.get(
                    "plugin_version",
                    "1.0.0",
                )
            )[:30],
            "publisher": str(
                plugin.get(
                    "publisher",
                    "ユーザープラグイン",
                )
            )[:80],
        }

        for key in (
            "search_url",
            "index_url",
        ):
            value = str(
                plugin.get(key, "")
            ).strip()
            if value:
                normalized[key] = value

        return normalized, ""


    def delete_external_plugin(
        self,
        source_file: str,
    ) -> bool:
        filename = Path(source_file).name

        if filename != source_file:
            return False

        path = self.plugin_dir / filename

        try:
            resolved_dir = self.plugin_dir.resolve()
            resolved_path = path.resolve()
        except OSError:
            return False

        if resolved_path.parent != resolved_dir:
            return False

        if not resolved_path.exists():
            return False

        try:
            resolved_path.unlink()
        except OSError:
            return False

        return True

    def write_example_plugin(self) -> Path:
        self.plugin_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        path = (
            self.plugin_dir
            / "_example_retail_plugin.json"
        )
        if not path.exists():
            path.write_text(
                json.dumps(
                    {
                        "id": "example_store",
                        "name": "サンプル店舗",
                        "plugin_version": "1.0.0",
                        "publisher": "PokeyoyaKun Project",
                        "mode": "search_page",
                        "search_url": (
                            "https://example.com/search"
                            "?q={query}"
                        ),
                        "regions": ["全国"],
                        "tcg": ["pokemon"],
                        "application_method": "Web",
                        "result_mode": "account_page",
                        "enabled": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return path

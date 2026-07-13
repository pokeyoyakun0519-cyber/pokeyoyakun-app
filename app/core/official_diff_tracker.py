import json
import re
from datetime import datetime
from typing import Any

from core.runtime_paths import app_root


class OfficialDiffTracker:
    """公式情報の名称・発売日・URLの変更履歴を管理する。"""

    def __init__(self):
        self.path = app_root() / "data" / "official_history.json"

    def compare_and_update(
        self,
        products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        state = self._load()
        changes: list[dict[str, Any]] = []

        for product in products:
            name = str(product.get("name", "")).strip()
            release_date = str(
                product.get("release_date", "")
            ).strip()
            official_url = self._official_url(product)

            if not name:
                continue

            key = self._key(name)
            current = {
                "name": name,
                "release_date": release_date,
                "official_url": official_url,
                "updated_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            }

            previous = state.get(key)
            if previous:
                changed_fields = {}

                for field, label in (
                    ("name", "商品名"),
                    ("release_date", "発売日"),
                    ("official_url", "公式URL"),
                ):
                    before = str(previous.get(field, ""))
                    after = str(current.get(field, ""))

                    if before and after and before != after:
                        changed_fields[field] = {
                            "label": label,
                            "before": before,
                            "after": after,
                        }

                if changed_fields:
                    changes.append(
                        {
                            "product_key": key,
                            "product_name": name,
                            "changes": changed_fields,
                            "detected_at": datetime.now().isoformat(
                                timespec="seconds"
                            ),
                        }
                    )

            state[key] = current

        self._save(state)
        return changes

    @staticmethod
    def _official_url(
        product: dict[str, Any],
    ) -> str:
        for site in product.get("sites", []):
            if not isinstance(site, dict):
                continue
            url = str(site.get("url", "")).strip()
            if url:
                return url
        return str(product.get("official_url", "")).strip()

    @staticmethod
    def _key(name: str) -> str:
        normalized = re.sub(
            r"[\s「」『』・･_\-&＆（）()【】\[\]]",
            "",
            name,
        ).lower()
        return normalized

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(
        self,
        data: dict[str, Any],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

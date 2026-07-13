import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.runtime_paths import app_root


class CandidateManager:
    """公式発表、新弾候補、販売サイト検索状態を管理する。"""

    def __init__(self):
        root = app_root()
        self.candidates_path = root / "data" / "candidates.json"
        self.products_path = root / "data" / "products.json"

    def load_candidates(self) -> list[dict[str, Any]]:
        return self._load_list(self.candidates_path)

    def save_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> None:
        self._save_list(self.candidates_path, candidates)

    def merge_official_candidates(
        self,
        discovered: list[dict[str, Any]],
        *,
        source_id: str,
        source_name: str,
        source_url: str,
    ) -> tuple[list[dict[str, Any]], int]:
        candidates = self.load_candidates()
        existing_keys = {
            (
                self._normalize_name(
                    str(item.get("name", ""))
                ),
                str(item.get("release_date", "")),
            )
            for item in candidates
        }

        added = 0

        for product in discovered:
            name = str(product.get("name", "")).strip()
            release_date = str(
                product.get("release_date", "")
            ).strip()
            confidence = float(
                product.get(
                    "candidate_confidence",
                    1.0,
                )
            )
            reasons = list(
                product.get(
                    "candidate_reasons",
                    [],
                )
            )

            if not name:
                continue
            if confidence < 0.72:
                continue

            official_url = source_url
            sites = product.get("sites", [])
            if sites:
                official_url = str(
                    sites[0].get("url", source_url)
                )

            key = (
                self._normalize_name(name),
                release_date,
            )
            if key in existing_keys:
                self._refresh_existing_candidate(
                    candidates,
                    key,
                    official_url=official_url,
                    source_name=source_name,
                    source_id=source_id,
                )
                continue

            digest = hashlib.sha256(
                (
                    f"{source_id}|{name}|"
                    f"{release_date}|{official_url}"
                ).encode("utf-8")
            ).hexdigest()[:20]

            candidates.append(
                {
                    "id": f"official_{digest}",
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_url": source_url,
                    "official_url": official_url,
                    "name": name,
                    "tcg_key": str(
                        product.get("tcg_key", "pokemon")
                    ),
                    "tcg": str(
                        product.get("tcg", "ポケモンカード")
                    ),
                    "release_date": release_date,
                    "status": "販売・抽選情報を検索待ち",
                    "candidate_confidence": confidence,
                    "candidate_reasons": reasons,
                    "approved": False,
                    "last_searched": "",
                    "retail_hits": [],
                    "search_message": "",
                    "created_at": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                }
            )
            existing_keys.add(key)
            added += 1

        if added:
            candidates.sort(
                key=lambda item: (
                    str(
                        item.get(
                            "release_date",
                            "9999-99-99",
                        )
                    ),
                    str(item.get("name", "")),
                )
            )

        self.save_candidates(candidates)
        return candidates, added

    def build_candidates_from_sources(
        self,
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """旧データとの互換用。検出済み商品から候補を作る。"""
        before = len(self.load_candidates())

        for source in sources:
            discovered = []

            for item in source.get(
                "detected_products",
                [],
            ):
                discovered.append(
                    {
                        "name": item.get("name", ""),
                        "release_date": item.get(
                            "release_date",
                            "",
                        ),
                        "tcg_key": "pokemon",
                        "tcg": "ポケモンカード",
                        "sites": [
                            {
                                "url": item.get(
                                    "url",
                                    source.get("url", ""),
                                )
                            }
                        ],
                    }
                )

            if discovered:
                self.merge_official_candidates(
                    discovered,
                    source_id=str(source.get("id", "")),
                    source_name=str(
                        source.get(
                            "name",
                            "公式情報ソース",
                        )
                    ),
                    source_url=str(source.get("url", "")),
                )

        candidates = self.load_candidates()
        return candidates[before:]

    def add_manual_candidate(
        self,
        name: str,
        source_name: str = "手動追加",
        source_url: str = "",
    ) -> None:
        clean_name = name.strip()
        if not clean_name:
            return

        candidates = self.load_candidates()

        normalized = self._normalize_name(clean_name)
        if any(
            self._normalize_name(
                str(item.get("name", ""))
            )
            == normalized
            for item in candidates
        ):
            return

        digest = hashlib.sha256(
            clean_name.encode("utf-8")
        ).hexdigest()[:16]

        candidates.append(
            {
                "id": f"manual_{digest}",
                "source_id": "manual",
                "source_name": source_name,
                "source_url": source_url,
                "official_url": source_url,
                "name": clean_name,
                "tcg_key": "pokemon",
                "tcg": "ポケモンカード",
                "release_date": "",
                "status": "販売・抽選情報を検索待ち",
                "approved": False,
                "last_searched": "",
                "retail_hits": [],
                "search_message": "",
                "created_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            }
        )
        self.save_candidates(candidates)

    def add_test_candidate(self) -> None:
        self.add_manual_candidate(
            "拡張パック「動作確認用サンプル」",
            "ポケヨヤ君 テストデータ",
            "https://example.com/",
        )

    def update_search_result(
        self,
        candidate_id: str,
        *,
        hits: list[dict[str, Any]],
        messages: list[str],
    ) -> dict[str, Any] | None:
        candidates = self.load_candidates()
        updated = None

        for candidate in candidates:
            if candidate.get("id") != candidate_id:
                continue

            candidate["retail_hits"] = hits
            candidate["last_searched"] = (
                datetime.now().isoformat(
                    timespec="seconds"
                )
            )
            candidate["search_message"] = "\n".join(
                messages
            )

            if hits:
                candidate["status"] = (
                    f"販売・抽選情報 {len(hits)}件"
                )
                candidate["approved"] = True
                self._upsert_product_from_candidate(
                    candidate
                )
            else:
                candidate["status"] = (
                    "販売・抽選情報は未検出"
                )
                candidate["approved"] = False

            updated = candidate
            break

        self.save_candidates(candidates)
        return updated

    def approve_candidate(
        self,
        candidate_id: str,
        tcg_key: str,
        tcg_label: str,
        release_date: str,
    ) -> None:
        """旧画面との互換。販売情報なしでは商品一覧へ入れない。"""
        candidates = self.load_candidates()

        for candidate in candidates:
            if candidate.get("id") != candidate_id:
                continue

            candidate["tcg_key"] = tcg_key
            candidate["tcg"] = tcg_label

            if release_date:
                candidate["release_date"] = release_date

            if candidate.get("retail_hits"):
                candidate["approved"] = True
                self._upsert_product_from_candidate(
                    candidate
                )
            break

        self.save_candidates(candidates)

    def delete_candidate(
        self,
        candidate_id: str,
    ) -> None:
        candidates = [
            item
            for item in self.load_candidates()
            if item.get("id") != candidate_id
        ]
        self.save_candidates(candidates)

    def _upsert_product_from_candidate(
        self,
        candidate: dict[str, Any],
    ) -> None:
        hits = []
        for raw_hit in candidate.get("retail_hits", []):
            if not isinstance(raw_hit, dict):
                continue
            hit = dict(raw_hit)
            hit.setdefault("application_method", "Web / 店頭")
            hit.setdefault("result_mode", "manual")
            hit.setdefault("application_period", "")
            hit.setdefault("result_date", "")
            hit.setdefault("order_period", "")
            hits.append(hit)
        if not hits:
            return

        products = self._load_list(
            self.products_path
        )
        product_id = (
            f"retail_{candidate.get('id', '')}"
        )

        product = {
            "id": product_id,
            "tcg_key": candidate.get(
                "tcg_key",
                "pokemon",
            ),
            "tcg": candidate.get(
                "tcg",
                "ポケモンカード",
            ),
            "name": candidate.get(
                "name",
                "名称未設定",
            ),
            "release_date": (
                candidate.get("release_date")
                or str(date.today())
            ),
            "status": self._combined_status(hits),
            "favorite": False,
            "reserved": False,
            "source_type": "retail_search",
            "official_url": candidate.get(
                "official_url",
                "",
            ),
            "sites": hits,
        }

        replaced = False
        for index, current in enumerate(products):
            if current.get("id") == product_id:
                product["reserved"] = bool(
                    current.get("reserved", False)
                )
                product["favorite"] = bool(
                    current.get("favorite", False)
                )
                products[index] = product
                replaced = True
                break

        if not replaced:
            products.append(product)

        self._save_list(
            self.products_path,
            products,
        )

    @staticmethod
    def _combined_status(
        hits: list[dict[str, Any]],
    ) -> str:
        statuses = [
            str(hit.get("status", ""))
            for hit in hits
        ]

        if any(
            "受付中" in status
            for status in statuses
        ):
            return "抽選・予約受付中"
        if any(
            "抽選" in status
            for status in statuses
        ):
            return "抽選情報あり"
        if any(
            "予約" in status
            for status in statuses
        ):
            return "予約情報あり"
        return "販売情報あり"

    @classmethod
    def _refresh_existing_candidate(
        cls,
        candidates: list[dict[str, Any]],
        key: tuple[str, str],
        *,
        official_url: str,
        source_name: str,
        source_id: str,
    ) -> None:
        for item in candidates:
            item_key = (
                cls._normalize_name(
                    str(item.get("name", ""))
                ),
                str(item.get("release_date", "")),
            )
            if item_key != key:
                continue

            item["official_url"] = (
                official_url
                or item.get("official_url", "")
            )
            item["source_name"] = (
                source_name
                or item.get("source_name", "")
            )
            item["source_id"] = (
                source_id
                or item.get("source_id", "")
            )
            break

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(
            r"[\s「」『』・･_\-&＆]",
            "",
            name,
        ).lower()

    @staticmethod
    def _load_list(
        path: Path,
    ) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return []

    @staticmethod
    def _save_list(
        path: Path,
        data: list[dict[str, Any]],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

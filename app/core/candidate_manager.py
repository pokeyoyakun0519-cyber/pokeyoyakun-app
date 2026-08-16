import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from core.application_period import ApplicationPeriodParser
from core.application_site import normalize_application_site
from core.json_file_state import (
    CANDIDATE_LIST_FIELDS,
    PRODUCT_LIST_FIELDS,
    JsonFileResult,
    ensure_json_writable,
    inspect_json_file,
    restore_json_backup,
)
from core.product_master import ProductMasterManager
from core.runtime_paths import app_root
from core.tcg_categories import display_name, normalize_key, normalize_record
from core.information_classifier import PRODUCT, classify_information


class CandidateManager:
    """公式発表、新弾候補、販売サイト検索状態を管理する。"""

    def __init__(self, root: Path | None = None):
        root = root or app_root()
        self.root = root
        self.candidates_path = root / "data" / "candidates.json"
        self.products_path = root / "data" / "products.json"
        self.last_merge_diagnostics: dict[str, Any] = {}
        self.last_candidate_file_result: JsonFileResult | None = None

    def load_candidates(self) -> list[dict[str, Any]]:
        result = self.inspect_candidates_file()
        self.last_candidate_file_result = result
        return [normalize_record(item)[0] for item in (result.data or [])]

    def inspect_candidates_file(self) -> JsonFileResult:
        return inspect_json_file(
            self.candidates_path,
            list,
            nullable_list_fields=CANDIDATE_LIST_FIELDS,
        )

    def restore_candidates_backup(self) -> bool:
        return restore_json_backup(
            self.candidates_path,
            list,
            nullable_list_fields=CANDIDATE_LIST_FIELDS,
        )

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
        products = self._load_list(self.products_path)
        identity = ProductMasterManager(self.root)
        products_changed = False
        candidate_indexes_by_id = {
            str(item.get("id", "")): index
            for index, item in enumerate(candidates)
            if str(item.get("id", ""))
        }

        added = 0
        diagnostic_reasons = Counter()
        detected_by_tcg = Counter()

        for product in discovered:
            tcg_key = normalize_key(product.get("tcg_key"), product.get("tcg"))[0]
            detected_by_tcg[tcg_key] += 1
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
                diagnostic_reasons["missing_name"] += 1
                continue
            if confidence < 0.72:
                diagnostic_reasons["low_confidence"] += 1
                continue
            if not self._is_new_release_candidate(product, tcg_key):
                diagnostic_reasons["not_new_release_product"] += 1
                continue
            if classify_information(product) != PRODUCT:
                diagnostic_reasons["not_product_information"] += 1
                continue

            official_url = str(product.get("official_url", "")) or source_url
            sites = product.get("sites", [])
            if sites:
                official_url = str(
                    sites[0].get("url", source_url)
                )

            observed = dict(product)
            observed["tcg_key"] = tcg_key
            observed["official_url"] = official_url
            observed["source_url"] = source_url
            observed["source_name"] = source_name
            observed.setdefault("source_type", "official_source")

            digest = hashlib.sha256(
                (
                    f"{source_id}|{name}|"
                    f"{release_date}|{official_url}|"
                    f"{product.get('official_product_id') or product.get('official_id') or ''}|"
                    f"{product.get('product_code') or ''}|"
                    f"{product.get('jan_code') or product.get('jan') or ''}"
                ).encode("utf-8")
            ).hexdigest()[:20]
            candidate_id = f"official_{digest}"
            legacy_digest = hashlib.sha256(
                (
                    f"{source_id}|{name}|"
                    f"{release_date}|{official_url}"
                ).encode("utf-8")
            ).hexdigest()[:20]
            legacy_candidate_id = f"official_{legacy_digest}"

            product_index, product_match = identity.find_match(
                products, observed
            )
            if product_index is not None:
                merged, changes = identity.reconcile_product(
                    products[product_index], observed
                )
                products[product_index] = merged
                if changes:
                    products_changed = True
                    diagnostic_reasons["existing_product_updated"] += 1
                else:
                    diagnostic_reasons["already_product"] += 1
                continue
            if product_match.startswith("ambiguous_"):
                diagnostic_reasons["ambiguous_product"] += 1

            exact_candidate_index = candidate_indexes_by_id.get(candidate_id)
            if exact_candidate_index is not None:
                candidate_index, candidate_match = (
                    exact_candidate_index, "candidate_id"
                )
            else:
                legacy_index = candidate_indexes_by_id.get(
                    legacy_candidate_id
                )
                if (
                    legacy_index is not None
                    and not identity.has_identifier_conflict(
                        candidates[legacy_index], observed
                    )
                ):
                    candidate_index, candidate_match = (
                        legacy_index, "legacy_candidate_id"
                    )
                else:
                    candidate_index, candidate_match = identity.find_match(
                        candidates, observed
                    )
            if candidate_index is not None:
                merged, changes = identity.reconcile_product(
                    candidates[candidate_index], observed
                )
                merged["official_url"] = official_url or merged.get(
                    "official_url", ""
                )
                merged["source_name"] = source_name or merged.get(
                    "source_name", ""
                )
                merged["source_id"] = source_id or merged.get("source_id", "")
                candidates[candidate_index] = merged
                diagnostic_reasons[
                    "existing_candidate_updated" if changes else "already_candidate"
                ] += 1
                continue
            if candidate_match.startswith("ambiguous_"):
                diagnostic_reasons["ambiguous_candidate"] += 1

            candidates.append(
                {
                    "id": candidate_id,
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_url": source_url,
                    "official_url": official_url,
                    "name": name,
                    "tcg_key": tcg_key,
                    "tcg": display_name(
                        normalize_key(product.get("tcg_key"), product.get("tcg"))[0],
                        product.get("tcg"),
                    ),
                    "release_date": release_date,
                    "product_kind": str(product.get("product_kind", "その他")),
                    "product_code": str(product.get("product_code", "")),
                    "official_product_id": str(
                        product.get("official_product_id")
                        or product.get("official_id")
                        or ""
                    ),
                    "jan_code": str(
                        product.get("jan_code") or product.get("jan") or ""
                    ),
                    "msrp": product.get("msrp"),
                    "msrp_includes_tax": bool(product.get("msrp_includes_tax", True)),
                    "reference_price": product.get("reference_price"),
                    "application_start_at": str(product.get("application_start_at", "")),
                    "application_end_at": str(product.get("application_end_at", "")),
                    "application_url": str(product.get("application_url", "")),
                    "application_method": str(product.get("application_method", "")),
                    "application_status": str(product.get("application_status", "")),
                    "status": "販売・抽選情報を検索待ち",
                    "candidate_confidence": confidence,
                    "candidate_reasons": reasons,
                    "approved": False,
                    "last_searched": "",
                    "retail_hits": [],
                    "search_message": "",
                    "search_diagnostics": {},
                    "created_at": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                }
            )
            candidate_indexes_by_id[candidate_id] = len(candidates) - 1
            added += 1
            diagnostic_reasons["added"] += 1

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
        if products_changed:
            from core.product_store import ProductStore

            ProductStore(self.root)._save_product_file(products)
        identity.log_conflicts()
        self.last_merge_diagnostics = {
            "detected": len(discovered),
            "added": added,
            "detected_by_tcg": dict(detected_by_tcg),
            "reasons": dict(diagnostic_reasons),
        }
        try:
            from core.auto_monitor_manager import AutoMonitorManager
            from core.config_manager import ConfigManager
            from core.product_store import ProductStore

            promotion = AutoMonitorManager(
                ConfigManager(self.root), ProductStore(self.root)
            ).add_due_candidates(candidates)
            self.last_merge_diagnostics["promotion"] = {
                key: value
                for key, value in promotion.items()
                if key != "products"
            }
        except (OSError, ValueError, TypeError):
            # 公式候補の保存は成功扱いとし、自動追加だけ次回起動へ回す。
            pass
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
                        "product_kind": item.get("product_kind", "その他"),
                        "product_code": item.get("product_code", ""),
                        "msrp": item.get("msrp"),
                        "msrp_includes_tax": item.get("msrp_includes_tax", True),
                        "reference_price": item.get("reference_price"),
                        "application_start_at": item.get("application_start_at", ""),
                        "application_end_at": item.get("application_end_at", ""),
                        "application_url": item.get("application_url", ""),
                        "application_method": item.get("application_method", ""),
                        "application_status": item.get("application_status", ""),
                        "tcg_key": normalize_key(
                            source.get("tcg_key"), source.get("tcg")
                        )[0],
                        "tcg": display_name(
                            normalize_key(source.get("tcg_key"), source.get("tcg"))[0],
                            source.get("tcg"),
                        ),
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
        tcg_key: str = "other",
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
                "tcg_key": normalize_key(tcg_key)[0],
                "tcg": display_name(normalize_key(tcg_key)[0]),
                "release_date": "",
                "product_kind": "その他",
                "product_code": "",
                "status": "販売・抽選情報を検索待ち",
                "approved": False,
                "last_searched": "",
                "retail_hits": [],
                "search_message": "",
                "search_diagnostics": {},
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
        candidates: list[dict[str, Any]] | None = None,
        save: bool = True,
    ) -> dict[str, Any] | None:
        candidates = candidates if candidates is not None else self.load_candidates()
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
            candidate["search_diagnostics"] = self._build_search_diagnostics(
                hits, messages
            )

            confirmed_hits = [
                hit for hit in hits
                if str(hit.get("verification_status", "confirmed")) != "candidate"
            ]
            if confirmed_hits:
                candidate["status"] = (
                    f"販売・抽選情報 {len(confirmed_hits)}件"
                )
                candidate["approved"] = True
                approved_candidate = dict(candidate)
                approved_candidate["retail_hits"] = confirmed_hits
                self._upsert_product_from_candidate(
                    approved_candidate
                )
            elif hits:
                candidate["status"] = f"販売・抽選候補 {len(hits)}件（確認待ち）"
                candidate["approved"] = False
            else:
                candidate["status"] = (
                    "販売・抽選情報は未検出"
                )
                candidate["approved"] = False

            updated = candidate
            break

        if save:
            self.save_candidates(candidates)
        return updated

    def merge_application_discoveries(
        self,
        discoveries: list[dict[str, Any]],
        *,
        matcher: Callable[[dict[str, Any], dict[str, Any]], bool],
    ) -> dict[str, int]:
        """Merge strong dedicated-adapter discoveries without per-item writes."""
        candidates = self.load_candidates()
        created = 0
        updated = 0
        ambiguous = 0
        promoted: dict[str, dict[str, Any]] = {}
        for discovery in discoveries:
            record = discovery.get("record")
            hit = discovery.get("hit")
            if not isinstance(record, dict) or not isinstance(hit, dict):
                continue
            matches = [item for item in candidates if matcher(item, record)]
            if len(matches) > 1:
                ambiguous += 1
                continue
            if matches:
                candidate = matches[0]
            else:
                name = str(record.get("product_name", "")).strip()
                tcg_key = normalize_key(record.get("tcg_key"), record.get("tcg"))[0]
                if not name or tcg_key not in {"pokemon", "onepiece"}:
                    continue
                signature = re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠]", "", name.casefold())
                digest = hashlib.sha256(
                    f"card_labo|{tcg_key}|{signature}".encode("utf-8")
                ).hexdigest()[:16]
                candidate = {
                    "id": f"application_{digest}",
                    "source_id": "card_labo_application",
                    "source_name": "カードラボ公式応募記事",
                    "source_url": str(record.get("article_url", "")),
                    "official_url": str(record.get("article_url", "")),
                    "name": name,
                    "tcg_key": tcg_key,
                    "tcg": display_name(tcg_key, record.get("tcg")),
                    "release_date": str(record.get("release_date", "")),
                    "product_kind": "その他",
                    "product_code": str(record.get("product_code", "")),
                    "status": "販売・抽選情報を検出",
                    "approved": False,
                    "last_searched": "",
                    "retail_hits": [],
                    "search_message": "専用Adapterが公式応募記事を検出",
                    "search_diagnostics": {},
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
                candidates.append(candidate)
                created += 1
            key = (str(hit.get("site_key", "")), str(hit.get("url", "")))
            existing_hits = [
                dict(value) for value in candidate.get("retail_hits", [])
                if isinstance(value, dict)
            ]
            if key not in {
                (str(value.get("site_key", "")), str(value.get("url", "")))
                for value in existing_hits
            }:
                existing_hits.append(dict(hit))
                candidate["retail_hits"] = existing_hits
                updated += 1
            if str(hit.get("verification_status", "")) == "confirmed":
                candidate["approved"] = True
                candidate["status"] = f"販売・抽選情報 {len(existing_hits)}件"
                approved = dict(candidate)
                approved["retail_hits"] = [
                    value for value in existing_hits
                    if str(value.get("verification_status", "confirmed")) != "candidate"
                ]
                promoted[str(candidate.get("id", ""))] = approved
        if created or updated:
            self.save_candidates(candidates)
            for candidate in promoted.values():
                self._upsert_product_from_candidate(candidate)
        return {"created": created, "updated": updated, "ambiguous": ambiguous}

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

            normalized_key = normalize_key(tcg_key, tcg_label)[0]
            candidate["tcg_key"] = normalized_key
            candidate["tcg"] = display_name(normalized_key, tcg_label)

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
            evidence_text = "\n".join(
                str(hit.get(key, ""))
                for key in (
                    "application_period", "order_period", "result_date",
                    "notice", "text", "description", "status",
                )
                if hit.get(key)
            )
            hit = ApplicationPeriodParser().enrich_site(
                hit,
                evidence_text,
                release_date=str(candidate.get("release_date", "")),
            )
            hit = normalize_application_site(hit, product=candidate)
            hits.append(hit)
        if not hits:
            return

        product_id = (
            f"retail_{candidate.get('id', '')}"
        )

        product = {
            "id": product_id,
            "tcg_key": normalize_key(
                candidate.get("tcg_key"), candidate.get("tcg")
            )[0],
            "tcg": display_name(
                candidate.get("tcg_key"), candidate.get("tcg")
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
            "product_kind": candidate.get("product_kind", "その他"),
            "product_code": candidate.get("product_code", ""),
            "official_product_id": candidate.get("official_product_id", ""),
            "jan_code": candidate.get("jan_code", ""),
            "msrp": candidate.get("msrp"),
            "msrp_includes_tax": candidate.get("msrp_includes_tax", True),
            "reference_price": candidate.get("reference_price"),
            "sites": hits,
        }

        from core.product_store import ProductStore

        ProductStore(self.root).merge_discovered_products([product])

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
        key: tuple[str, str, str],
        *,
        official_url: str,
        source_name: str,
        source_id: str,
    ) -> None:
        for item in candidates:
            item_key = (
                normalize_key(item.get("tcg_key"), item.get("tcg"))[0],
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
    def _is_new_release_candidate(product: dict[str, Any], tcg_key: str) -> bool:
        if tcg_key not in {"onepiece", "gundam", "union_arena"}:
            return bool(str(product.get("name", "")).strip())
        allowed = {
            "onepiece": {
                "ブースターパック", "エクストラブースター", "スタートデッキ",
                "プレミアムカードコレクション", "プレミアム商品", "その他",
            },
            "gundam": {
                "ブースターパック", "スタートデッキ", "プレミアムバンダイ", "その他",
            },
            "union_arena": {
                "ブースターパック", "スタートデッキ", "構築済みデッキ",
                "プレミアム商品", "その他カード商品",
            },
        }
        kind = str(product.get("product_kind", "その他"))
        if kind not in allowed[tcg_key]:
            return False
        name = str(product.get("name", ""))
        if kind == "その他":
            lowered_name = name.casefold()
            if any(term in lowered_name for term in (
                "スリーブ", "プレイマット", "ケース", "アクセサリー", "sleeve", "playmat", "case",
            )):
                return False
            if not re.search(r"カード|セット|コレクション|card|set|collection", lowered_name, re.IGNORECASE):
                return False
        release_text = str(product.get("release_date", "")).strip()
        if not release_text:
            # Some current ONE PIECE official catalogue entries expose no date
            # in the list/detail HTML.  Preserve those official card products as
            # candidates; AutoMonitorManager will keep them out of monitoring
            # until a reliable release date is available.
            if tcg_key not in {"onepiece", "union_arena"} or not product.get("manufacturer_official"):
                return False
        if release_text:
            try:
                release = datetime.strptime(release_text, "%Y-%m-%d").date()
            except ValueError:
                return False
            age_days = (date.today() - release).days
            if age_days > 45 or age_days < -730:
                return False
        url = str(product.get("official_url", ""))
        if not url:
            sites = product.get("sites", [])
            url = str(sites[0].get("url", "")) if sites else ""
        if not url.startswith("https://"):
            return False
        lowered = (name + " " + url).casefold()
        return not any(
            term in lowered for term in ("cardlist", "event", "rule", "カードリスト", "イベント", "ルール")
        )

    @staticmethod
    def _build_search_diagnostics(
        hits: list[dict[str, Any]], messages: list[str]
    ) -> dict[str, Any]:
        for message in reversed(messages):
            if not message.startswith("店舗発見診断JSON:"):
                continue
            try:
                parsed = json.loads(message.removeprefix("店舗発見診断JSON:"))
            except json.JSONDecodeError:
                break
            if isinstance(parsed, dict):
                return parsed
        excluded = [message.removeprefix("除外: ") for message in messages if message.startswith("除外: ")]
        searched = [message for message in messages if not message.startswith(("除外:", "検索診断:", "店舗発見診断JSON:"))]
        return {
            "searched_store_count": len(searched),
            "found_store_count": len({str(hit.get("site_key", "")) for hit in hits}) + len(excluded),
            "regular_retail_count": len({str(hit.get("site_key", "")) for hit in hits}),
            "excluded_count": len(excluded),
            "new_store_candidate_count": sum("管理者確認待ち" in message for message in messages),
            "excluded_reasons": excluded,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

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
        fields = (
            CANDIDATE_LIST_FIELDS
            if path.name == "candidates.json"
            else PRODUCT_LIST_FIELDS
        )
        return (
            inspect_json_file(
                path,
                list,
                nullable_list_fields=fields,
            ).data
            or []
        )

    @staticmethod
    def _save_list(
        path: Path,
        data: list[dict[str, Any]],
    ) -> None:
        fields = (
            CANDIDATE_LIST_FIELDS
            if path.name == "candidates.json"
            else PRODUCT_LIST_FIELDS
        )
        ensure_json_writable(
            path,
            list,
            nullable_list_fields=fields,
        )
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

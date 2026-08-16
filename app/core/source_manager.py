import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from core.official_diff_tracker import OfficialDiffTracker
from core.pokemon_official_extractor import PokemonOfficialExtractor
from core.yugioh_official_extractor import YugiohOfficialExtractor
from core.onepiece_official_extractor import OnePieceOfficialExtractor
from core.union_arena_official_extractor import UnionArenaOfficialExtractor
from core.gundam_official_extractor import GundamOfficialExtractor
from core.additional_official_extractors import (
    DuelMastersOfficialExtractor,
    MtgOfficialExtractor,
    WeissOfficialExtractor,
)
from core.candidate_manager import CandidateManager
from core.runtime_paths import app_root
from core.secure_https import build_https_opener
from core.tcg_categories import display_name, normalize_key, normalize_record
from core.json_file_state import (
    CORRUPT,
    SOURCE_LIST_FIELDS,
    JsonFileResult,
    ensure_json_writable,
    inspect_json_file,
    restore_json_backup,
)
from core.source_product_extractor import SourceProductExtractor


class SourceManager:
    POKEMON_PRODUCT_API = "https://www.pokemon-card.com/products/topList.php"
    CACHE_TTL_SECONDS = 600
    _response_cache: dict[str, tuple[float, dict[str, Any]]] = {}
    DEFAULT_SOURCES = (
        {
            "name": "ポケモンカードゲーム トレーナーズウェブサイト",
            "url": "https://www.pokemon-card.com/",
            "tcg_key": "pokemon",
        },
        {
            "name": "ワンピースカードゲーム公式",
            "url": "https://www.onepiece-cardgame.com/products/?view=normal",
            "tcg_key": "onepiece",
        },
        {
            "name": "遊戯王OCG公式 商品情報",
            "url": "https://www.yugioh-card.com/japan/products/",
            "tcg_key": "yugioh",
        },
        {
            "name": "ガンダムカードゲーム公式",
            "url": "https://www.gundam-gcg.com/jp/products/",
            "tcg_key": "gundam",
        },
        {
            "name": "UNION ARENA公式 商品情報",
            "url": "https://www.unionarena-tcg.com/jp/products/",
            "tcg_key": "union_arena",
        },
        {
            "name": "デュエル・マスターズ公式 商品情報",
            "url": "https://dm.takaratomy.co.jp/product/",
            "tcg_key": "duelmasters",
        },
        {
            "name": "ヴァイスシュヴァルツ公式 商品情報",
            "url": "https://ws-tcg.com/products/",
            "tcg_key": "weiss",
        },
        {
            "name": "マジック：ザ・ギャザリング日本公式 製品情報",
            "url": "https://mtg-jp.com/products/index.php",
            "tcg_key": "mtg",
        },
    )
    YUGIOH_OFFICIAL_PRODUCTS_URL = (
        "https://www.yugioh-card.com/japan/products/"
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 "
        "PokeyoyaKun/1.1.0"
    )

    def __init__(self):
        self.sources_path = app_root() / "config" / "sources.json"
        self.extractor = SourceProductExtractor()
        self.pokemon_extractor = PokemonOfficialExtractor()
        self.yugioh_extractor = YugiohOfficialExtractor()
        self.onepiece_extractor = OnePieceOfficialExtractor()
        self.gundam_extractor = GundamOfficialExtractor()
        self.union_arena_extractor = UnionArenaOfficialExtractor()
        self.duelmasters_extractor = DuelMastersOfficialExtractor()
        self.weiss_extractor = WeissOfficialExtractor()
        self.mtg_extractor = MtgOfficialExtractor()
        self.diff_tracker = OfficialDiffTracker()
        self.candidate_manager = CandidateManager()

    def load_sources(self) -> list[dict[str, Any]]:
        result = self.inspect_sources_file()
        if result.state == CORRUPT:
            return []
        sources = [normalize_record(item)[0] for item in (result.data or [])]

        merged, changed = self._merge_default_sources(sources)
        if changed:
            self.save_sources(merged)
        return merged

    def inspect_sources_file(self) -> JsonFileResult:
        return inspect_json_file(
            self.sources_path,
            list,
            nullable_list_fields=SOURCE_LIST_FIELDS,
        )

    def restore_sources_backup(self) -> bool:
        return restore_json_backup(
            self.sources_path,
            list,
            nullable_list_fields=SOURCE_LIST_FIELDS,
        )

    def _merge_default_sources(
        self,
        sources: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        merged = [dict(source) for source in sources]
        identities = {
            self._url_identity(str(source.get("url", "")))
            for source in merged
        }
        changed = False
        for default in self.DEFAULT_SOURCES:
            identity = self._url_identity(default["url"])
            if identity in identities:
                continue
            merged.append(self._new_source_record(
                default["name"],
                default["url"],
                default["tcg_key"],
                len(merged) + 1,
                builtin=True,
            ))
            identities.add(identity)
            changed = True
        return merged, changed

    @staticmethod
    def _url_identity(url: str) -> str:
        parsed = urlparse(url.strip())
        if not parsed.scheme or not parsed.netloc:
            return url.strip().casefold().rstrip("/")
        path = parsed.path.rstrip("/") or "/"
        return (
            f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"
            f"{path}?{parsed.query}".rstrip("?")
        )

    def _new_source_record(
        self,
        name: str,
        url: str,
        tcg_key: str,
        priority: int,
        *,
        builtin: bool = False,
    ) -> dict[str, Any]:
        normalized_key = normalize_key(tcg_key)[0]
        return {
            "id": self._make_id(url),
            "name": name.strip() or "名称未設定",
            "url": url.strip(),
            "last_title": "",
            "last_checked": "",
            "last_status": "未確認",
            "check_state": "unchecked",
            "changed": False,
            "last_detected_count": 0,
            "last_added_count": 0,
            "last_detail_pages": 0,
            "last_duplicate_count": 0,
            "last_http_status": "未確認",
            "last_error_reason": "",
            "detected_products": [],
            "official_changes": [],
            "enabled": True,
            "priority": priority,
            "tcg_key": normalized_key,
            "tcg": display_name(normalized_key),
            "builtin": builtin,
        }

    def save_sources(self, sources: list[dict[str, Any]]) -> None:
        ensure_json_writable(
            self.sources_path,
            list,
            nullable_list_fields=SOURCE_LIST_FIELDS,
        )
        self.sources_path.parent.mkdir(parents=True, exist_ok=True)
        with self.sources_path.open("w", encoding="utf-8") as file:
            json.dump(sources, file, ensure_ascii=False, indent=2)

    def add_source(self, name: str, url: str, tcg_key: str = "other") -> None:
        sources = self.load_sources()
        source_id = self._make_id(url)

        if any(source.get("id") == source_id for source in sources):
            return

        sources.append(self._new_source_record(
            name,
            url,
            tcg_key,
            len(sources) + 1,
        ))
        self.save_sources(sources)


    def update_source(
        self,
        source_id: str,
        name: str,
        url: str,
        tcg_key: str | None = None,
    ) -> bool:
        sources = self.load_sources()
        changed = False

        for source in sources:
            if str(source.get("id", "")) != source_id:
                continue

            source["name"] = (
                name.strip()
                or "名称未設定"
            )
            source["url"] = url.strip()
            if tcg_key is not None:
                source["tcg_key"] = normalize_key(tcg_key)[0]
                source["tcg"] = display_name(source["tcg_key"])
            changed = True
            break

        if changed:
            self.save_sources(sources)

        return changed

    def set_enabled(
        self,
        source_id: str,
        enabled: bool,
    ) -> bool:
        sources = self.load_sources()
        changed = False

        for source in sources:
            if str(source.get("id", "")) != source_id:
                continue

            source["enabled"] = bool(enabled)
            changed = True
            break

        if changed:
            self.save_sources(sources)

        return changed

    def remove_source(self, source_id: str) -> None:
        sources = [
            source
            for source in self.load_sources()
            if source.get("id") != source_id
        ]
        self.save_sources(sources)

    def check_all(
        self,
        cancel_requested: Callable[[], bool] | None = None,
        enabled_tcg_keys: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sources = self.load_sources()
        changed_sources = []

        for source in sources:
            if cancel_requested is not None and cancel_requested():
                break
            if not source.get("enabled", True):
                source["last_status"] = "無効"
                source["check_state"] = "unchecked"
                source["changed"] = False
                continue
            source_tcg = normalize_key(source.get("tcg_key"), source.get("tcg"))[0]
            if enabled_tcg_keys is not None and source_tcg not in enabled_tcg_keys:
                source["last_status"] = "監視対象外"
                source["check_state"] = "unchecked"
                source["changed"] = False
                continue
            if self._check_source_record(source):
                changed_sources.append(source.copy())
            if cancel_requested is not None and cancel_requested():
                break

        self.save_sources(sources)
        return sources, changed_sources

    def mark_checking(self, source_id: str) -> bool:
        sources = self.load_sources()
        for source in sources:
            if str(source.get("id", "")) == source_id:
                source["check_state"] = "checking"
                source["last_status"] = "確認中"
                self.save_sources(sources)
                return True
        return False

    def check_source(
        self,
        source_id: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        sources = self.load_sources()
        for source in sources:
            if str(source.get("id", "")) != source_id:
                continue
            if not source.get("enabled", True):
                source["last_status"] = "無効"
                source["check_state"] = "unchecked"
                changed = False
            else:
                changed = self._check_source_record(source)
            self.save_sources(sources)
            return source.copy(), changed
        return None, False

    def _check_source_record(self, source: dict[str, Any]) -> bool:
        old_title = source.get("last_title", "")
        source["last_checked"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        source["last_detected_count"] = 0
        source["last_added_count"] = 0
        source["last_detail_pages"] = 0
        source["last_duplicate_count"] = 0
        source["last_http_status"] = "未確認"
        source["last_error_reason"] = ""
        source["detected_products"] = []
        source["official_changes"] = []
        source["last_candidate_diagnostics"] = {}

        try:
            checked = self._fetch_page(source.get("url", ""))
            source["last_status"] = checked["status"]
            if not checked["ok"]:
                source["last_http_status"] = "失敗"
                source["last_error_reason"] = checked["status"]
                source["check_state"] = "error"
                source["changed"] = False
                return False
            source["last_http_status"] = "成功"

            new_title = checked["title"]
            source["changed"] = bool(old_title and new_title != old_title)
            source["last_title"] = new_title
            source_url = source.get("url", "")
            source_name = source.get("name", "公式情報ソース")

            if self._is_pokemon_official(source_url):
                discovered, detail_pages = self._extract_pokemon_official_products(
                    checked["html"], source_url, source_name
                )
                source["last_detail_pages"] = detail_pages
            elif self._is_yugioh_official(source_url):
                discovered, detail_pages = self._extract_yugioh_official_products(
                    checked["html"], source_url, source_name
                )
                source["last_detail_pages"] = detail_pages
            elif self._is_onepiece_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_onepiece_official_products(
                        checked["html"], checked.get("url", source_url), source_name
                    )
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            elif self._is_gundam_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_gundam_official_products(source_name)
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            elif self._is_union_arena_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_union_arena_official_products(
                        checked["html"], checked.get("url", source_url), source_name
                    )
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            elif self._is_duelmasters_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_catalog_official_products(
                        self.duelmasters_extractor,
                        checked["html"],
                        checked.get("url", source_url),
                        source_name,
                    )
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            elif self._is_weiss_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_catalog_official_products(
                        self.weiss_extractor,
                        checked["html"],
                        checked.get("url", source_url),
                        source_name,
                    )
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            elif self._is_mtg_official(source_url):
                discovered, detail_pages, duplicate_count = (
                    self._extract_mtg_official_products(
                        checked["html"],
                        checked.get("url", source_url),
                        source_name,
                    )
                )
                source["last_detail_pages"] = detail_pages
                source["last_duplicate_count"] = duplicate_count
            else:
                discovered = self.extractor.extract(
                    checked["html"], source_url, source_name
                )
                source_tcg_key = normalize_key(
                    source.get("tcg_key"), source.get("tcg")
                )[0]
                for product in discovered:
                    product["tcg_key"] = source_tcg_key
                    product["tcg"] = display_name(source_tcg_key)

            if not discovered:
                raise ValueError(
                    "ページは取得できましたが、商品を解析できませんでした"
                )

            official_changes = self.diff_tracker.compare_and_update(discovered)
            source["official_changes"] = official_changes
            _, added_count = self.candidate_manager.merge_official_candidates(
                discovered,
                source_id=str(source.get("id", "")),
                source_name=source_name,
                source_url=source_url,
            )
            source["last_candidate_diagnostics"] = dict(
                self.candidate_manager.last_merge_diagnostics
            )
            source["last_detected_count"] = len(discovered)
            source["last_added_count"] = added_count
            source["last_duplicate_count"] += max(
                0, len(discovered) - added_count
            )
            source["detected_products"] = [
                {
                    "name": item.get("name", ""),
                    "release_date": item.get("release_date", ""),
                    "product_kind": item.get("product_kind", "その他"),
                    "product_code": item.get("product_code", ""),
                    "msrp": item.get("msrp"),
                    "msrp_includes_tax": item.get("msrp_includes_tax", True),
                    "reference_price": item.get("reference_price"),
                    "url": (
                        item.get("sites", [{}])[0].get("url", "")
                        if item.get("sites")
                        else ""
                    ),
                    "source_name": source_name,
                    "candidate_added_at": datetime.now().isoformat(timespec="seconds"),
                }
                for item in discovered[:12]
            ]
            detailed = any((
                self._is_pokemon_official(source_url),
                self._is_yugioh_official(source_url),
                self._is_onepiece_official(source_url),
                self._is_gundam_official(source_url),
                self._is_union_arena_official(source_url),
                self._is_duelmasters_official(source_url),
                self._is_weiss_official(source_url),
                self._is_mtg_official(source_url),
            ))
            detail_text = (
                f"商品ページ{source['last_detail_pages']}件解析・" if detailed else ""
            )
            source["last_status"] = (
                "確認成功\n"
                "HTTP取得: 成功\n"
                f"商品取得数: {len(discovered)}件\n"
                f"新規候補: {added_count}件\n"
                f"重複除外: {source['last_duplicate_count']}件\n"
                f"{detail_text}公式変更: {len(official_changes)}件"
            )
            source["check_state"] = "checked"
            return bool(source["changed"] or added_count or official_changes)
        except Exception as error:
            source["last_error_reason"] = str(error)
            source["last_status"] = (
                "確認失敗\n"
                f"HTTP取得: {source.get('last_http_status', '失敗')}\n"
                f"エラー理由: {error}"
            )
            source["check_state"] = "error"
            source["changed"] = False
            return False

    def _extract_onepiece_official_products(
        self, top_html: str, source_url: str, source_name: str
    ) -> tuple[list[dict], int, int]:
        self.onepiece_extractor.validate_japanese_page(top_html, source_url)
        all_products = self.onepiece_extractor.extract_list_products(
            top_html, source_url, source_name
        )
        detail_pages = 0
        for page_url in self.onepiece_extractor.collect_page_urls(top_html, source_url):
            if self._url_identity(page_url) == self._url_identity(source_url):
                continue
            checked = self._fetch_page(page_url)
            if not checked["ok"]:
                continue
            detail_pages += 1
            all_products.extend(self.onepiece_extractor.extract_list_products(
                checked["html"], checked.get("url", page_url), source_name
            ))
            time.sleep(0.25)
        products, duplicates = self._deduplicate_products(all_products)
        for product in [item for item in products if not item.get("release_date")][
            : self.onepiece_extractor.MAX_DETAIL_PAGES
        ]:
            checked = self._fetch_page(product["official_url"])
            if not checked["ok"]:
                continue
            detail_pages += 1
            supplement = self.onepiece_extractor.supplement_from_detail(
                checked["html"], checked.get("url", product["official_url"])
            )
            product["release_date"] = supplement.get("release_date", "")
            if supplement.get("msrp"):
                product["msrp"] = supplement["msrp"]
                product["reference_price"] = supplement["msrp"]
            time.sleep(0.25)
        # An official card product without a machine-readable release date is
        # still a valid discovery candidate.  Auto-monitoring separately
        # requires a usable date, so preserving it here cannot start premature
        # monitoring but prevents an official product from disappearing.
        return products, detail_pages, duplicates

    def _extract_gundam_official_products(
        self, source_name: str
    ) -> tuple[list[dict], int, int]:
        first = self._fetch_page(self.gundam_extractor.LIST_URL)
        if not first["ok"]:
            raise ValueError(first["status"])
        first_url = first.get("url", self.gundam_extractor.LIST_URL)
        self.gundam_extractor.validate_japanese_page(first["html"], first_url)
        all_products = self.gundam_extractor.extract_list_products(
            first["html"], first_url, source_name
        )
        detail_pages = 1
        for page_url in self.gundam_extractor.collect_page_urls(first["html"], first_url):
            if self._url_identity(page_url) == self._url_identity(first_url):
                continue
            checked = self._fetch_page(page_url)
            if not checked["ok"]:
                continue
            detail_pages += 1
            all_products.extend(self.gundam_extractor.extract_list_products(
                checked["html"], checked.get("url", page_url), source_name
            ))
            time.sleep(0.25)
        products, duplicates = self._deduplicate_products(all_products)
        for product in [item for item in products if not item.get("release_date")][
            : self.gundam_extractor.MAX_DETAIL_PAGES
        ]:
            checked = self._fetch_page(product["official_url"])
            if not checked["ok"]:
                continue
            detail_pages += 1
            supplement = self.gundam_extractor.supplement_from_detail(
                checked["html"], checked.get("url", product["official_url"])
            )
            product["release_date"] = supplement.get("release_date", "")
            if supplement.get("msrp"):
                product["msrp"] = supplement["msrp"]
                product["reference_price"] = supplement["msrp"]
            time.sleep(0.25)
        return [item for item in products if item.get("release_date")], detail_pages, duplicates

    def _extract_union_arena_official_products(
        self, top_html: str, source_url: str, source_name: str
    ) -> tuple[list[dict], int, int]:
        extractor = self.union_arena_extractor
        products = extractor.extract_list_products(top_html, source_url, source_name)
        products, duplicates = self._deduplicate_products(products)
        detail_pages = 0
        for product in products[: extractor.MAX_DETAIL_PAGES]:
            checked = self._fetch_page(product["official_url"])
            if not checked["ok"]:
                continue
            detail_pages += 1
            supplement = extractor.supplement_from_detail(
                checked["html"], checked.get("url", product["official_url"])
            )
            for key in ("product_code", "jan", "release_date"):
                if supplement.get(key):
                    product[key] = supplement[key]
            if supplement.get("msrp"):
                product["msrp"] = supplement["msrp"]
                product["reference_price"] = supplement["msrp"]
            time.sleep(0.1)
        return products, detail_pages, duplicates

    def _extract_catalog_official_products(
        self,
        extractor: Any,
        top_html: str,
        source_url: str,
        source_name: str,
    ) -> tuple[list[dict], int, int]:
        extractor.validate_japanese_page(top_html, source_url)
        products = extractor.extract_list_products(top_html, source_url, source_name)
        deduplicated, duplicates = self._deduplicate_products(products)
        return (
            [item for item in deduplicated if item.get("release_date")],
            1,
            duplicates,
        )

    def _extract_mtg_official_products(
        self,
        top_html: str,
        source_url: str,
        source_name: str,
    ) -> tuple[list[dict], int, int]:
        self.mtg_extractor.validate_japanese_page(top_html, source_url)
        products = self.mtg_extractor.extract_list_products(
            top_html, source_url, source_name
        )
        products, duplicates = self._deduplicate_products(products)
        detail_pages = 1
        for product in products[: self.mtg_extractor.MAX_DETAIL_PAGES]:
            checked = self._fetch_page(product["official_url"])
            if not checked["ok"]:
                continue
            detail_pages += 1
            supplement = self.mtg_extractor.supplement_from_detail(
                checked["html"], checked.get("url", product["official_url"])
            )
            product["release_date"] = str(supplement.get("release_date", ""))
            product["image_url"] = str(supplement.get("image_url", ""))
            if supplement.get("msrp"):
                product["msrp"] = supplement["msrp"]
                product["reference_price"] = supplement["msrp"]
            time.sleep(0.25)
        return [item for item in products if item.get("release_date")], detail_pages, duplicates

    @classmethod
    def _deduplicate_products(cls, products: list[dict]) -> tuple[list[dict], int]:
        output = []
        seen = set()
        duplicates = 0
        for product in products:
            key = str(product.get("official_url", "")).casefold() or (
                cls._normalize_name(str(product.get("name", ""))),
                str(product.get("release_date", "")),
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            output.append(product)
        return output, duplicates

    def _extract_pokemon_official_products(
        self,
        top_html: str,
        source_url: str,
        source_name: str,
    ) -> tuple[list[dict], int]:
        catalog = self._fetch_page(self.POKEMON_PRODUCT_API)
        products = []
        if catalog["ok"]:
            products = self.pokemon_extractor.extract_catalog_products(
                catalog["html"], source_name
            )

        candidates = self.pokemon_extractor.collect_candidate_links(
            top_html,
            source_url,
        )
        detail_pages = 0
        seen = {
            (self._normalize_name(str(item.get("name", ""))), str(item.get("release_date", "")))
            for item in products
        }

        special_queue = []
        for candidate in candidates:
            if "30th.pokemon-card.com/product/" not in candidate["url"]:
                continue
            checked = self._fetch_page(candidate["url"])

            if not checked["ok"]:
                continue

            detail_pages += 1
            found = self.pokemon_extractor.extract_detail_products(
                checked["html"],
                candidate["url"],
                source_name,
                candidate.get("text", ""),
            )
            if "30th.pokemon-card.com/product/" in candidate["url"]:
                for href in re.findall(r'href=["\']([^"\']+)["\']', checked["html"], re.IGNORECASE):
                    extra = urljoin(candidate["url"], unescape(href))
                    if re.fullmatch(
                        r"https://www\.30th\.pokemon-card\.com/product/(?:furbox|cardset)",
                        extra.rstrip("/"),
                    ):
                        special_queue.append(extra.rstrip("/"))

            for product in found:
                key = (
                    self._normalize_name(
                        str(product.get("name", ""))
                    ),
                    str(product.get("release_date", "")),
                )
                if key in seen:
                    continue

                seen.add(key)
                products.append(product)

            # 公式サイトへ負荷をかけすぎない。
            time.sleep(0.25)

        for detail_url in dict.fromkeys(special_queue):
            checked = self._fetch_page(detail_url)
            if not checked["ok"]:
                continue
            detail_pages += 1
            for product in self.pokemon_extractor.extract_detail_products(
                checked["html"], detail_url, source_name
            ):
                key = (self._normalize_name(str(product.get("name", ""))), str(product.get("release_date", "")))
                if key not in seen:
                    seen.add(key)
                    products.append(product)
            time.sleep(0.25)

        # API停止時だけ旧HTML解析へ戻る。
        if not products:
            products = self.extractor.extract(
                top_html,
                source_url,
                source_name,
            )

        return products, detail_pages

    def _extract_yugioh_official_products(
        self,
        top_html: str,
        source_url: str,
        source_name: str,
    ) -> tuple[list[dict], int]:
        candidates = self.yugioh_extractor.collect_candidate_links(
            top_html, source_url
        )
        products = []
        detail_pages = 0
        seen = set()
        for candidate in candidates:
            checked = self._fetch_page(candidate["url"])
            if not checked["ok"]:
                continue
            detail_pages += 1
            for product in self.yugioh_extractor.extract_detail_products(
                checked["html"],
                candidate["url"],
                source_name,
                candidate.get("text", ""),
            ):
                key = (
                    self._normalize_name(str(product.get("name", ""))),
                    str(product.get("release_date", "")),
                )
                if key not in seen:
                    seen.add(key)
                    products.append(product)
            time.sleep(0.25)
        if not products:
            products = self.extractor.extract(top_html, source_url, source_name)
            for product in products:
                product["tcg_key"] = "yugioh"
                product["tcg"] = "遊戯王OCG"
        return products, detail_pages

    def _fetch_page(self, url: str) -> dict[str, Any]:
        if not url.lower().startswith(("http://", "https://")):
            return {
                "ok": False,
                "title": "",
                "html": "",
                "status": "URLが正しくありません",
            }

        now = time.monotonic()
        expired = [
            key for key, (stored_at, _value) in self._response_cache.items()
            if now - stored_at >= self.CACHE_TTL_SECONDS
        ]
        for key in expired:
            self._response_cache.pop(key, None)
        cached = self._response_cache.get(url)
        if cached and now - cached[0] < self.CACHE_TTL_SECONDS:
            value = dict(cached[1])
            value["cache_hit"] = True
            return value

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
            },
        )

        try:
            opener = build_https_opener()
            with opener.open(request, timeout=20) as response:
                raw = response.read(3_000_000)
                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )
        except urllib.error.HTTPError as error:
            return {
                "ok": False,
                "title": "",
                "html": "",
                "status": f"HTTPエラー {error.code}",
            }
        except urllib.error.URLError as error:
            return {
                "ok": False,
                "title": "",
                "html": "",
                "status": f"接続失敗: {error.reason}",
            }
        except Exception as error:
            return {
                "ok": False,
                "title": "",
                "html": "",
                "status": f"確認失敗: {error}",
            }

        try:
            html = raw.decode(charset, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")

        match = re.search(
            r"<title[^>]*>(.*?)</title>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        title = ""
        if match:
            title = re.sub(
                r"\s+",
                " ",
                unescape(match.group(1)),
            ).strip()

        result = {
            "ok": True,
            "title": title or "タイトル未取得",
            "html": html,
            "status": "確認成功",
            "url": response.geturl(),
        }
        self._response_cache[url] = (now, dict(result))
        return result

    @staticmethod
    def _is_pokemon_official(url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        return host == "pokemon-card.com" or host.endswith(
            ".pokemon-card.com"
        )

    @staticmethod
    def _is_yugioh_official(url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        return host == "yugioh-card.com" or host.endswith(".yugioh-card.com")

    @staticmethod
    def _is_onepiece_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "www.onepiece-cardgame.com"

    @staticmethod
    def _is_gundam_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "www.gundam-gcg.com"

    @staticmethod
    def _is_union_arena_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "www.unionarena-tcg.com"

    @staticmethod
    def _is_duelmasters_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "dm.takaratomy.co.jp"

    @staticmethod
    def _is_weiss_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "ws-tcg.com"

    @staticmethod
    def _is_mtg_official(url: str) -> bool:
        return (urlparse(url).hostname or "").casefold() == "mtg-jp.com"

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(
            r"[\s「」『』・･_\-&＆]",
            "",
            name,
        ).lower()

    @staticmethod
    def _make_id(url: str) -> str:
        return hashlib.sha256(
            url.strip().encode("utf-8")
        ).hexdigest()[:16]

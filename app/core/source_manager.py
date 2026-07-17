import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urlparse

from core.official_diff_tracker import OfficialDiffTracker
from core.pokemon_official_extractor import PokemonOfficialExtractor
from core.yugioh_official_extractor import YugiohOfficialExtractor
from core.candidate_manager import CandidateManager
from core.runtime_paths import app_root
from core.secure_https import build_https_opener
from core.tcg_categories import display_name, normalize_key, normalize_record
from core.source_product_extractor import SourceProductExtractor


class SourceManager:
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
        self.diff_tracker = OfficialDiffTracker()
        self.candidate_manager = CandidateManager()

    def load_sources(self) -> list[dict[str, Any]]:
        if self.sources_path.exists():
            try:
                with self.sources_path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError):
                # 壊れた既存ファイルを初期値で上書きしない。
                return []
            if not isinstance(data, list):
                return []
            sources = [normalize_record(item)[0] for item in data]
        else:
            sources = []

        merged, changed = self._merge_default_sources(sources)
        if changed:
            self.save_sources(merged)
        return merged

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
            "detected_products": [],
            "official_changes": [],
            "enabled": True,
            "priority": priority,
            "tcg_key": normalized_key,
            "tcg": display_name(normalized_key),
            "builtin": builtin,
        }

    def save_sources(self, sources: list[dict[str, Any]]) -> None:
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
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sources = self.load_sources()
        changed_sources = []

        for source in sources:
            if not source.get("enabled", True):
                source["last_status"] = "無効"
                source["check_state"] = "unchecked"
                source["changed"] = False
                continue
            if self._check_source_record(source):
                changed_sources.append(source.copy())

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
        source["detected_products"] = []
        source["official_changes"] = []

        try:
            checked = self._fetch_page(source.get("url", ""))
            source["last_status"] = checked["status"]
            if not checked["ok"]:
                source["check_state"] = "error"
                source["changed"] = False
                return False

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

            official_changes = self.diff_tracker.compare_and_update(discovered)
            source["official_changes"] = official_changes
            _, added_count = self.candidate_manager.merge_official_candidates(
                discovered,
                source_id=str(source.get("id", "")),
                source_name=source_name,
                source_url=source_url,
            )
            source["last_detected_count"] = len(discovered)
            source["last_added_count"] = added_count
            source["detected_products"] = [
                {
                    "name": item.get("name", ""),
                    "release_date": item.get("release_date", ""),
                    "url": (
                        item.get("sites", [{}])[0].get("url", "")
                        if item.get("sites")
                        else ""
                    ),
                }
                for item in discovered[:12]
            ]
            detailed = self._is_pokemon_official(source_url) or self._is_yugioh_official(
                source_url
            )
            detail_text = (
                f"商品ページ{source['last_detail_pages']}件解析・" if detailed else ""
            )
            source["last_status"] = (
                f"確認成功・{detail_text}商品{len(discovered)}件検出"
                f"・新弾候補へ新規{added_count}件追加"
                f"・公式変更{len(official_changes)}件"
            )
            source["check_state"] = "checked"
            return bool(source["changed"] or added_count or official_changes)
        except Exception as error:
            source["last_status"] = f"確認失敗: {error}"
            source["check_state"] = "error"
            source["changed"] = False
            return False

    def _extract_pokemon_official_products(
        self,
        top_html: str,
        source_url: str,
        source_name: str,
    ) -> tuple[list[dict], int]:
        candidates = self.pokemon_extractor.collect_candidate_links(
            top_html,
            source_url,
        )

        products = []
        detail_pages = 0
        seen = set()

        for candidate in candidates:
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

        # 商品詳細リンクが取れなかった場合だけトップHTML解析へ戻る。
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

        return {
            "ok": True,
            "title": title or "タイトル未取得",
            "html": html,
            "status": "確認成功",
        }

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

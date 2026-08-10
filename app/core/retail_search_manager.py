import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

from core.application_period import ApplicationPeriodParser
from core.application_site import normalize_application_site
from core.bushiroad_store_parser import BushiroadStoreParser
from core.card_labo_parser import CardLaboParser
from core.hobby_station_parser import HobbyStationParser
from core.konami_style_parser import KonamiStyleParser
from urllib.parse import urljoin, urlparse

from core.builtin_store_catalog import load_builtin_store_catalog, match_builtin_store
from core.retail_plugin_registry import enabled_plugins_for_tcg
from core.retail_price_policy import RetailPricePolicy
from core.secure_https import build_https_opener
from core.store_candidate_manager import StoreCandidateManager
from core.store_discovery import StoreDiscovery
from core.tcg_categories import normalize_key


POKEMON_CENTER_LOTTERY_INDEX = (
    "https://www.support.pokemoncenter-online.com/"
    "%E6%8A%BD%E9%81%B8%E8%B2%A9%E5%A3%B2%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6"
    "%E3%81%AE%E3%82%88%E3%81%8F%E3%81%82%E3%82%8B%E3%81%94%E8%B3%AA%E5%95%8F"
    "-6a01a29ef091d67966492512"
)

POKEMON_CENTER_CARD_INDEX = (
    "https://www.pokemoncenter-online.com/"
    "pokemon-card-game/"
)

YODOBASHI_LOTTERY = "https://limited.yodobashi.com/"
YODOBASHI_SEARCH = "https://www.yodobashi.com/?word={query}"


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = ""
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag.lower() == "a":
            self.href = urljoin(
                self.base_url,
                str(attrs_dict.get("href", "")).strip(),
            )
            self.parts = [
                str(attrs_dict.get(key, "")).strip()
                for key in ("title", "aria-label")
                if str(attrs_dict.get(key, "")).strip()
            ]

        if tag.lower() == "img" and self.href:
            alt = str(attrs_dict.get("alt", "")).strip()
            if alt:
                self.parts.append(alt)

    def handle_data(self, data):
        text = data.strip()
        if text and self.href:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.href:
            return

        text = re.sub(
            r"\s+",
            " ",
            " ".join(self.parts),
        ).strip()

        self.links.append(
            {
                "url": self.href,
                "text": text,
            }
        )
        self.href = ""
        self.parts = []


class RetailSearchManager:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36 "
        "PokeyoyaKun/1.7.0"
    )

    MIN_CONFIDENCE = 0.75

    def __init__(self):
        self.price_policy = RetailPricePolicy()
        self.bushiroad_store = BushiroadStoreParser()
        self.card_labo = CardLaboParser()
        self.hobby_station = HobbyStationParser()
        self.konami_style = KonamiStyleParser()
        self.store_candidates = StoreCandidateManager()
        self.store_discovery = StoreDiscovery(self.store_candidates)
        self.last_diagnostics: dict[str, Any] = {}

    def search_candidate(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        hits: list[dict[str, Any]] = []
        messages: list[str] = []
        searched_stores: set[str] = set()
        excluded: list[str] = []
        new_store_candidates = 0
        self.store_discovery.candidates = self.store_candidates
        self.store_discovery.reset()
        discovery = {
            "searched_source_count": 0,
            "discovered_store_name_count": 0,
            "existing_store_match_count": 0,
            "duplicate_excluded_count": 0,
            "url_safety_rejected_count": 0,
            "insufficient_evidence_count": 0,
            "save_failure_count": 0,
            "failure_reasons": [],
        }

        tcg_key = normalize_key(
            candidate.get("tcg_key"),
            candidate.get("tcg") or candidate.get("category"),
        )[0]
        searchers = [self._search_yodobashi]
        if tcg_key == "pokemon":
            searchers.insert(0, self._search_pokemon_center)

        for searcher in searchers:
            searched_stores.add(getattr(searcher, "__name__", "dedicated_search"))
            try:
                found, message = searcher(candidate)
                hits.extend(found)
                messages.append(message)
            except Exception as error:
                messages.append(
                    f"{getattr(searcher, '__name__', '専用検索')}: 検索失敗 ({error})"
                )

        for plugin in enabled_plugins_for_tcg(tcg_key):
            plugin_id = str(plugin.get("id", ""))
            if (
                plugin.get("mode") == "dedicated"
                and plugin_id not in {
                    "card_labo",
                    "hobby_station",
                    "konami_style",
                }
            ):
                continue
            searched_stores.add(str(plugin.get("id", plugin.get("name", ""))))

            try:
                if plugin_id == "bushiroad_store":
                    found, message = self.bushiroad_store.search_candidate(candidate)
                elif plugin_id == "card_labo":
                    found, message = self.card_labo.search_candidate(candidate)
                elif plugin_id == "hobby_station":
                    found, message = self.hobby_station.search_candidate(candidate)
                elif plugin_id == "konami_style":
                    found, message = self.konami_style.search_candidate(candidate)
                else:
                    found, message = self._search_generic_plugin(
                        candidate,
                        plugin,
                    )
                if plugin.get("source") != "builtin":
                    for item in found:
                        discovery["discovered_store_name_count"] += 1
                        item["host"] = urlparse(str(item.get("url", ""))).hostname or ""
                        item.update({
                            "source_url": str(plugin.get("index_url") or plugin.get("search_url") or ""),
                            "product_name": str(candidate.get("name", "")),
                            "tcg_key": tcg_key or "unknown",
                            "discovery_type": "reservation_or_lottery",
                            "evidence_text": str(item.get("text", item.get("name", ""))),
                        })
                        if self.store_candidates.add_candidate(item):
                            new_store_candidates += 1
                        else:
                            result = getattr(self.store_candidates, "last_result", {})
                            status = str(result.get("status", "")) if isinstance(result, dict) else ""
                            reason = str(result.get("reason", "")) if isinstance(result, dict) else ""
                            if status == "duplicate":
                                discovery["duplicate_excluded_count"] += 1
                            elif status == "insufficient_evidence":
                                discovery["insufficient_evidence_count"] += 1
                            elif "保存失敗" in reason or "更新失敗" in reason:
                                discovery["save_failure_count"] += 1
                            elif status:
                                discovery["url_safety_rejected_count"] += 1
                            if reason and reason not in discovery["failure_reasons"]:
                                discovery["failure_reasons"].append(reason)
                    messages.append(
                        f"{plugin.get('name', '店舗')}: 新規店舗候補として管理者確認待ち"
                    )
                else:
                    hits.extend(found)
                messages.append(message)
            except Exception as error:
                messages.append(
                    f"{plugin.get('name', '店舗')}: "
                    f"検索失敗 ({error})"
                )

        hits = [
            hit
            for hit in self._deduplicate_hits(hits)
            if float(hit.get("confidence", 0.0))
            >= self.MIN_CONFIDENCE
        ]
        accepted = []
        for hit in hits:
            decision = self.price_policy.evaluate(candidate, hit)
            hit.pop("_evaluation_text", None)
            hit.pop("text", None)
            if not decision["accepted"]:
                excluded.append(
                    f"{hit.get('name', '店舗')}: {decision['exclusion_reason']}"
                )
                continue
            hit.update(decision)
            accepted.append(hit)

        found_stores = {str(hit.get("site_key", "")) for hit in hits}
        regular_stores = {str(hit.get("site_key", "")) for hit in accepted}
        automatic = self.store_discovery.diagnostics
        for key in (
            "discovered_store_name_count", "existing_store_match_count",
            "new_candidate_count", "duplicate_excluded_count",
            "url_safety_rejected_count", "insufficient_evidence_count",
            "save_failure_count",
        ):
            discovery[key] = int(discovery.get(key, 0)) + int(automatic.get(key, 0))
        discovery["failure_reasons"] = list(dict.fromkeys([
            *discovery["failure_reasons"], *automatic.get("failure_reasons", []),
        ]))
        discovery["searched_source_count"] = len(searched_stores)
        new_store_candidates += int(automatic.get("new_candidate_count", 0))
        discovery["new_candidate_count"] = new_store_candidates
        self.last_diagnostics = {
            "searched_store_count": len(searched_stores),
            "found_store_count": len(found_stores),
            "regular_retail_count": len(regular_stores),
            "excluded_count": len(excluded),
            "new_store_candidate_count": new_store_candidates,
            "new_candidate_count": new_store_candidates,
            **discovery,
            "excluded_reasons": excluded,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        messages.extend(f"除外: {reason}" for reason in excluded)
        messages.append(
            "検索診断: "
            f"検索店舗{len(searched_stores)} / 発見{len(found_stores)} / "
            f"正規販売{len(regular_stores)} / 除外{len(excluded)} / "
            f"新規店舗候補{new_store_candidates}"
        )
        messages.append(
            "店舗発見診断JSON:"
            + json.dumps(self.last_diagnostics, ensure_ascii=False, separators=(",", ":"))
        )
        return accepted, messages

    def _search_pokemon_center(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        keywords = self._name_keywords(
            str(candidate.get("name", ""))
        )
        release_date = str(
            candidate.get("release_date", "")
        )

        index = self._fetch(
            POKEMON_CENTER_LOTTERY_INDEX
        )
        if not index["ok"]:
            return (
                [],
                "ポケモンセンターオンライン: "
                + index["status"],
            )

        parser = _LinkParser(
            POKEMON_CENTER_LOTTERY_INDEX
        )
        parser.feed(index["html"])

        matching = [
            link
            for link in parser.links
            if self._matches(
                link.get("text", ""),
                keywords,
            )
            and "pokemoncenter-online.com"
            in link.get("url", "")
        ]

        hits = []

        for link in matching[:4]:
            detail = self._fetch(link["url"])
            if not detail["ok"]:
                continue

            page_text = self._html_to_text(
                detail["html"]
            )
            confidence = self._confidence(
                page_text,
                keywords,
                release_date,
            )
            if confidence < self.MIN_CONFIDENCE:
                continue

            hit = self._build_hit(
                site_key="pokemon_center_online",
                site_name="ポケモンセンターオンライン",
                url=link["url"],
                text=page_text,
                default_status="抽選情報あり",
                confidence=confidence,
            )
            hit["application_method"] = "Web"
            hit["result_mode"] = "account_page"
            hit["regions"] = ["全国"]
            hit["retailer_verified"] = True
            hit["seller"] = "ポケモンセンターオンライン"
            hits.append(hit)

        card_index = self._fetch(
            POKEMON_CENTER_CARD_INDEX
        )
        if card_index["ok"]:
            parser = _LinkParser(
                POKEMON_CENTER_CARD_INDEX
            )
            parser.feed(card_index["html"])

            for link in parser.links:
                link_text = link.get("text", "")
                confidence = self._confidence(
                    link_text,
                    keywords,
                    release_date,
                )
                if confidence < self.MIN_CONFIDENCE:
                    continue

                hits.append(
                    {
                        "site_key": "pokemon_center_online",
                        "name": "ポケモンセンターオンライン",
                        "status": "商品掲載あり",
                        "url": link["url"],
                        "notice": (
                            "公式通販の商品一覧で候補名と"
                            "一致する掲載を検出しました。"
                        ),
                        "application_period": "",
                        "result_date": "",
                        "order_period": "",
                        "application_method": "Web",
                        "result_mode": "account_page",
                        "regions": ["全国"],
                        "retailer_verified": True,
                        "seller": "ポケモンセンターオンライン",
                        "text": link_text,
                        "confidence": confidence,
                        "checked_at": datetime.now().isoformat(
                            timespec="seconds"
                        ),
                    }
                )
                break

        return (
            hits,
            "ポケモンセンターオンライン: "
            f"{len(hits)}件",
        )

    def _search_yodobashi(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        keywords = self._name_keywords(
            str(candidate.get("name", ""))
        )
        release_date = str(
            candidate.get("release_date", "")
        )
        hits = []
        errors = []
        lottery = self._fetch(YODOBASHI_LOTTERY)
        if lottery["ok"]:
            page_text = self._html_to_text(lottery["html"])
            confidence = self._confidence(page_text, keywords, release_date)
            if confidence >= self.MIN_CONFIDENCE:
                hits.append(self._build_hit(
                    site_key="yodobashi_lottery",
                    site_name="ヨドバシ・ドット・コム",
                    url=YODOBASHI_LOTTERY,
                    text=page_text,
                    default_status="抽選情報あり",
                    confidence=confidence,
                ))
        else:
            errors.append("抽選ページ: " + lottery["status"])

        search_url = YODOBASHI_SEARCH.format(
            query=urllib.parse.quote(str(candidate.get("name", "")))
        )
        search = self._fetch(search_url)
        if search["ok"]:
            parser = _LinkParser(search_url)
            parser.feed(search["html"])
            for link in parser.links:
                if urlparse(link["url"]).hostname != "www.yodobashi.com":
                    continue
                confidence = self._confidence(link["text"], keywords, release_date)
                if confidence < self.MIN_CONFIDENCE:
                    continue
                hits.append(self._build_hit(
                    site_key="yodobashi_retail",
                    site_name="ヨドバシ・ドット・コム",
                    url=link["url"],
                    text=link["text"],
                    default_status="販売予定",
                    confidence=confidence,
                ))
                if len(hits) >= 3:
                    break
        else:
            errors.append("商品検索: " + search["status"])

        for hit in hits:
            hit.update({
                "application_method": "Web",
                "result_mode": "account_page",
                "regions": ["全国"],
                "retailer_verified": True,
                "seller": "ヨドバシ・ドット・コム",
            })
        message = f"ヨドバシ: {len(hits)}件"
        if errors:
            message += " / " + " / ".join(errors)
        return hits, message

    def _search_generic_plugin(
        self,
        candidate: dict[str, Any],
        plugin: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        name = str(candidate.get("name", ""))
        product_code = str(candidate.get("product_code", "")).strip()
        release_date = str(
            candidate.get("release_date", "")
        )
        plugin_name = str(
            plugin.get("name", "店舗")
        )
        mode = str(plugin.get("mode", ""))

        if mode == "manual_app":
            return (
                [],
                f"{plugin_name}: アプリ限定。"
                "結果日は公式アプリで確認",
            )

        keywords = self._name_keywords(name)
        query_text = name if not product_code or product_code in name else f"{name} {product_code}"
        query = urllib.parse.quote(query_text)

        if mode == "search_page":
            url = str(
                plugin.get("search_url", "")
            ).format(query=query)
        else:
            url = str(plugin.get("index_url", ""))

        if not url:
            return [], f"{plugin_name}: 検索URL未設定"

        page = self._fetch(url)
        if not page["ok"]:
            return [], f"{plugin_name}: {page['status']}"

        page_text = self._html_to_text(page["html"])
        matches: list[tuple[str, str, float]] = []
        parser = _LinkParser(url)
        parser.feed(page["html"])
        parser.links.extend(self._json_ld_product_links(page["html"], url))
        if plugin.get("source") == "builtin":
            discovery_links = [
                link for link in parser.links
                if self._looks_like_store_name(str(link.get("text", "")))
            ][:100]
            self.store_discovery.inspect_links(
                discovery_links,
                source_url=url,
                product_name=name,
                tcg_key=str(candidate.get("tcg_key", "unknown")),
                discovery_type="reservation_or_lottery",
            )
        if mode == "search_page":
            for link in parser.links:
                link_text = str(link.get("text", ""))
                if not self._is_safe_retail_link(url, str(link.get("url", ""))):
                    continue
                confidence = self._confidence(link_text, keywords, release_date)
                if confidence >= self.MIN_CONFIDENCE:
                    matches.append((str(link.get("url", "")), link_text, confidence))
            matches = matches[:3]
        else:
            confidence = self._confidence(page_text, keywords, release_date)
            if confidence >= self.MIN_CONFIDENCE:
                matches.append((url, page_text, confidence))

        if not matches:
            return [], f"{plugin_name}: 該当商品リンクなし"

        found = []
        for product_url, match_text, confidence in matches:
            hit = self._build_hit(
                site_key=str(plugin.get("id", "")),
                site_name=plugin_name,
                url=product_url,
                text=match_text,
                default_status="商品掲載あり",
                confidence=confidence,
            )
            hit.update({
                "application_method": str(plugin.get("application_method", "")),
                "result_mode": str(plugin.get("result_mode", "manual")),
                "regions": list(plugin.get("regions", ["全国"])),
                "plugin_source": str(plugin.get("source", "builtin")),
                "plugin_version": str(plugin.get("plugin_version", "builtin")),
                "retailer_verified": plugin.get("source") == "builtin",
                "seller": self._extract_seller(match_text, plugin_name),
                "shipped_by": self._extract_shipping_seller(match_text),
                "text": match_text,
            })
            found.append(hit)
        return found, f"{plugin_name}: {len(found)}件"

    def _fetch(
        self,
        url: str,
    ) -> dict[str, Any]:
        try:
            requested = urlparse(url)
            requested_port = requested.port
        except ValueError:
            return {"ok": False, "html": "", "status": "URL形式エラー"}
        if requested.scheme != "https" or requested_port not in (None, 443):
            return {"ok": False, "html": "", "status": "HTTPS以外を拒否"}

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept-Language": (
                    "ja,en-US;q=0.8,en;q=0.6"
                ),
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
            },
        )

        try:
            with build_https_opener().open(request, timeout=20) as response:
                final = urlparse(response.geturl())
                if final.scheme != "https" or final.port not in (None, 443):
                    return {"ok": False, "html": "", "status": "安全でないリダイレクトを拒否"}
                if not self._redirect_allowed(url, response.geturl()):
                    return {"ok": False, "html": "", "status": "公式ドメイン外へのリダイレクトを拒否"}
                raw = response.read(3_000_000)
                charset = (
                    response.headers
                    .get_content_charset()
                    or "utf-8"
                )
        except urllib.error.HTTPError as error:
            return {
                "ok": False,
                "html": "",
                "status": f"HTTPエラー {error.code}",
            }
        except urllib.error.URLError as error:
            return {
                "ok": False,
                "html": "",
                "status": (
                    f"接続失敗: {error.reason}"
                ),
            }
        except Exception as error:
            return {
                "ok": False,
                "html": "",
                "status": f"確認失敗: {error}",
            }

        try:
            html = raw.decode(
                charset,
                errors="replace",
            )
        except LookupError:
            html = raw.decode(
                "utf-8",
                errors="replace",
            )

        return {
            "ok": True,
            "html": html,
            "status": "確認成功",
        }

    def _build_hit(
        self,
        *,
        site_key: str,
        site_name: str,
        url: str,
        text: str,
        default_status: str,
        confidence: float,
    ) -> dict[str, Any]:
        application = self._extract_period(
            text,
            (
                "応募受付期間",
                "抽選お申し込み 受付期間",
                "抽選受付期間",
                "申込期間",
            ),
        )
        result_date = self._extract_period(
            text,
            (
                "抽選結果発表日",
                "当選発表",
                "抽選結果発表",
                "結果発表",
            ),
        )
        order_period = self._extract_period(
            text,
            (
                "注文および、支払い期間",
                "ご注文期限",
                "購入期間",
                "受取期間",
            ),
        )

        if application or "抽選受付中" in text:
            status = "抽選受付中"
        elif "予約受付中" in text or "予約商品" in text:
            status = "予約受付中"
        elif "販売予定" in text or "発売予定" in text:
            status = "販売予定"
        else:
            status = default_status

        notice_parts = []
        if application:
            notice_parts.append(
                "応募受付: " + application
            )
        if result_date:
            notice_parts.append(
                "結果発表: " + result_date
            )
        if order_period:
            notice_parts.append(
                "購入・支払: " + order_period
            )
        notice_parts.append(
            f"照合信頼度: {confidence:.0%}"
        )

        hit = {
            "site_key": site_key,
            "name": site_name,
            "status": status,
            "url": url,
            "notice": "\n".join(notice_parts),
            "application_period": application,
            "result_date": result_date,
            "order_period": order_period,
            "confidence": round(confidence, 3),
            "checked_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "text": text,
        }
        return normalize_application_site(
            ApplicationPeriodParser().enrich_site(hit, text)
        )

    @staticmethod
    def _extract_seller(text: str, fallback: str) -> str:
        match = re.search(
            r"(?:販売元|出品者)\s*[:：]?\s*(.{2,60}?)(?=\s*(?:発送元|発送|販売価格|価格|$))",
            text,
        )
        return match.group(1).strip() if match else fallback

    @staticmethod
    def _extract_shipping_seller(text: str) -> str:
        match = re.search(
            r"(?:発送元|発送)\s*[:：]?\s*(.{2,60}?)(?=\s*(?:販売価格|価格|$))",
            text,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _is_safe_retail_link(search_url: str, product_url: str) -> bool:
        try:
            search = urlparse(search_url)
            product = urlparse(product_url)
            port = product.port
        except ValueError:
            return False
        if product.scheme != "https" or port not in (None, 443):
            return False
        return (search.hostname or "").removeprefix("www.").casefold() == (
            product.hostname or ""
        ).removeprefix("www.").casefold()

    @staticmethod
    def _looks_like_store_name(text: str) -> bool:
        clean = re.sub(r"\s+", " ", text).strip()
        if not 2 <= len(clean) <= 80:
            return False
        return bool(re.search(
            r"店|ショップ|ストア|カード|トレカ|玩具|おもちゃ|電器|書店|"
            r"BOOK|カメラ|Amazon|楽天|Yahoo|DMM",
            clean,
            re.IGNORECASE,
        ))

    @staticmethod
    def _redirect_allowed(requested_url: str, final_url: str) -> bool:
        requested_host = (urlparse(requested_url).hostname or "").casefold()
        final_host = (urlparse(final_url).hostname or "").casefold()
        if requested_host == final_host:
            return True
        catalog = load_builtin_store_catalog()["stores"]
        requested_store = match_builtin_store(catalog, url=requested_url)
        final_store = match_builtin_store(catalog, url=final_url)
        return bool(
            requested_store
            and final_store
            and requested_store["store_group_id"] == final_store["store_group_id"]
        )

    @staticmethod
    def _extract_period(
        text: str,
        labels: tuple[str, ...],
    ) -> str:
        for label in labels:
            pattern = re.compile(
                re.escape(label)
                + r"\s*[:：|｜]?\s*"
                + r"([^\n]{3,120})",
            )
            match = pattern.search(text)
            if not match:
                continue

            value = match.group(1).strip()
            value = re.split(
                r"(?:抽選結果|当選発表|"
                r"ご注文期限|購入期間|"
                r"お届け時期|発売日)",
                value,
                maxsplit=1,
            )[0].strip(" |｜")
            return value[:120]

        return ""

    @classmethod
    def _confidence(
        cls,
        text: str,
        keywords: list[str],
        release_date: str,
    ) -> float:
        normalized = cls._normalize(text)
        if not keywords:
            return 0.0

        matched = sum(
            1 for keyword in keywords
            if keyword in normalized
        )
        score = 0.65 * (
            matched / len(keywords)
        )

        if any(
            word in text
            for word in (
                "抽選",
                "予約",
                "販売",
                "応募",
                "受付",
                "発売",
            )
        ):
            score += 0.20

        if release_date:
            compact = release_date.replace("-", "")
            readable = release_date.replace("-", "/")
            japanese = re.sub(
                r"^(\d{4})-(\d{2})-(\d{2})$",
                r"\1年\2月\3日",
                release_date,
            ).replace("月0", "月").replace("日", "日")
            if (
                compact in normalized
                or readable in text
                or japanese in text
            ):
                score += 0.15

        return min(1.0, score)

    @classmethod
    def _matches(
        cls,
        text: str,
        keywords: list[str],
    ) -> bool:
        normalized = cls._normalize(text)
        return bool(keywords) and all(
            keyword in normalized
            for keyword in keywords
        )

    @classmethod
    def _name_keywords(
        cls,
        name: str,
    ) -> list[str]:
        normalized = cls._normalize(name)

        for removable in (
            "ポケモンカードゲーム",
            "ワンピースカードゲーム",
            "ガンダムカードゲーム",
            "遊戯王ocg",
            "デュエルマスターズtcg",
            "デュエルマスターズ",
            "ヴァイスシュヴァルツ",
            "マジックザギャザリング",
            "magicthegathering",
            "mega",
            "強化拡張パック",
            "拡張パック",
            "ブースターパック",
            "ハイクラスパック",
            "プレミアムデッキセット",
            "スターターセットex",
            "スターターセット",
            "スタートデッキ",
            "スターターデッキ",
            "構築デッキ",
            "デッキセット",
            "box",
        ):
            normalized = normalized.replace(
                cls._normalize(removable),
                "",
            )

        return [normalized] if normalized else []

    @classmethod
    def _json_ld_product_links(
        cls,
        html: str,
        base_url: str,
    ) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []

        def collect(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    collect(item)
                return
            if not isinstance(value, dict):
                return
            value_type = value.get("@type", "")
            types = value_type if isinstance(value_type, list) else [value_type]
            if "Product" in types:
                name = str(value.get("name", "")).strip()
                url = urljoin(base_url, str(value.get("url", "")).strip())
                if name and cls._is_safe_retail_link(base_url, url):
                    output.append({"url": url, "text": name})
            for child in value.values():
                if isinstance(child, (dict, list)):
                    collect(child)

        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                collect(json.loads(unescape(match.group(1)).strip()))
            except (json.JSONDecodeError, TypeError):
                continue
        return output

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(
            r"[\s「」『』・･_\-&＆"
            r"（）()【】\[\]、。！!：:]",
            "",
            unescape(text),
        ).lower()

    @staticmethod
    def _html_to_text(html: str) -> str:
        alts = re.findall(
            r"<img[^>]+alt=[\"']"
            r"([^\"']+)[\"'][^>]*>",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r"<script[^>]*>.*?</script>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(
            r"<style[^>]*>.*?</style>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(
            r"<(br|p|li|tr|td|th|"
            r"h1|h2|h3|h4|div|section)"
            r"[^>]*>",
            "\n",
            html,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", html)
        text = "\n".join(
            [*alts, unescape(text)]
        )
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    @staticmethod
    def _deduplicate_hits(
        hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output = []
        seen = set()

        for hit in hits:
            key = (
                str(hit.get("site_key", "")),
                str(hit.get("url", "")),
            )
            if key in seen:
                continue

            seen.add(key)
            output.append(hit)

        return output

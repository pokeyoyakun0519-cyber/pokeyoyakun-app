import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from core.retail_plugin_registry import enabled_plugins_for_tcg


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
            self.parts = []

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

    def search_candidate(
        self,
        candidate: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        hits: list[dict[str, Any]] = []
        messages: list[str] = []

        tcg_key = str(candidate.get("tcg_key", "other"))
        searchers = [self._search_yodobashi]
        if tcg_key == "pokemon":
            searchers.insert(0, self._search_pokemon_center)

        for searcher in searchers:
            try:
                found, message = searcher(candidate)
                hits.extend(found)
                messages.append(message)
            except Exception as error:
                messages.append(
                    f"{searcher.__name__}: 検索失敗 ({error})"
                )

        for plugin in enabled_plugins_for_tcg(tcg_key):
            if plugin.get("mode") == "dedicated":
                continue

            try:
                found, message = self._search_generic_plugin(
                    candidate,
                    plugin,
                )
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
        return hits, messages

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
        page = self._fetch(YODOBASHI_LOTTERY)

        if not page["ok"]:
            return (
                [],
                "ヨドバシ: " + page["status"],
            )

        page_text = self._html_to_text(page["html"])
        confidence = self._confidence(
            page_text,
            keywords,
            release_date,
        )

        if confidence < self.MIN_CONFIDENCE:
            return [], "ヨドバシ: 該当なし"

        hit = self._build_hit(
            site_key="yodobashi_lottery",
            site_name="ヨドバシ・ドット・コム",
            url=YODOBASHI_LOTTERY,
            text=page_text,
            default_status="抽選情報あり",
            confidence=confidence,
        )
        hit["application_method"] = "Web"
        hit["result_mode"] = "account_page"
        hit["regions"] = ["全国"]

        return [hit], "ヨドバシ: 1件"

    def _search_generic_plugin(
        self,
        candidate: dict[str, Any],
        plugin: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        name = str(candidate.get("name", ""))
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
        query = urllib.parse.quote(name)

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
        confidence = self._confidence(
            page_text,
            keywords,
            release_date,
        )

        if confidence < self.MIN_CONFIDENCE:
            return (
                [],
                f"{plugin_name}: 該当なし "
                f"(信頼度 {confidence:.0%})",
            )

        hit = self._build_hit(
            site_key=str(plugin.get("id", "")),
            site_name=plugin_name,
            url=url,
            text=page_text,
            default_status="販売・抽選情報あり",
            confidence=confidence,
        )
        hit["application_method"] = str(
            plugin.get("application_method", "")
        )
        hit["result_mode"] = str(
            plugin.get("result_mode", "manual")
        )
        hit["regions"] = list(
            plugin.get("regions", ["全国"])
        )
        hit["plugin_source"] = str(
            plugin.get("source", "builtin")
        )
        hit["plugin_version"] = str(
            plugin.get(
                "plugin_version",
                "builtin",
            )
        )

        return (
            [hit],
            f"{plugin_name}: 1件 "
            f"(信頼度 {confidence:.0%})",
        )

    def _fetch(
        self,
        url: str,
    ) -> dict[str, Any]:
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
            with urllib.request.urlopen(
                request,
                timeout=20,
            ) as response:
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

        status = (
            "抽選受付情報あり"
            if application
            else default_status
        )

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

        return {
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
        }

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

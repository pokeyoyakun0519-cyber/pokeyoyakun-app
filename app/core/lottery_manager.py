import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

from core.runtime_paths import app_root
from typing import Any


WIN_KEYWORDS = [
    "当選",
    "ご当選",
    "おめでとうございます",
    "当選しました",
]

LOSE_KEYWORDS = [
    "落選",
    "残念ながら",
    "当選しませんでした",
    "選外",
]

PENDING_KEYWORDS = [
    "抽選中",
    "結果発表前",
    "受付中",
    "確認中",
]


class LotteryManager:
    """
    ユーザーが登録した抽選結果ページを、手動操作時だけ確認する。

    ログイン突破やCAPTCHA回避は行わない。
    ページのタイトルと取得できたHTML本文からキーワードを探し、
    当選・落選・未判定の候補を表示する。
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36 "
        "PokeyoyaKun/0.10"
    )

    def __init__(self):
        self.items_path = app_root() / "config" / "lotteries.json"

    def load_items(self) -> list[dict[str, Any]]:
        if not self.items_path.exists():
            return []

        try:
            with self.items_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save_items(self, items: list[dict[str, Any]]) -> None:
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        with self.items_path.open("w", encoding="utf-8") as file:
            json.dump(items, file, ensure_ascii=False, indent=2)

    def add_item(
        self,
        product_name: str,
        site_name: str,
        url: str,
    ) -> bool:
        items = self.load_items()
        item_id = self._make_id(
            product_name,
            site_name,
            url,
        )

        if any(
            str(item.get("id", "")) == item_id
            for item in items
        ):
            return False

        items.append(
            {
                "id": item_id,
                "product_name": (
                    product_name.strip()
                    or "商品名未設定"
                ),
                "site_name": (
                    site_name.strip()
                    or "サイト名未設定"
                ),
                "url": url.strip(),
                "status": "結果待ち候補",
                "last_checked": "",
                "last_title": "",
                "matched_keyword": "",
            }
        )
        self.save_items(items)
        return True


    def upsert_email_result(
        self,
        result: dict[str, Any],
    ) -> None:
        items = self.load_items()
        message_id = str(
            result.get(
                "gmail_message_id",
                "",
            )
        )
        account_id = str(
            result.get(
                "account_id",
                "",
            )
        )
        item_id = self._make_id(
            str(result.get("product_name", "")),
            str(result.get("site_name", "")),
            message_id + account_id,
        )

        status_map = {
            "当選": "当選候補",
            "落選": "落選候補",
            "要確認": "判定できません",
        }

        item = {
            "id": item_id,
            "tcg_key": str(result.get("tcg_key", "other")),
            "tcg": str(result.get("tcg", "その他")),
            "product_name": str(
                result.get(
                    "product_name",
                    "商品名未設定",
                )
            ) or "商品名未設定",
            "site_name": str(
                result.get(
                    "site_name",
                    "サイト名未設定",
                )
            ) or "サイト名未設定",
            "url": str(
                result.get(
                    "gmail_url",
                    "",
                )
            ),
            "status": status_map.get(
                str(result.get("status", "")),
                "判定できません",
            ),
            "last_checked": datetime.now().strftime(
                "%Y/%m/%d %H:%M:%S"
            ),
            "last_title": str(
                result.get("subject", "")
            ),
            "matched_keyword": str(
                result.get(
                    "matched_keyword",
                    "",
                )
            ),
            "source_type": "gmail",
            "account_email": str(
                result.get(
                    "account_email",
                    "",
                )
            ),
            "confidence": float(
                result.get(
                    "confidence",
                    0.0,
                )
            ),
        }

        for index, existing in enumerate(items):
            if str(existing.get("id", "")) == item_id:
                items[index] = item
                self.save_items(items)
                return

        items.append(item)
        self.save_items(items)

    def remove_item(self, item_id: str) -> None:
        items = [
            item for item in self.load_items()
            if item.get("id") != item_id
        ]
        self.save_items(items)

    def check_all(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items = self.load_items()
        newly_won = []

        for item in items:
            previous_status = item.get("status", "未確認")
            result = self._fetch_and_judge(item.get("url", ""))

            item["status"] = result["status"]
            item["last_checked"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            item["last_title"] = result["title"]
            item["matched_keyword"] = result["matched_keyword"]

            if previous_status != "当選候補" and result["status"] == "当選候補":
                newly_won.append(item.copy())

        self.save_items(items)
        return items, newly_won

    def _fetch_and_judge(self, url: str) -> dict[str, str]:
        if not url.lower().startswith(("http://", "https://")):
            return self._result("URLエラー", "", "")

        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.USER_AGENT},
        )

        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read(750_000)
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as error:
            return self._result(f"HTTPエラー {error.code}", "", "")
        except urllib.error.URLError as error:
            return self._result(f"接続失敗", "", str(error.reason))
        except Exception as error:
            return self._result("確認失敗", "", str(error))

        try:
            html = raw.decode(charset, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")

        title = self._extract_title(html)
        text = self._html_to_text(html)
        combined = f"{title}\n{text}"

        for keyword in WIN_KEYWORDS:
            if keyword in combined:
                return self._result("当選候補", title, keyword)

        for keyword in LOSE_KEYWORDS:
            if keyword in combined:
                return self._result("落選候補", title, keyword)

        for keyword in PENDING_KEYWORDS:
            if keyword in combined:
                return self._result("結果待ち候補", title, keyword)

        return self._result("判定できません", title, "")

    @staticmethod
    def _extract_title(html: str) -> str:
        match = re.search(
            r"<title[^>]*>(.*?)</title>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        return re.sub(r"\s+", " ", unescape(match.group(1))).strip()

    @staticmethod
    def _html_to_text(html: str) -> str:
        html = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _result(status: str, title: str, matched_keyword: str) -> dict[str, str]:
        return {
            "status": status,
            "title": title,
            "matched_keyword": matched_keyword,
        }

    @staticmethod
    def _make_id(product_name: str, site_name: str, url: str) -> str:
        import hashlib

        source = f"{product_name}|{site_name}|{url}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

from __future__ import annotations

import base64
import importlib
import json
import re
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import Any

from core.email_account_manager import EmailAccountManager
from core.gmail_result_history import GmailResultHistory
from core.lottery_manager import LotteryManager
from core.product_store import ProductStore
from core.runtime_paths import app_root
from core.tcg_categories import display_name, normalize_key


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

GMAIL_DEPENDENCIES = (
    ("google-auth", "google.auth.transport.requests"),
    ("google-auth", "google.oauth2.credentials"),
    ("google-auth-oauthlib", "google_auth_oauthlib.flow"),
    ("google-api-python-client", "googleapiclient.discovery"),
)


class GmailDependencyError(RuntimeError):
    pass


class GmailOAuthConfigurationError(RuntimeError):
    pass

WIN_KEYWORDS = (
    "ご当選",
    "当選しました",
    "当選のお知らせ",
    "当選となりました",
    "購入手続き",
)

LOSE_KEYWORDS = (
    "落選",
    "残念ながら",
    "当選となりませんでした",
    "選外",
)

RESULT_KEYWORDS = (
    "抽選結果",
    "当選結果",
    "結果のお知らせ",
    "抽選販売",
)

ORDER_STATUS_KEYWORDS = (
    ("キャンセル", ("キャンセル", "注文取消", "予約取消")),
    ("予約完了", ("予約完了", "予約を承りました", "予約受付完了")),
    ("注文受付", ("注文受付", "ご注文を承りました", "注文完了")),
    ("抽選結果", ("抽選結果", "当選結果", "結果のお知らせ")),
)

YUGIOH_KEYWORDS = (
    "遊戯王",
    "遊戯王OCG",
    "デュエルモンスターズ",
    "遊☆戯☆王",
    "YU-GI-OH",
)
ONEPIECE_KEYWORDS = (
    "ONE PIECEカードゲーム", "ワンピースカード", "ONEPIECE CARD GAME",
)
GUNDAM_KEYWORDS = (
    "ガンダムカードゲーム", "GUNDAM CARD GAME", "GUNDAM GCG",
)
POKEMON_ONLY_KEYWORDS = (
    "ポケモンカード",
    "ポケモンセンター",
    "pokemoncenter",
)

STORE_HINTS = {
    "pokemon_center_online": (
        "ポケモンセンター",
        "pokemoncenter",
    ),
    "yodobashi_lottery": (
        "ヨドバシ",
        "yodobashi",
    ),
    "rakuten_books": (
        "楽天ブックス",
        "rakuten",
    ),
    "seven_net": (
        "セブンネット",
        "7net",
        "omni7",
    ),
    "geo": (
        "ゲオ",
        "geo",
    ),
    "amazon_jp": (
        "amazon.co.jp",
        "アマゾン",
    ),
    "biccamera": (
        "ビックカメラ",
        "biccamera",
    ),
    "joshin": (
        "ジョーシン",
        "joshin",
    ),
}


class GmailResultService:
    def __init__(self):
        root = app_root()
        self.client_secret_path = (
            root / "config" / "google_client_secret.json"
        )
        self.token_dir = (
            root / "config" / "gmail_tokens"
        )
        self.account_manager = EmailAccountManager()
        self.product_store = ProductStore()
        self.lottery_manager = LotteryManager()
        self.history = GmailResultHistory()

    @staticmethod
    def missing_dependencies() -> list[str]:
        missing = []
        for package_name, module_name in GMAIL_DEPENDENCIES:
            try:
                importlib.import_module(module_name)
            except ImportError:
                if package_name not in missing:
                    missing.append(package_name)
        return missing

    @classmethod
    def dependencies_available(cls) -> bool:
        return not cls.missing_dependencies()

    @classmethod
    def require_dependencies(cls) -> None:
        missing = cls.missing_dependencies()
        if missing:
            raise GmailDependencyError(
                "Gmail連携ライブラリが不足しています: "
                + ", ".join(missing)
                + "。最新版のアプリを再インストールしてください。"
            )

    def client_secret_exists(self) -> bool:
        return self.client_secret_path.exists()

    def validate_client_secret(self) -> dict[str, Any]:
        if not self.client_secret_exists():
            raise GmailOAuthConfigurationError(
                "OAuth設定ファイルが未配置です。"
                "デスクトップアプリ用のgoogle_client_secret.jsonを"
                f"次の場所へ配置してください: {self.client_secret_path}"
            )
        try:
            document = json.loads(
                self.client_secret_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise GmailOAuthConfigurationError(
                "OAuth設定エラー: google_client_secret.jsonを読み込めません。"
                "Google CloudからJSONを再取得してください。"
            ) from error
        installed = document.get("installed")
        required = {
            "client_id",
            "client_secret",
            "auth_uri",
            "token_uri",
            "redirect_uris",
        }
        if (
            not isinstance(installed, dict)
            or any(not installed.get(key) for key in required)
        ):
            raise GmailOAuthConfigurationError(
                "OAuth設定エラー: デスクトップアプリ用OAuthクライアントの"
                "JSONではないか、必須項目が不足しています。"
            )
        return document

    def connect_account(
        self,
        account_id: str,
    ) -> dict[str, Any]:
        self.require_dependencies()
        self.validate_client_secret()

        account = self._find_account(account_id)
        if account is None:
            raise RuntimeError(
                "対象のメールアカウントが見つかりません。"
            )

        from google_auth_oauthlib.flow import InstalledAppFlow

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_path),
                GMAIL_SCOPES,
            )
            credentials = flow.run_local_server(
                port=0,
                open_browser=True,
                authorization_prompt_message=(
                    "ブラウザーでGmail読取を許可してください。"
                ),
                success_message=(
                    "Gmail連携が完了しました。"
                    "この画面を閉じてポケヨヤ君へ戻ってください。"
                ),
            )
        except (OSError, ValueError) as error:
            raise GmailOAuthConfigurationError(
                "OAuth設定エラー: Google認証を開始できません。"
                "OAuthクライアント設定とリダイレクトURIを確認してください。"
            ) from error

        self.token_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        token_path = self._token_path(account_id)
        token_path.write_text(
            credentials.to_json(),
            encoding="utf-8",
        )

        self.account_manager.update_connection_status(
            account_id,
            "連携済み",
        )
        return {
            "account_id": account_id,
            "email": account.get("email", ""),
            "status": "連携済み",
        }

    def disconnect_account(
        self,
        account_id: str,
    ) -> None:
        token_path = self._token_path(account_id)
        token_path.unlink(missing_ok=True)
        self.account_manager.update_connection_status(
            account_id,
            "未連携",
        )

    def scan_account(
        self,
        account_id: str,
        *,
        days: int = 60,
    ) -> list[dict[str, Any]]:
        service = self._build_service(account_id)
        account = self._find_account(account_id)
        if account is None:
            raise RuntimeError(
                "メールアカウントが見つかりません。"
            )

        after_date = (
            datetime.now() - timedelta(days=max(1, days))
        ).strftime("%Y/%m/%d")

        query = (
            f"after:{after_date} "
            "(抽選 OR 当選 OR 落選 OR 結果)"
        )

        messages = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=100,
            )
            .execute()
            .get("messages", [])
        )

        applications = self._application_targets()
        results: list[dict[str, Any]] = []

        for item in messages:
            message_id = str(item.get("id", ""))
            if not message_id:
                continue

            if self.history.is_processed(
                account_id,
                message_id,
            ):
                continue

            raw = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="full",
                )
                .execute()
            )
            parsed = self._parse_message(raw)
            judged = self._judge_message(
                parsed,
                applications,
            )
            if judged is None:
                continue

            judged["account_id"] = account_id
            judged["account_email"] = account.get(
                "email",
                "",
            )
            judged["gmail_message_id"] = message_id
            judged["gmail_url"] = (
                "https://mail.google.com/mail/u/0/#all/"
                + message_id
            )
            results.append(judged)

            self._apply_result(judged)
            self.history.mark_processed(
                account_id,
                message_id,
                judged,
            )

        self.account_manager.mark_checked(
            account_id
        )
        return self._deduplicate(results)

    def scan_all_enabled(
        self,
    ) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []

        for account in self.account_manager.load_accounts():
            if not account.get("enabled", True):
                continue
            if account.get("connection_status") != "連携済み":
                continue

            try:
                all_results.extend(
                    self.scan_account(
                        str(account.get("id", ""))
                    )
                )
            except Exception as error:
                all_results.append(
                    {
                        "status": "エラー",
                        "product_name": "",
                        "site_name": "",
                        "subject": str(error),
                        "account_email": account.get(
                            "email",
                            "",
                        ),
                    }
                )

        return self._deduplicate(all_results)

    def _build_service(
        self,
        account_id: str,
    ):
        self.require_dependencies()

        token_path = self._token_path(account_id)
        if not token_path.exists():
            raise RuntimeError(
                "このアカウントはGmail連携されていません。"
            )

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_authorized_user_file(
            str(token_path),
            GMAIL_SCOPES,
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_path.write_text(
                credentials.to_json(),
                encoding="utf-8",
            )

        if not credentials.valid:
            raise RuntimeError(
                "Gmail認証が無効です。再連携してください。"
            )

        return build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )

    def _application_targets(
        self,
    ) -> list[dict[str, Any]]:
        output = []
        for product in self.product_store.load_products():
            for site in product.get("sites", []):
                state = str(
                    site.get(
                        "application_state",
                        "未応募",
                    )
                )
                if state == "未応募":
                    continue

                output.append(
                    {
                        "product_id": str(
                            product.get("id", "")
                        ),
                        "product_name": str(
                            product.get("name", "")
                        ),
                        "site_key": str(
                            site.get("site_key", "")
                        ),
                        "site_name": str(
                            site.get("name", "")
                        ),
                        "site_url": str(
                            site.get("url", "")
                        ),
                        "tcg_key": normalize_key(
                            product.get("tcg_key"), product.get("tcg")
                        )[0],
                        "tcg": display_name(normalize_key(
                            product.get("tcg_key"), product.get("tcg")
                        )[0]),
                    }
                )
        return output

    def _judge_message(
        self,
        message: dict[str, str],
        targets: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        combined = (
            message["subject"]
            + "\n"
            + message["from"]
            + "\n"
            + message["body"]
        )
        normalized = self._normalize(combined)

        status = ""
        matched_keyword = ""

        for keyword in WIN_KEYWORDS:
            if self._normalize(keyword) in normalized:
                status = "当選"
                matched_keyword = keyword
                break

        if not status:
            for keyword in LOSE_KEYWORDS:
                if self._normalize(keyword) in normalized:
                    status = "落選"
                    matched_keyword = keyword
                break

        if not status:
            for result_status, keywords in ORDER_STATUS_KEYWORDS:
                for keyword in keywords:
                    if self._normalize(keyword) in normalized:
                        status = result_status
                        matched_keyword = keyword
                        break
                if status:
                    break

        if not status and not any(
            self._normalize(keyword) in normalized
            for keyword in RESULT_KEYWORDS
        ):
            return None

        best_target = None
        best_score = 0

        for target in targets:
            score = 0
            product_keywords = self._name_keywords(
                target["product_name"]
            )
            score += sum(
                2
                for keyword in product_keywords
                if keyword in normalized
            )

            site_key = target["site_key"]
            site_name = self._normalize(
                target["site_name"]
            )

            if site_name and site_name in normalized:
                score += 3

            for hint in STORE_HINTS.get(
                site_key,
                (),
            ):
                if self._normalize(hint) in normalized:
                    score += 3

            if score > best_score:
                best_score = score
                best_target = target

        if best_target is None or best_score < 3:
            inferred_key = self._infer_tcg_key(normalized)
            return {
                "status": status or "要確認",
                "tcg_key": inferred_key,
                "tcg": display_name(inferred_key),
                "product_name": "",
                "site_name": "",
                "subject": message["subject"],
                "from": message["from"],
                "date": message["date"],
                "matched_keyword": matched_keyword,
                "confidence": 0.4,
            }

        return {
            "status": status or "要確認",
            "product_id": best_target["product_id"],
            "product_name": best_target["product_name"],
            "site_key": best_target["site_key"],
            "site_name": best_target["site_name"],
            "site_url": best_target["site_url"],
            "tcg_key": normalize_key(
                best_target.get("tcg_key"), best_target.get("tcg")
            )[0],
            "tcg": display_name(
                best_target.get("tcg_key"), best_target.get("tcg")
            ),
            "subject": message["subject"],
            "from": message["from"],
            "date": message["date"],
            "matched_keyword": matched_keyword,
            "confidence": min(
                1.0,
                0.45 + best_score * 0.08,
            ),
        }

    @classmethod
    def _infer_tcg_key(cls, normalized: str) -> str:
        normalized = cls._normalize(normalized)
        if any(cls._normalize(term) in normalized for term in ONEPIECE_KEYWORDS):
            return "onepiece"
        if any(cls._normalize(term) in normalized for term in GUNDAM_KEYWORDS):
            return "gundam"
        if any(cls._normalize(term) in normalized for term in YUGIOH_KEYWORDS):
            return "yugioh"
        if any(
            cls._normalize(term) in normalized for term in POKEMON_ONLY_KEYWORDS
        ):
            return "pokemon"
        return "other"

    def _apply_result(
        self,
        result: dict[str, Any],
    ) -> None:
        if result.get("status") not in {
            "当選", "落選", "予約完了", "注文受付", "キャンセル",
        }:
            return

        product_id = str(
            result.get("product_id", "")
        )
        site_key = str(
            result.get("site_key", "")
        )
        site_url = str(
            result.get("site_url", "")
        )

        if product_id and site_key:
            self.product_store.save_site_result(
                product_id,
                site_key,
                site_url,
                str(result["status"]),
            )

        self.lottery_manager.upsert_email_result(result)

    @staticmethod
    def _parse_message(
        raw: dict[str, Any],
    ) -> dict[str, str]:
        payload = raw.get("payload", {})
        headers = {
            str(item.get("name", "")).lower():
            str(item.get("value", ""))
            for item in payload.get("headers", [])
        }

        return {
            "subject": GmailResultService._decode_header(
                headers.get("subject", "")
            ),
            "from": GmailResultService._decode_header(
                headers.get("from", "")
            ),
            "date": headers.get("date", ""),
            "body": GmailResultService._extract_body(
                payload
            ),
        }

    @staticmethod
    def _extract_body(
        payload: dict[str, Any],
    ) -> str:
        texts: list[str] = []

        def walk(part: dict[str, Any]) -> None:
            mime_type = str(
                part.get("mimeType", "")
            )
            data = str(
                part.get("body", {}).get(
                    "data",
                    "",
                )
            )

            if data and mime_type in {
                "text/plain",
                "text/html",
            }:
                try:
                    decoded = base64.urlsafe_b64decode(
                        data + "=" * (-len(data) % 4)
                    ).decode(
                        "utf-8",
                        errors="replace",
                    )
                    if mime_type == "text/html":
                        decoded = re.sub(
                            r"<[^>]+>",
                            " ",
                            decoded,
                        )
                    texts.append(decoded)
                except Exception:
                    pass

            for child in part.get("parts", []):
                if isinstance(child, dict):
                    walk(child)

        walk(payload)
        return re.sub(
            r"\s+",
            " ",
            "\n".join(texts),
        ).strip()

    @staticmethod
    def _decode_header(
        value: str,
    ) -> str:
        output = []

        for part, charset in decode_header(value):
            if isinstance(part, bytes):
                output.append(
                    part.decode(
                        charset or "utf-8",
                        errors="replace",
                    )
                )
            else:
                output.append(part)

        return "".join(output)

    @staticmethod
    def _name_keywords(
        name: str,
    ) -> list[str]:
        cleaned = re.sub(
            r"(強化拡張パック|拡張パック|"
            r"ハイクラスパック|スターターセットex|"
            r"スターターセット|構築デッキ)",
            " ",
            name,
        )
        parts = re.findall(
            r"[A-Za-z0-9一-龠ぁ-んァ-ヶー]{3,}",
            cleaned,
        )
        return [
            GmailResultService._normalize(part)
            for part in parts[:6]
        ]

    @staticmethod
    def _normalize(
        value: str,
    ) -> str:
        return re.sub(
            r"[\s\-ー・･「」『』【】\[\]（）()]",
            "",
            value,
        ).lower()

    @staticmethod
    def _deduplicate(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output = []
        seen = set()

        for item in items:
            key = (
                str(item.get("gmail_message_id", "")),
                str(item.get("account_id", "")),
                str(item.get("status", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append(item)

        return output

    def _find_account(
        self,
        account_id: str,
    ) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.account_manager.load_accounts()
                if str(item.get("id", ""))
                == account_id
            ),
            None,
        )

    def _token_path(
        self,
        account_id: str,
    ) -> Path:
        return (
            self.token_dir
            / f"{account_id}.json"
        )

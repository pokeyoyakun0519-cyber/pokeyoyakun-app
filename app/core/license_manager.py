import json

from core.online_license_client import OnlineLicenseClient
from core.runtime_paths import app_root


class LicenseManager:
    def __init__(self):
        self.online_client = OnlineLicenseClient()
        self.online_key_path = app_root() / "config" / "online_license_key.json"


    def save_online_key(
        self,
        license_key: str,
    ) -> None:
        key = license_key.strip().upper()
        self.online_key_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.online_key_path.write_text(
            json.dumps(
                {"license_key": key},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def load_online_key(self) -> str:
        if not self.online_key_path.exists():
            return ""

        try:
            data = json.loads(
                self.online_key_path.read_text(
                    encoding="utf-8"
                )
            )
            return str(
                data.get(
                    "license_key",
                    "",
                )
            ).strip().upper()
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return ""

    def activate_online(
        self,
        license_key: str,
    ) -> tuple[bool, str]:
        ok, message, _ = (
            self.online_client.activate(
                license_key
            )
        )
        if ok:
            self.save_online_key(
                license_key
            )
        return ok, message

    def request_subscription_code(
        self,
        email: str,
    ) -> tuple[bool, str]:
        ok, message, _ = self.online_client.request_subscription_code(email)
        return ok, message

    def activate_subscription(
        self,
        email: str,
        code: str,
    ) -> tuple[bool, str]:
        ok, message, data = self.online_client.activate_subscription(
            email,
            code,
        )
        if not ok:
            return False, message

        internal_key = str(data.get("license_key", "")).strip().upper()
        if not internal_key:
            return False, "自動認証用ライセンスを保存できませんでした。"
        self.save_online_key(internal_key)
        return True, message

    def verify_online(
        self,
    ) -> tuple[bool, str]:
        key = self.load_online_key()
        if not key:
            return False, "オンラインライセンスキーが登録されていません。"

        ok, message, _ = (
            self.online_client.verify(key)
        )
        return ok, message

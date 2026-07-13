import hashlib
import hmac
import json
from datetime import date
from pathlib import Path

from core.admin_auth import verify_admin_credentials
from core.device_id import get_device_id
from core.license_crypto import verify_signature
from core.online_license_client import OnlineLicenseClient
from core.runtime_paths import app_root


class LicenseManager:
    def __init__(self):
        self.license_path = app_root() / "config" / "license.json"
        self.online_client = OnlineLicenseClient()
        self.online_key_path = app_root() / "config" / "online_license_key.json"

    def load_license(self):
        if not self.license_path.exists():
            return {}

        try:
            return json.loads(
                self.license_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}

    def import_license(self, source_path):
        data = json.loads(
            Path(source_path).read_text(encoding="utf-8")
        )

        if not isinstance(data, dict):
            raise ValueError("形式が正しくありません")

        self.license_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.license_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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

    def verify(self, user_id, password):
        # 開発者本人はライセンスファイルなしで起動できる。
        if verify_admin_credentials(user_id, password):
            return True, "Administratorとして認証しました。"

        data = self.load_license()

        if not data:
            return False, "ライセンスファイルが登録されていません。"

        payload = data.get("payload", {})
        signature = data.get("signature", "")

        if not verify_signature(payload, signature):
            return False, "ライセンスの署名が正しくありません。"

        if payload.get("device_id") != get_device_id():
            return False, "このライセンスは別のPC用です。"

        if payload.get("user_id") != user_id.strip():
            return False, "IDが違います。"

        try:
            expiry = date.fromisoformat(payload.get("expiry", ""))
        except ValueError:
            return False, "ライセンス期限の形式が正しくありません。"

        if expiry < date.today():
            return False, "ライセンスの期限が切れています。"

        try:
            salt = bytes.fromhex(payload.get("password_salt", ""))
        except ValueError:
            return False, "ライセンス情報が壊れています。"

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            200_000,
        ).hex()

        if not hmac.compare_digest(
            payload.get("password_hash", ""),
            actual,
        ):
            return False, "パスワードが違います。"

        return (
            True,
            f'{payload.get("user_id")} / '
            f'有効期限 {expiry.isoformat()}',
        )

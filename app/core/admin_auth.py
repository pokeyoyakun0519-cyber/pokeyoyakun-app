import hashlib
import hmac


ADMIN_ID = "admin"
ADMIN_PASSWORD_SHA256 = "75c8baf4b1e4f265b25bb69e36336de6c6b638e5679f0fbea10755586cdbcb5b"


def verify_admin_credentials(user_id: str, password: str) -> bool:
    """開発用の固定Administrator認証。配布版では無効化する。"""
    entered_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()

    id_ok = hmac.compare_digest(user_id.strip(), ADMIN_ID)
    password_ok = hmac.compare_digest(
        entered_hash,
        ADMIN_PASSWORD_SHA256,
    )

    return id_ok and password_ok

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PUBLIC_KEYRING_PATH = (
    Path(__file__).resolve().parent
    / "online_license_public_keys.json"
)
ALGORITHM = "rsa-pkcs1v15-sha256"
TOKEN_VERSION = 1
ACTIVE_STATUS = "active"
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex(
    "3031300d060960864801650304020105000420"
)


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_public_keys(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for item in data["keys"]:
        if not isinstance(item, dict):
            continue
        key_id = str(item.get("key_id", ""))
        if key_id and key_id not in output:
            output[key_id] = dict(item)
    return output


def _verify_signature(
    claims: dict[str, Any],
    signature: object,
    keyring_path: Path,
) -> bool:
    if not isinstance(signature, dict):
        return False
    algorithm = str(signature.get("algorithm", ""))
    key_id = str(signature.get("key_id", ""))
    encoded = str(signature.get("value", ""))
    if algorithm != ALGORITHM or not key_id or not encoded:
        return False
    key = _load_public_keys(keyring_path).get(key_id)
    if key is None or str(key.get("algorithm", "")) != algorithm:
        return False
    try:
        signature_bytes = base64.b64decode(encoded, validate=True)
        modulus = int(str(key["n"]), 16)
        exponent = int(key["e"])
    except (KeyError, TypeError, ValueError):
        return False
    if modulus <= 0 or exponent <= 1:
        return False
    size = (modulus.bit_length() + 7) // 8
    if len(signature_bytes) != size:
        return False
    signature_int = int.from_bytes(signature_bytes, "big")
    if signature_int >= modulus:
        return False
    encoded_message = pow(signature_int, exponent, modulus).to_bytes(size, "big")
    digest_info = (
        _SHA256_DIGEST_INFO_PREFIX
        + hashlib.sha256(_canonical_payload(claims)).digest()
    )
    padding_size = size - len(digest_info) - 3
    if padding_size < 8:
        return False
    expected = (
        b"\x00\x01"
        + b"\xff" * padding_size
        + b"\x00"
        + digest_info
    )
    return hmac.compare_digest(encoded_message, expected)


def _parse_utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed.astimezone(timezone.utc)


def verify_online_token(
    token: object,
    license_key: str,
    device_id: str,
    *,
    now: datetime | None = None,
    keyring_path: Path = PUBLIC_KEYRING_PATH,
) -> tuple[bool, str, dict[str, Any]]:
    if not isinstance(token, dict):
        return False, "署名付き認証トークンがありません。", {}
    claims = token.get("claims")
    if not isinstance(claims, dict):
        return False, "認証トークンの形式が不正です。", {}
    if not _verify_signature(claims, token.get("signature"), keyring_path):
        return False, "認証トークンの署名またはkey_idが正しくありません。", {}
    try:
        version = int(claims["version"])
        issued_at = _parse_utc(claims["issued_at"])
        expires_at = _parse_utc(claims["expires_at"])
    except (KeyError, TypeError, ValueError):
        return False, "認証トークンの日時または版が不正です。", {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expected_hash = hashlib.sha256(
        license_key.strip().upper().encode("utf-8")
    ).hexdigest()
    if version != TOKEN_VERSION:
        return False, "未対応の認証トークンです。", {}
    if str(claims.get("status", "")) != ACTIVE_STATUS:
        return False, "停止または失効したライセンスです。", {}
    if str(claims.get("device_id", "")) != device_id:
        return False, "別のPC用の認証トークンです。", {}
    if str(claims.get("license_key_hash", "")) != expected_hash:
        return False, "別のライセンス用の認証トークンです。", {}
    if issued_at > current:
        return False, "PC時計が認証時刻より前に戻されています。", {}
    if expires_at <= current:
        return False, "ライセンスの有効期限が切れています。", {}
    return True, "署名付き認証トークンは有効です。", dict(claims)

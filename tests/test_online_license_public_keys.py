from __future__ import annotations

import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.online_license_token import (
    MAX_ISSUED_AT_FUTURE_SKEW,
    PUBLIC_KEYRING_PATH,
    verify_online_token,
)


EXPECTED_KEY_ID = "online-2026-07-vps"
EXPECTED_FINGERPRINT = (
    "5ab3726be8f068ab8305079b04916dd40fa1e259916a4d10b8ea2379e5fe47c7"
)


class OnlineLicensePublicKeysTest(unittest.TestCase):
    def records(self) -> dict[str, dict]:
        payload = json.loads(PUBLIC_KEYRING_PATH.read_text(encoding="utf-8"))
        return {record["key_id"]: record for record in payload["keys"]}

    def test_new_vps_key_fingerprint_and_legacy_key_are_present(self):
        records = self.records()
        self.assertIn("online-2026-07-prod", records)
        self.assertIn(EXPECTED_KEY_ID, records)
        record = records[EXPECTED_KEY_ID]
        self.assertEqual(record["algorithm"], "rsa-pkcs1v15-sha256")
        public_key = rsa.RSAPublicNumbers(
            int(record["e"]),
            int(record["n"], 16),
        ).public_key()
        der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.assertEqual(hashlib.sha256(der).hexdigest(), EXPECTED_FINGERPRINT)
        self.assertEqual(public_key.key_size, 3072)

    def test_unknown_key_id_and_missing_token_fail_closed(self):
        ok, message, data = verify_online_token(None, "PKY-TEST", "PC-1")
        self.assertFalse(ok)
        self.assertEqual(data, {})
        self.assertIn("トークン", message)

    @staticmethod
    def token(issued_at: datetime) -> dict:
        license_key = "PKY-CLOCK-TEST"
        claims = {
            "version": 1,
            "issued_at": issued_at.isoformat(),
            "expires_at": (issued_at + timedelta(days=1)).isoformat(),
            "status": "active",
            "device_id": "PC-CLOCK-1",
            "license_key_hash": hashlib.sha256(
                license_key.encode("utf-8")
            ).hexdigest(),
        }
        return {
            "claims": claims,
            "signature": {
                "algorithm": "rsa-pkcs1v15-sha256",
                "key_id": EXPECTED_KEY_ID,
                "value": "test-only",
            },
        }

    def verify_clock_token(
        self,
        issued_at: datetime,
        now: datetime,
    ) -> tuple[bool, str, dict]:
        with patch(
            "core.online_license_token._verify_signature",
            return_value=True,
        ):
            return verify_online_token(
                self.token(issued_at),
                "PKY-CLOCK-TEST",
                "PC-CLOCK-1",
                now=now,
            )

    def test_issued_at_future_clock_skew_within_five_minutes_is_allowed(self):
        current = datetime(2026, 7, 25, 4, 0, tzinfo=timezone.utc)
        for delta in (
            timedelta(seconds=5),
            MAX_ISSUED_AT_FUTURE_SKEW,
        ):
            with self.subTest(delta=delta):
                ok, message, claims = self.verify_clock_token(
                    current + delta,
                    current,
                )
                self.assertTrue(ok, message)
                self.assertTrue(claims)

    def test_issued_at_beyond_future_clock_skew_is_rejected(self):
        current = datetime(2026, 7, 25, 4, 0, tzinfo=timezone.utc)
        ok, message, claims = self.verify_clock_token(
            current + MAX_ISSUED_AT_FUTURE_SKEW + timedelta(microseconds=1),
            current,
        )
        self.assertFalse(ok)
        self.assertEqual(claims, {})
        self.assertIn("PC時計", message)

    def test_naive_validation_clock_is_rejected(self):
        current = datetime(2026, 7, 25, 4, 0, tzinfo=timezone.utc)
        ok, message, claims = self.verify_clock_token(
            current,
            current.replace(tzinfo=None),
        )
        self.assertFalse(ok)
        self.assertEqual(claims, {})
        self.assertIn("タイムゾーン", message)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.online_license_token import PUBLIC_KEYRING_PATH, verify_online_token


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


if __name__ == "__main__":
    unittest.main()

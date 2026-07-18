from __future__ import annotations

import ipaddress
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.feedback_api import FeedbackApiClient, FeedbackApiError
from core.online_license_client import OnlineLicenseClient
from core.public_roadmap import (
    PublicRoadmapCache,
    PublicRoadmapClient,
    PublicRoadmapError,
)
from core.secure_https import (
    TlsConfigurationError,
    build_https_opener,
    create_tls_context,
    tls_ca_diagnostics,
)


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):
        return


def _write_test_certificates(directory: Path) -> tuple[Path, Path, Path]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RC3 Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / "test-ca.pem"
    cert_path = directory / "server-cert.pem"
    key_path = directory / "server-key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


class SecureHttpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(cls.temp_dir.name)
        cls.ca_path, cert_path, key_path = _write_test_certificates(directory)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(str(cert_path), str(key_path))
        cls.server.socket = server_context.wrap_socket(
            cls.server.socket, server_side=True
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"https://localhost:{cls.server.server_port}/health"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp_dir.cleanup()

    def test_certifi_context_requires_certificate_and_hostname(self):
        with patch("core.secure_https.certifi.where", return_value=str(self.ca_path)):
            context = create_tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.cert_store_stats()["x509_ca"], 1)

    def test_https_handler_receives_the_created_context(self):
        context = ssl.create_default_context(cafile=str(self.ca_path))
        marker = object()
        with (
            patch("core.secure_https.create_tls_context", return_value=context),
            patch("core.secure_https.urllib.request.build_opener", return_value=marker) as build,
        ):
            result = build_https_opener(urllib.request.HTTPRedirectHandler())
        self.assertIs(result, marker)
        https_handler = next(
            item for item in build.call_args.args if isinstance(item, urllib.request.HTTPSHandler)
        )
        self.assertIs(https_handler._context, context)

    def test_missing_ca_bundle_fails_closed(self):
        missing = Path(self.temp_dir.name) / "missing-ca.pem"
        with patch("core.secure_https.certifi.where", return_value=str(missing)):
            with self.assertRaises(TlsConfigurationError):
                create_tls_context()
            diagnostics = tls_ca_diagnostics()
        self.assertFalse(diagnostics["ca_bundle_available"])
        self.assertTrue(diagnostics["certificate_verification"])
        self.assertTrue(diagnostics["hostname_verification"])
        self.assertNotIn(str(missing), str(diagnostics))

    def test_missing_ca_refuses_license_feedback_and_roadmap_requests(self):
        error = TlsConfigurationError("TLS CA証明書がありません。")
        license_client = OnlineLicenseClient()
        config = {
            "enabled": True,
            "server_url": "https://api.pokeyoyakun.com",
            "timeout_seconds": 5,
        }
        with (
            patch.object(license_client.config_manager, "load", return_value=config),
            patch("core.online_license_client.build_https_opener", side_effect=error),
        ):
            ok, message = license_client.test_connection()
        self.assertFalse(ok)
        self.assertIn("TLS CA", message)

        with patch("core.feedback_api.build_https_opener", side_effect=error):
            with self.assertRaises(FeedbackApiError):
                FeedbackApiClient()._request("GET", "/api/v1/feedback/receipts/FB-20260101-000000000000")

        cache = PublicRoadmapCache(Path(self.temp_dir.name) / "roadmap.json")
        with patch("core.public_roadmap.build_https_opener", side_effect=error):
            with self.assertRaises(PublicRoadmapError):
                PublicRoadmapClient(cache=cache).list_roadmap(force=True)

    def test_trusted_certificate_is_allowed(self):
        with patch("core.secure_https.certifi.where", return_value=str(self.ca_path)):
            opener = build_https_opener()
            with opener.open(self.url, timeout=5) as response:
                self.assertEqual(response.status, 200)

    def test_untrusted_certificate_is_rejected(self):
        import certifi

        with patch("core.secure_https.certifi.where", return_value=certifi.where()):
            opener = build_https_opener()
            with self.assertRaises(urllib.error.URLError) as raised:
                opener.open(self.url, timeout=5)
        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)

    def test_all_public_clients_use_the_common_https_builder(self):
        self.assertIsNotNone(OnlineLicenseClient)
        self.assertIsNotNone(FeedbackApiClient)
        self.assertIsNotNone(PublicRoadmapClient)
        for relative in (
            "core/online_license_client.py",
            "core/feedback_api.py",
            "core/public_roadmap.py",
        ):
            source = (APP_DIR / relative).read_text(encoding="utf-8")
            self.assertIn("build_https_opener", source)
            self.assertNotIn("_create_unverified_context", source)
            self.assertNotIn("CERT_NONE", source)
            self.assertNotIn("verify=False", source)
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in APP_DIR.rglob("*.py")
        )
        self.assertNotIn("_create_unverified_context", combined)
        self.assertNotIn("CERT_NONE", combined)
        self.assertNotIn("verify=False", combined)

    def test_builds_explicitly_include_certifi_data(self):
        pyinstaller = (PROJECT_ROOT / "tools/build_user_edition.py").read_text(
            encoding="utf-8"
        )
        nuitka = (PROJECT_ROOT / "tools/build_user_edition_nuitka.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--collect-data"', pyinstaller)
        self.assertIn('"certifi"', pyinstaller)
        self.assertIn('"--include-package-data=certifi"', nuitka)


if __name__ == "__main__":
    unittest.main()

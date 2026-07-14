from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
TOOLS_DIR = PROJECT_ROOT / "tools"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(TOOLS_DIR))

from core.release_integrity import verify_runtime_integrity
from core import runtime_paths
from release_security import scan_repository, verify_distribution


class ReleaseIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.exe = self.root / "app.exe"
        self.exe.write_bytes(b"native executable")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.root / "release-integrity.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "algorithm": "sha256",
                    "files": {"app.exe": digest},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _verify(self):
        with (
            patch("core.release_integrity.is_frozen", return_value=True),
            patch("core.release_integrity.install_root", return_value=self.root),
        ):
            return verify_runtime_integrity()

    def test_valid_distribution_passes(self):
        ok, message = self._verify()
        self.assertTrue(ok, message)

    def test_modified_executable_is_rejected(self):
        self.exe.write_bytes(b"modified")
        ok, message = self._verify()
        self.assertFalse(ok)
        self.assertIn("改ざん", message)

    def test_python_source_in_distribution_is_rejected(self):
        (self.root / "debug.py").write_text("print('debug')", encoding="utf-8")
        ok, message = self._verify()
        self.assertFalse(ok)
        self.assertIn("開発用ファイル", message)

    def test_nuitka_runtime_is_treated_as_frozen(self):
        with patch.dict(runtime_paths.__dict__, {"__compiled__": object()}):
            self.assertTrue(runtime_paths.is_frozen())


class ReleaseScannerTest(unittest.TestCase):
    def test_repository_has_no_high_confidence_secret(self):
        self.assertEqual(scan_repository(PROJECT_ROOT), [])

    def test_distribution_rejects_test_and_debug_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "tests" / "debug.py").write_text("pass", encoding="utf-8")
            self.assertTrue(verify_distribution(root))


if __name__ == "__main__":
    unittest.main()

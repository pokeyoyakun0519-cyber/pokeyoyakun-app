from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.version import (
    APP_CHANNEL,
    APP_RELEASE_CHANNEL,
    APP_VERSION,
    format_version_label,
    load_build_channel,
    normalize_build_channel,
)


class BuildChannelLabelTest(unittest.TestCase):
    def test_source_and_unspecified_build_remain_stable(self) -> None:
        self.assertEqual(APP_VERSION, "1.25.0")
        self.assertEqual(APP_CHANNEL, "stable")
        self.assertEqual(APP_RELEASE_CHANNEL, "stable")
        self.assertEqual(
            format_version_label(),
            "Ver.1.25.0 STABLE",
        )
        self.assertEqual(normalize_build_channel(None), "stable")

    def test_test_build_label(self) -> None:
        self.assertEqual(
            format_version_label("TEST"),
            "Ver.1.25.0 TEST",
        )

    def test_rc_test_build_label(self) -> None:
        self.assertEqual(
            format_version_label("  RC5   TEST "),
            "Ver.1.25.0 RC5 TEST",
        )

    def test_generated_metadata_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "build_metadata.json"
            path.write_text(
                json.dumps(
                    {"version": "1.25.0", "channel": "RC5 TEST"}
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_build_channel(path), "rc5 test")

    def test_invalid_or_mismatched_metadata_fails_safe(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "build_metadata.json"
            path.write_text(
                json.dumps(
                    {"version": "1.24.0", "channel": "RC5 TEST"}
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_build_channel(path), "stable")
            with self.assertRaises(ValueError):
                normalize_build_channel("nightly local-path")


if __name__ == "__main__":
    unittest.main()

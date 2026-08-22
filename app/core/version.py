from __future__ import annotations

import json
import re
from pathlib import Path


APP_NAME = "ポケヨヤ君"
APP_VERSION = "1.25.0"
DEFAULT_APP_CHANNEL = "stable"
APP_RELEASE_CHANNEL = "stable"


def normalize_build_channel(value: object) -> str:
    channel = " ".join(str(value or "").strip().split()).lower()
    if not channel:
        return DEFAULT_APP_CHANNEL
    if channel in {"stable", "test"}:
        return channel
    if re.fullmatch(r"rc\d+ test", channel):
        return channel
    raise ValueError("build channel must be stable, test, or RC<number> TEST")


def load_build_channel(metadata_path: Path | None = None) -> str:
    path = metadata_path or Path(__file__).with_name("build_metadata.json")
    if not path.is_file():
        return DEFAULT_APP_CHANNEL
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != APP_VERSION:
            return DEFAULT_APP_CHANNEL
        return normalize_build_channel(payload.get("channel"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DEFAULT_APP_CHANNEL


def format_version_label(channel: object | None = None) -> str:
    normalized = (
        APP_CHANNEL
        if channel is None
        else normalize_build_channel(channel)
    )
    return f"Ver.{APP_VERSION} {normalized.upper()}"


APP_CHANNEL = load_build_channel()

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


TEXT_SUFFIXES = {
    ".py", ".json", ".txt", ".ini", ".cfg", ".toml", ".yaml", ".yml",
    ".env", ".bat", ".ps1", ".iss", ".spec", ".md",
}
IGNORED_PARTS = {".git", "release", "build", "dist", "__pycache__", ".venv", "venv"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".db", ".sqlite", ".sqlite3"}
SENSITIVE_NAMES = {
    ".env",
    "admin_config.json",
    "google_client_secret.json",
    "service_account.json",
}
EXPECTED_PUBLIC_LICENSE_ENDPOINT = "https://api.pokeyoyakun.com"
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "Stripe secret key": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    "database URL": re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s\"']+"),
    "assigned secret": re.compile(
        r"(?i)\b(?:admin_token|api_secret|stripe_secret_key|db_password|private_key)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
}


def verify_public_license_endpoint(root: Path) -> None:
    endpoint_path = root / "app" / "core" / "online_license_endpoint.json"
    try:
        payload = json.loads(endpoint_path.read_text(encoding="utf-8"))
        endpoint = str(payload.get("public_url", "")).strip().rstrip("/")
    except (OSError, AttributeError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"ライセンス接続先設定を読み込めません: {endpoint_path}"
        ) from error
    if endpoint != EXPECTED_PUBLIC_LICENSE_ENDPOINT:
        raise SystemExit(
            "User Editionのライセンス接続先が本番APIではありません: "
            + endpoint
        )


def scan_repository(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.name.lower() in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            findings.append(f"{path.relative_to(root)}: sensitive file must not be distributed")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".env"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}: {label}")
    return findings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_integrity_manifest(
    dist_dir: Path,
    executable_names: list[str],
    *,
    build_commit: str | None = None,
) -> Path:
    files = {}
    for name in executable_names:
        path = dist_dir / name
        if not path.is_file():
            raise SystemExit(f"整合性マニフェスト対象がありません: {path}")
        files[name] = sha256(path)
    manifest = {
        "schema_version": 1,
        "algorithm": "sha256",
        "files": files,
    }
    if build_commit:
        manifest["build_commit"] = build_commit
    destination = dist_dir / "release-integrity.json"
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def verify_distribution(dist_dir: Path) -> list[str]:
    errors: list[str] = []
    forbidden_suffixes = {
        ".py", ".pyc", ".pdb", ".spec", ".map",
        ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pfx", ".p12",
    }
    forbidden_names = {"tests", "test", "__pycache__", "debug", "license_server", "admin_server"}
    forbidden_runtime_names = {
        "admin_config.json",
        "google_client_secret.json",
        "online_license_key.json",
        "online_license_cache.json",
        "online_license_settings.json",
        "feedback_receipts.json",
        "public_roadmap_cache.json",
    }
    for path in dist_dir.rglob("*"):
        lowered_parts = {part.lower() for part in path.relative_to(dist_dir).parts}
        if lowered_parts & forbidden_names:
            errors.append(f"開発・管理用パスが混入: {path}")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes:
            errors.append(f"配布禁止ファイルが混入: {path}")
        if path.is_file() and path.name.lower() in forbidden_runtime_names:
            errors.append(f"ユーザー設定・認証キャッシュが混入: {path}")
        if path.is_file() and "dpapi" in path.name.lower():
            errors.append(f"DPAPI由来ファイルが混入: {path}")
    return errors

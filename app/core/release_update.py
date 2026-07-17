from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import urlsplit

from core.secure_https import build_https_opener


TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-rc(?P<rc>\d+))?$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class ReleaseVersion:
    major: int
    minor: int
    patch: int
    stability: int
    rc: int

    @classmethod
    def parse(cls, value: str) -> "ReleaseVersion":
        match = TAG_PATTERN.fullmatch(value.strip().lower())
        if not match:
            raise UpdateError("Releaseタグの形式が正しくありません。")
        major, minor, patch = (int(item) for item in match.group("version").split("."))
        rc = match.group("rc")
        return cls(major, minor, patch, 1 if rc is None else 0, int(rc or 0))

    @property
    def prerelease(self) -> bool:
        return self.stability == 0


@dataclass(frozen=True)
class UpdateProfile:
    edition_id: str
    metadata_url: str
    allowed_hosts: frozenset[str]
    asset_pattern: re.Pattern[str]
    updater_name: str
    application_name: str
    public_github: bool
    enabled: bool = True
    disabled_reason: str = ""


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise UpdateError("更新URLが正しくありません。") from error
    host = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in allowed_hosts
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UpdateError("許可されていない更新先を拒否しました。")


def parse_sha256sums(text: str, filename: str) -> str:
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        if name.lstrip("*") == filename and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return digest.lower()
    raise UpdateError("SHA256SUMS.txtに対象Setup.exeのハッシュがありません。")


class ReleaseUpdateClient:
    def __init__(
        self,
        profile: UpdateProfile,
        current_tag: str,
        *,
        owner_token_provider: Callable[[], str] | None = None,
    ):
        self.profile = profile
        self.current = ReleaseVersion.parse(current_tag)
        self.owner_token_provider = owner_token_provider

    def check(self, *, allow_prerelease: bool = False) -> dict:
        if not self.profile.enabled:
            raise UpdateError(self.profile.disabled_reason or "更新機能は現在利用できません。")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = self._json(self.profile.metadata_url, headers)
        releases = payload if self.profile.public_github else [payload]
        if not isinstance(releases, list):
            raise UpdateError("更新情報の形式が正しくありません。")
        candidates = []
        for release in releases:
            try:
                candidate = self._candidate(release, allow_prerelease)
            except UpdateError:
                continue
            if candidate and candidate["version"] > self.current:
                candidates.append(candidate)
        if not candidates:
            return {"available": False, "current": self.current, "reason": "現在のバージョンが最新です。"}
        latest = max(candidates, key=lambda item: item["version"])
        latest["available"] = True
        latest["reason"] = "新しいバージョンがあります。"
        return latest

    def _candidate(self, release: dict, allow_prerelease: bool) -> dict | None:
        if not isinstance(release, dict) or release.get("draft"):
            return None
        tag = str(release.get("tag_name", ""))
        version = ReleaseVersion.parse(tag)
        prerelease = bool(release.get("prerelease")) or version.prerelease
        if prerelease and not allow_prerelease:
            return None
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            return None
        setup = next((a for a in assets if self.profile.asset_pattern.fullmatch(str(a.get("name", "")))), None)
        sums = next((a for a in assets if str(a.get("name", "")) == "SHA256SUMS.txt"), None)
        if setup is None or sums is None:
            return None
        match = self.profile.asset_pattern.fullmatch(str(setup["name"]))
        asset_tag = f"v{match.group('version')}" + (f"-rc{match.group('rc')}" if match.group("rc") else "")
        if asset_tag.lower() != tag.lower():
            raise UpdateError("Releaseタグと成果物名のバージョンが一致しません。")
        for asset in (setup, sums):
            validate_url(str(asset.get("browser_download_url", "")), self.profile.allowed_hosts)
        if self.profile.edition_id == "user" and any("owner" in str(a.get("name", "")).lower() for a in assets):
            raise UpdateError("公開ReleaseにOwner成果物が含まれているため拒否しました。")
        return {
            "version": version, "tag": tag, "notes": str(release.get("body", "")),
            "setup_name": str(setup["name"]), "setup_url": str(setup["browser_download_url"]),
            "size": int(setup.get("size", 0)), "sha_url": str(sums["browser_download_url"]),
        }

    def download(
        self,
        release: dict,
        destination: Path,
        *,
        progress: Callable[[int], None] | None = None,
        cancel: Event | None = None,
        retries: int = 2,
    ) -> Path:
        if not self.profile.enabled:
            raise UpdateError(self.profile.disabled_reason or "更新機能は現在利用できません。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        sums = self._text(release["sha_url"], {})
        expected = parse_sha256sums(sums, release["setup_name"])
        error = None
        for attempt in range(retries + 1):
            try:
                self._download_once(release["setup_url"], destination, progress, cancel)
                actual = _sha256(destination)
                if actual != expected:
                    raise UpdateError("Setup.exeのSHA-256が一致しません。")
                destination.with_suffix(destination.suffix + ".sha256").write_text(
                    expected + "\n", encoding="ascii"
                )
                return destination
            except (OSError, urllib.error.URLError, UpdateError) as current:
                destination.unlink(missing_ok=True)
                error = current
                if cancel and cancel.is_set():
                    break
                if attempt < retries:
                    time.sleep(0.25)
        raise UpdateError(f"更新ファイルを取得できません: {error}")

    def _download_once(self, url, destination, progress, cancel):
        validate_url(url, self.profile.allowed_hosts)
        request = urllib.request.Request(url, headers=self._request_headers({}))
        opener = build_https_opener(StrictRedirectHandler(self.profile.allowed_hosts))
        with opener.open(request, timeout=60) as response, destination.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0) or 0)
            received = 0
            while True:
                if cancel and cancel.is_set():
                    raise UpdateError("更新ダウンロードをキャンセルしました。")
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if progress and total:
                    progress(min(100, received * 100 // total))

    def _json(self, url, headers):
        return json.loads(self._text(url, headers))

    def _text(self, url, headers):
        validate_url(url, self.profile.allowed_hosts)
        request = urllib.request.Request(url, headers=self._request_headers(headers))
        opener = build_https_opener(StrictRedirectHandler(self.profile.allowed_hosts))
        try:
            with opener.open(request, timeout=20) as response:
                return response.read(5_000_000).decode("utf-8-sig")
        except urllib.error.HTTPError as error:
            if error.code == 404 and self.profile.public_github:
                raise UpdateError(
                    "GitHub Releaseを取得できません（404）。更新元リポジトリが公開されているか確認してください。"
                ) from error
            raise UpdateError(f"更新情報を取得できません（HTTP {error.code}）。") from error
        except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise UpdateError("更新情報を取得できません。") from error

    def _request_headers(self, extra: dict) -> dict:
        headers = {"User-Agent": "PokeyoyaKun-Updater/1.25.0", **extra}
        if self.profile.edition_id == "owner":
            token = (self.owner_token_provider() if self.owner_token_provider else "").strip()
            if not token:
                raise UpdateError("Owner更新の認証情報がプロビジョニングされていません。")
            headers["Authorization"] = f"Bearer {token}"
        return headers


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.plugin_distribution_config import (
    PluginDistributionConfig,
)
from core.retail_plugin_loader import RetailPluginLoader
from core.runtime_paths import app_root


class OnlinePluginError(RuntimeError):
    pass


class OnlinePluginManager:
    def __init__(self):
        self.config_manager = (
            PluginDistributionConfig()
        )
        self.loader = RetailPluginLoader()
        self.state_path = (
            app_root()
            / "config"
            / "online_plugin_versions.json"
        )

    def check(
        self,
    ) -> dict[str, Any]:
        config = self.config_manager.load()
        if not config.get("enabled", False):
            return {
                "available": [],
                "installed": self._load_versions(),
                "message": "オンラインプラグイン配信は無効です。",
            }

        manifest = self._load_json(
            str(config["manifest_url"]),
            int(config["timeout_seconds"]),
        )
        plugins = manifest.get("plugins", [])
        if not isinstance(plugins, list):
            raise OnlinePluginError(
                "プラグインマニフェストの形式が不正です。"
            )

        installed = self._load_versions()
        available = []

        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue

            plugin_id = str(
                plugin.get("id", "")
            ).strip()
            version = str(
                plugin.get("version", "")
            ).strip()

            if not plugin_id or not version:
                continue

            current = str(
                installed.get(plugin_id, "")
            )
            if (
                not current
                or self._version_tuple(version)
                > self._version_tuple(current)
            ):
                available.append(dict(plugin))

        return {
            "available": available,
            "installed": installed,
            "manifest": manifest,
            "message": (
                f"{len(available)}件の新規・更新プラグインがあります。"
                if available
                else "オンラインプラグインは最新です。"
            ),
        }

    def install_all(
        self,
        plugins: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = []

        for plugin in plugins:
            try:
                path = self.install_plugin(
                    plugin
                )
                results.append(
                    {
                        "ok": True,
                        "id": plugin.get("id", ""),
                        "name": plugin.get("name", ""),
                        "path": str(path),
                    }
                )
            except Exception as error:
                results.append(
                    {
                        "ok": False,
                        "id": plugin.get("id", ""),
                        "name": plugin.get("name", ""),
                        "error": str(error),
                    }
                )

        return results

    def install_plugin(
        self,
        plugin: dict[str, Any],
    ) -> Path:
        plugin_id = str(
            plugin.get("id", "")
        ).strip()
        version = str(
            plugin.get("version", "")
        ).strip()
        url = str(
            plugin.get("download_url", "")
        ).strip()
        expected_sha = str(
            plugin.get("sha256", "")
        ).strip().lower()

        if not plugin_id or not version or not url:
            raise OnlinePluginError(
                "プラグイン情報が不足しています。"
            )

        config = self.config_manager.load()
        timeout = int(
            config.get("timeout_seconds", 15)
        )

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="pokeyoya_plugin_"
            )
        )
        try:
            temp_path = temp_dir / (
                plugin_id + ".json"
            )
            self._download(
                url,
                temp_path,
                timeout,
            )

            if expected_sha:
                actual = self._sha256(
                    temp_path
                )
                if actual != expected_sha:
                    raise OnlinePluginError(
                        "SHA-256が一致しません。"
                    )

            raw = json.loads(
                temp_path.read_text(
                    encoding="utf-8"
                )
            )
            normalized, error = (
                self.loader.validate_plugin(raw)
            )
            if error:
                raise OnlinePluginError(
                    "プラグイン検証エラー: "
                    + error
                )

            if normalized["id"] != plugin_id:
                raise OnlinePluginError(
                    "マニフェストとJSONのIDが一致しません。"
                )

            destination = (
                self.loader.plugin_dir
                / f"{plugin_id}.json"
            )
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.copy2(
                temp_path,
                destination,
            )

            versions = self._load_versions()
            versions[plugin_id] = version
            self._save_versions(versions)
            return destination
        finally:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )

    def _load_versions(
        self,
    ) -> dict[str, str]:
        if not self.state_path.exists():
            return {}

        try:
            data = json.loads(
                self.state_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return {}

        if not isinstance(data, dict):
            return {}

        return {
            str(key): str(value)
            for key, value in data.items()
        }

    def _save_versions(
        self,
        versions: dict[str, str],
    ) -> None:
        self.state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.state_path.write_text(
            json.dumps(
                versions,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _load_json(
        url: str,
        timeout: int,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PokeyoyaKun-PluginClient/1.13.0",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                raw = response.read()
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            raise OnlinePluginError(
                f"プラグインサーバーへ接続できません: {error}"
            ) from error

        try:
            data = json.loads(
                raw.decode("utf-8-sig")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise OnlinePluginError(
                "プラグインマニフェストを読み込めません。"
            ) from error

        if not isinstance(data, dict):
            raise OnlinePluginError(
                "プラグインマニフェストの形式が不正です。"
            )
        return data

    @staticmethod
    def _download(
        url: str,
        destination: Path,
        timeout: int,
    ) -> None:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PokeyoyaKun-PluginClient/1.13.0",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                destination.write_bytes(
                    response.read()
                )
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            raise OnlinePluginError(
                f"プラグインを取得できません: {error}"
            ) from error

    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(
            path.read_bytes()
        )
        return digest.hexdigest()

    @staticmethod
    def _version_tuple(
        version: str,
    ) -> tuple[int, ...]:
        output = []
        for part in version.split("."):
            digits = "".join(
                character
                for character in part
                if character.isdigit()
            )
            output.append(
                int(digits or 0)
            )
        return tuple(output)

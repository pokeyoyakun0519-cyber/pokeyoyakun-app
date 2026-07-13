import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from core.config_manager import ConfigManager
from core.log_manager import LogManager
from sites.base_plugin import BaseSitePlugin
import sites


@dataclass
class PluginInfo:
    plugin_id: str
    display_name: str
    module_name: str
    class_name: str
    enabled: bool
    status: str
    message: str
    instance: BaseSitePlugin | None = None


class PluginManager:
    """app/sites 内のプラグインを自動検出して実行する。"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.log_manager = LogManager()

    def discover_plugins(self) -> list[PluginInfo]:
        config = self.config_manager.load()
        enabled_sites = config.get("sites", {})
        found: list[PluginInfo] = []

        for module_info in pkgutil.iter_modules(sites.__path__):
            module_name = module_info.name
            if module_name.startswith("_") or module_name == "base_plugin":
                continue

            full_name = f"sites.{module_name}"

            try:
                module = importlib.import_module(full_name)
            except Exception as error:
                found.append(
                    PluginInfo(
                        plugin_id=module_name,
                        display_name=module_name,
                        module_name=full_name,
                        class_name="",
                        enabled=False,
                        status="読込エラー",
                        message=str(error),
                    )
                )
                continue

            plugin_classes = []
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, BaseSitePlugin)
                    and obj is not BaseSitePlugin
                    and obj.__module__ == full_name
                ):
                    plugin_classes.append(obj)

            if not plugin_classes:
                found.append(
                    PluginInfo(
                        plugin_id=module_name,
                        display_name=module_name,
                        module_name=full_name,
                        class_name="",
                        enabled=False,
                        status="無効",
                        message="BaseSitePluginを継承したクラスがありません。",
                    )
                )
                continue

            for plugin_class in plugin_classes:
                try:
                    instance = plugin_class()
                    validation_error = self._validate_plugin(instance)
                    plugin_id = instance.plugin_id or module_name
                    display_name = instance.display_name or plugin_class.__name__
                    enabled = bool(enabled_sites.get(plugin_id, False))

                    found.append(
                        PluginInfo(
                            plugin_id=plugin_id,
                            display_name=display_name,
                            module_name=full_name,
                            class_name=plugin_class.__name__,
                            enabled=enabled,
                            status="正常" if not validation_error else "設定エラー",
                            message=validation_error or "読込に成功しました。",
                            instance=instance if not validation_error else None,
                        )
                    )
                except Exception as error:
                    found.append(
                        PluginInfo(
                            plugin_id=module_name,
                            display_name=plugin_class.__name__,
                            module_name=full_name,
                            class_name=plugin_class.__name__,
                            enabled=False,
                            status="初期化エラー",
                            message=str(error),
                        )
                    )

        return sorted(found, key=lambda item: item.display_name.lower())

    def fetch_enabled_products(self) -> tuple[list[dict[str, Any]], list[str]]:
        config = self.config_manager.load()
        enabled_games = config.get("games", {})

        products: list[dict[str, Any]] = []
        messages: list[str] = []

        for info in self.discover_plugins():
            if info.status != "正常" or info.instance is None:
                messages.append(f"{info.display_name}: {info.status} ({info.message})")
                continue

            if not info.enabled:
                messages.append(f"{info.display_name}: 設定でOFF")
                continue

            try:
                plugin_products = info.instance.fetch_products()
            except Exception as error:
                messages.append(f"{info.display_name}: 取得失敗 ({error})")
                self.log_manager.write(
                    f"{info.display_name}の取得に失敗しました: {error}",
                    level="ERROR",
                )
                continue

            if not isinstance(plugin_products, list):
                messages.append(f"{info.display_name}: 返却形式が不正")
                continue

            accepted = 0
            for product in plugin_products:
                if not isinstance(product, dict):
                    continue
                game_key = product.get("tcg_key", "")
                if enabled_games.get(game_key, False):
                    products.append(product)
                    accepted += 1

            messages.append(f"{info.display_name}: {accepted}件読み込み")

        self.log_manager.write(
            f"プラグイン更新を実行しました。取得件数: {len(products)}件"
        )
        return products, messages

    @staticmethod
    def _validate_plugin(plugin: BaseSitePlugin) -> str:
        if not plugin.plugin_id or not isinstance(plugin.plugin_id, str):
            return "plugin_idが設定されていません。"
        if not plugin.display_name or not isinstance(plugin.display_name, str):
            return "display_nameが設定されていません。"
        if not callable(getattr(plugin, "fetch_products", None)):
            return "fetch_productsがありません。"
        return ""

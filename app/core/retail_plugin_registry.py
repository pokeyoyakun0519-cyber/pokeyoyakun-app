from typing import Any

from core.retail_plugin_loader import RetailPluginLoader
from core.retail_plugin_state import RetailPluginState


BUILTIN_RETAIL_PLUGINS: list[dict[str, Any]] = [
    {
        "id": "pokemon_center_online",
        "name": "ポケモンセンターオンライン",
        "mode": "dedicated",
        "regions": ["全国"],
        "tcg": ["pokemon"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "amazon_jp",
        "name": "Amazon.co.jp",
        "mode": "search_page",
        "search_url": "https://www.amazon.co.jp/s?k={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "yodobashi_lottery",
        "name": "ヨドバシ・ドット・コム",
        "mode": "dedicated",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "geo",
        "name": "ゲオ",
        "mode": "public_html",
        "index_url": "https://geo-online.co.jp/news/",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "ゲオ抽選販売専用サイト / GEO ID",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "iaeon_kyushu",
        "name": "iAEON（イオン九州）",
        "mode": "public_html",
        "index_url": "https://www.aeon-kyushu.info/customer/information/archives/category/campaign",
        "regions": ["九州"],
        "tcg": ["pokemon", "onepiece", "gundam", "dragonball"],
        "application_method": "iAEONアプリ",
        "result_mode": "manual_app",
        "enabled": True,
    },
    {
        "id": "kids_republic",
        "name": "キッズリパブリック",
        "mode": "public_html",
        "index_url": "https://www.kidsrepublic.jp/campaign",
        "regions": ["関西", "中国", "四国", "本州"],
        "tcg": ["pokemon"],
        "application_method": "キッズリパブリックアプリ",
        "result_mode": "manual_app",
        "enabled": True,
    },
    {
        "id": "seven_net",
        "name": "セブンネットショッピング",
        "mode": "search_page",
        "search_url": "https://7net.omni7.jp/search/?keyword={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "rakuten_books",
        "name": "楽天ブックス",
        "mode": "search_page",
        "search_url": "https://search.books.rakuten.co.jp/bksearch/nm?sv=30&g=000&keyword={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "zozotown",
        "name": "ZOZOTOWN",
        "mode": "search_page",
        "search_url": "https://zozo.jp/search/?p_keyv={query}",
        "regions": ["全国"],
        "tcg": ["pokemon"],
        "application_method": "Web / アプリ",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "lawson_loppi",
        "name": "ローソン / Loppi",
        "mode": "public_html",
        "index_url": "https://www.lawson.co.jp/lab/entertainment/",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Loppi / 店頭 / Web",
        "result_mode": "manual_store",
        "enabled": True,
    },
    {
        "id": "yamada_app",
        "name": "ヤマダデンキアプリ",
        "mode": "manual_app",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "gundam"],
        "application_method": "ヤマダデジタル会員アプリ",
        "result_mode": "manual_app",
        "enabled": True,
    },
    {
        "id": "sanyodo",
        "name": "三洋堂書店",
        "mode": "public_html",
        "index_url": "https://www.sanyodo.co.jp/news/",
        "regions": ["中部", "関西"],
        "tcg": ["pokemon", "onepiece", "gundam"],
        "application_method": "Web / 店頭",
        "result_mode": "manual_store",
        "enabled": True,
    },
    {
        "id": "premium_bandai",
        "name": "プレミアムバンダイ",
        "mode": "search_page",
        "search_url": "https://p-bandai.jp/search/?text={query}",
        "regions": ["全国"],
        "tcg": ["onepiece", "gundam"],
        "application_method": "Web",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "biccamera",
        "name": "ビックカメラ",
        "mode": "search_page",
        "search_url": "https://www.biccamera.com/bc/category/?q={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web / 店頭",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "joshin",
        "name": "ジョーシン",
        "mode": "search_page",
        "search_url": "https://joshinweb.jp/search/?KEY={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "yugioh", "gundam"],
        "application_method": "Web / アプリ",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "edion",
        "name": "エディオン",
        "mode": "search_page",
        "search_url": "https://www.edion.com/search?keyword={query}",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "gundam"],
        "application_method": "Web / アプリ",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "toysrus",
        "name": "トイザらス",
        "mode": "search_page",
        "search_url": "https://www.toysrus.co.jp/search/?q={query}",
        "regions": ["全国"],
        "tcg": ["pokemon"],
        "application_method": "Web / 店頭",
        "result_mode": "account_page",
        "enabled": True,
    },
    {
        "id": "furuhon_ichiba",
        "name": "古本市場 / ふるいち",
        "mode": "manual_app",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "gundam"],
        "application_method": "ふるいちアプリ / 店頭",
        "result_mode": "manual_app",
        "enabled": True,
    },
    {
        "id": "tsutaya",
        "name": "TSUTAYA",
        "mode": "manual_app",
        "regions": ["全国"],
        "tcg": ["pokemon", "onepiece", "gundam"],
        "application_method": "アプリ / 店頭",
        "result_mode": "manual_app",
        "enabled": True,
    },
]

def load_all_retail_plugins(
) -> tuple[list[dict[str, Any]], list[str]]:
    loader = RetailPluginLoader()
    external, messages = (
        loader.load_external_plugins()
    )

    merged: dict[str, dict[str, Any]] = {
        str(plugin["id"]): {
            **plugin,
            "source": "builtin",
            "plugin_version": str(
                plugin.get(
                    "plugin_version",
                    "builtin",
                )
            ),
            "publisher": str(
                plugin.get(
                    "publisher",
                    "PokeyoyaKun Project",
                )
            ),
        }
        for plugin in BUILTIN_RETAIL_PLUGINS
    }

    for plugin in external:
        # 外部JSONは同じIDの組み込み定義を上書きできる。
        merged[str(plugin["id"])] = plugin

    state = RetailPluginState()

    plugins = []
    for plugin in merged.values():
        plugin = dict(plugin)
        plugin_id = str(
            plugin.get("id", "")
        )
        plugin["enabled"] = state.is_enabled(
            plugin_id,
            bool(plugin.get("enabled", True)),
        )
        plugins.append(plugin)

    return (
        sorted(
            plugins,
            key=lambda item: str(
                item.get("name", "")
            ).lower(),
        ),
        messages,
    )


def enabled_plugins_for_tcg(
    tcg_key: str,
) -> list[dict[str, Any]]:
    plugins, _ = load_all_retail_plugins()
    return [
        dict(plugin)
        for plugin in plugins
        if plugin.get("enabled", True)
        and tcg_key in plugin.get("tcg", [])
    ]

from sites.base_plugin import BaseSitePlugin


class DemoPokemonPlugin(BaseSitePlugin):
    plugin_id = "pokemon_center"
    display_name = "ポケモン系デモ情報源"

    def fetch_products(self) -> list[dict]:
        return [
            {
                "id": "demo_pokemon_box_001",
                "tcg_key": "pokemon",
                "tcg": "ポケモンカード",
                "name": "デモ用 ポケモンカードBOX",
                "release_date": "2026-11-20",
                "status": "予約受付中",
                "favorite": False,
                "reserved": False,
                "sites": [
                    {
                        "site_key": self.plugin_id,
                        "name": self.display_name,
                        "status": "予約受付中",
                        "url": "https://example.com/",
                        "notice": "※注意※ これは動作確認用データです。実際の予約ページではありません。"
                    }
                ]
            }
        ]

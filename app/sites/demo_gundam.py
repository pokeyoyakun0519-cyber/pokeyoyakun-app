from sites.base_plugin import BaseSitePlugin


class DemoGundamPlugin(BaseSitePlugin):
    plugin_id = "rakuten"
    display_name = "ガンダム系デモ情報源"

    def fetch_products(self) -> list[dict]:
        return [
            {
                "id": "demo_gundam_box_001",
                "tcg_key": "gundam",
                "tcg": "ガンダムカードゲーム",
                "name": "デモ用 ガンダムカードBOX",
                "release_date": "2026-10-10",
                "status": "予約開始前",
                "favorite": False,
                "reserved": False,
                "sites": [
                    {
                        "site_key": self.plugin_id,
                        "name": self.display_name,
                        "status": "予約開始前",
                        "url": "https://example.com/",
                        "notice": "※注意※ これは動作確認用データです。"
                    }
                ]
            }
        ]

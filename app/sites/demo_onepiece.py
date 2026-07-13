from sites.base_plugin import BaseSitePlugin


class DemoOnePiecePlugin(BaseSitePlugin):
    plugin_id = "amazon"
    display_name = "ONE PIECE系デモ情報源"

    def fetch_products(self) -> list[dict]:
        return [
            {
                "id": "demo_onepiece_box_001",
                "tcg_key": "onepiece",
                "tcg": "ONE PIECEカードゲーム",
                "name": "デモ用 ONE PIECEカードBOX",
                "release_date": "2026-12-05",
                "status": "抽選受付中",
                "favorite": False,
                "reserved": False,
                "sites": [
                    {
                        "site_key": self.plugin_id,
                        "name": self.display_name,
                        "status": "抽選受付中",
                        "url": "https://example.com/",
                        "notice": "※注意※ これは動作確認用データです。"
                    }
                ]
            }
        ]

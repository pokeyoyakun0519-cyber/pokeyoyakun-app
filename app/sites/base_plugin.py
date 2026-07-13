from abc import ABC, abstractmethod


class BaseSitePlugin(ABC):
    """販売サイトごとの取得処理が従う共通ルール。"""

    plugin_id = ""
    display_name = ""

    @abstractmethod
    def fetch_products(self) -> list[dict]:
        """
        商品情報を返す。

        返却する商品データの主な項目:
        id, tcg, name, release_date, status, favorite, reserved, sites
        """
        raise NotImplementedError

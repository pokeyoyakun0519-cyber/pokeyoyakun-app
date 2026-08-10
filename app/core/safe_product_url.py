from __future__ import annotations

import re
import webbrowser
from urllib.parse import parse_qsl, urlparse

from core.builtin_store_catalog import load_builtin_store_catalog


ALLOWED_PRODUCT_HOSTS = {
    "www.amazon.co.jp", "www.yodobashi.com", "limited.yodobashi.com",
    "www.biccamera.com", "joshinweb.jp", "geo-online.co.jp",
    "7net.omni7.jp", "books.rakuten.co.jp", "search.books.rakuten.co.jp",
    "www.lawson.co.jp", "p-bandai.jp", "www.edion.com",
    "www.sanyodo.co.jp", "www.toysrus.co.jp",
    "www.pokemoncenter-online.com", "www.pokemon-card.com",
    "www.onepiece-cardgame.com", "www.yugioh-card.com",
    "www.gundam-gcg.com", "www.kidsrepublic.jp", "www.aeon-kyushu.info",
}
for _store in load_builtin_store_catalog()["stores"]:
    ALLOWED_PRODUCT_HOSTS.update(str(domain) for domain in _store.get("official_domains", []))
SENSITIVE_QUERY_KEY = re.compile(
    r"^(?:license(?:_?key)?|token|receipt(?:_?number)?|reception(?:_?number)?|"
    r"order(?:_?number)?|email|auth|api_?key|secret_?key)$",
    re.IGNORECASE,
)


def validate_product_url(value: object) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("URLの形式が正しくありません。") from error
    if parsed.scheme.casefold() != "https":
        raise ValueError("HTTPSの商品・応募ページだけを開けます。")
    if parsed.username or parsed.password or (port not in (None, 443)):
        raise ValueError("許可されていないURLです。")
    host = (parsed.hostname or "").casefold()
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_PRODUCT_HOSTS):
        raise ValueError("許可済みの公式・店舗ホストではありません。")
    if any(SENSITIVE_QUERY_KEY.search(key) for key, _ in parse_qsl(parsed.query)):
        raise ValueError("受付番号などを含むURLは開けません。")
    return url


def can_open_product_url(value: object) -> bool:
    try:
        validate_product_url(value)
    except ValueError:
        return False
    return True


def open_product_url(value: object) -> None:
    webbrowser.open(validate_product_url(value))

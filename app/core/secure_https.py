from __future__ import annotations

import ssl
import sys
import urllib.request
from pathlib import Path

import certifi


class TlsConfigurationError(RuntimeError):
    """Raised when a verified HTTPS client cannot be configured safely."""


def certifi_ca_path() -> Path:
    try:
        path = Path(certifi.where()).resolve()
    except Exception as error:
        raise TlsConfigurationError(
            "TLS CA証明書を確認できないため通信を拒否しました。"
        ) from error
    if not path.is_file():
        raise TlsConfigurationError(
            "TLS CA証明書が見つからないため通信を拒否しました。"
        )
    return path


def create_tls_context() -> ssl.SSLContext:
    path = certifi_ca_path()
    try:
        context = ssl.create_default_context(cafile=str(path))
    except (OSError, ssl.SSLError) as error:
        raise TlsConfigurationError(
            "TLS CA証明書を読み込めないため通信を拒否しました。"
        ) from error
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise TlsConfigurationError(
            "TLS証明書検証を有効化できないため通信を拒否しました。"
        )
    return context


def build_https_opener(*handlers) -> urllib.request.OpenerDirector:
    context = create_tls_context()
    https_handler = urllib.request.HTTPSHandler(context=context)
    return urllib.request.build_opener(*handlers, https_handler)


def tls_ca_diagnostics() -> dict[str, bool | str]:
    try:
        create_tls_context()
    except TlsConfigurationError:
        available = False
    else:
        available = True
    return {
        "ca_bundle_available": available,
        "ca_bundle_provider": "certifi",
        "certificate_verification": True,
        "hostname_verification": True,
        "frozen_runtime": bool(getattr(sys, "frozen", False)),
    }

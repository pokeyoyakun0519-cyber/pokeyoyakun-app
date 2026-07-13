from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_FILES = (
    "admin_server/config/admin_config.json",
    "config/license.json",
    "config/password.dat",
    "config/settings.json",
    "config/user_state.json",
    "config/error_throttle.json",
    "config/scheduler_settings.json",
    "config/lotteries.json",
    "config/retail_plugin_state.json",
    "config/email_accounts.json",
    "config/google_client_secret.json",
    "config/online_license_settings.json",
    "config/online_license_key.json",
    "config/online_license_cache.json",
    "config/update_settings.json",
    "config/plugin_distribution_settings.json",
    "config/online_plugin_versions.json",
    "config/sources.json",
    "config/external_notification_settings.json",
    "data/candidates.json",
    "data/products.json",
    "data/official_history.json",
    "data/gmail_result_history.json",
    "logs/app.log",
    "logs/startup.log",
)

RUNTIME_DIRECTORIES = (
    "config/gmail_tokens",
)


def cleanup_runtime_files() -> list[str]:
    removed: list[str] = []

    for relative in RUNTIME_FILES:
        path = PROJECT_ROOT / relative
        if not path.exists():
            continue

        path.unlink()
        removed.append(relative)

    for relative in RUNTIME_DIRECTORIES:
        path = PROJECT_ROOT / relative
        if not path.exists():
            continue

        shutil.rmtree(path)
        removed.append(relative + "/")

    return removed


def main() -> None:
    removed = cleanup_runtime_files()

    if removed:
        print("実行時データを自動削除しました:")
        for relative in removed:
            print("-", relative)
    else:
        print("削除対象の実行時データはありません。")


if __name__ == "__main__":
    main()

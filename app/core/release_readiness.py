from pathlib import Path

from core.external_notification_config import ExternalNotificationConfig
from core.runtime_paths import app_root, install_root
from core.scheduler_config import SchedulerConfig
from core.self_test_manager import SelfTestManager
from core.version import APP_CHANNEL, APP_VERSION


class ReleaseReadiness:
    def __init__(self):
        self.user_root = app_root()
        self.install_root = install_root()

    def run(self) -> list[dict]:
        scheduler = SchedulerConfig().load()
        external = ExternalNotificationConfig().load()
        self_tests = SelfTestManager().run_all()

        checks = [
            {
                "name": "バージョン",
                "success": bool(APP_VERSION),
                "message": f"Ver.{APP_VERSION} / {APP_CHANNEL}",
            },
            {
                "name": "セルフテスト",
                "success": all(
                    bool(item.get("success"))
                    for item in self_tests
                ),
                "message": (
                    f"{sum(bool(item.get('success')) for item in self_tests)}"
                    f"/{len(self_tests)}件 成功"
                ),
            },
            {
                "name": "自動監視設定",
                "success": bool(
                    scheduler.get("check_sources", True)
                    or scheduler.get("check_lotteries", True)
                ),
                "message": (
                    "監視対象あり"
                    if (
                        scheduler.get("check_sources", True)
                        or scheduler.get("check_lotteries", True)
                    )
                    else "監視対象がありません"
                ),
            },
            {
                "name": "外部通知",
                "success": bool(
                    external.get("discord_enabled", False)
                    or external.get("email_enabled", False)
                ),
                "message": (
                    "Discordまたはメール通知が有効"
                    if (
                        external.get("discord_enabled", False)
                        or external.get("email_enabled", False)
                    )
                    else "外部通知は未設定"
                ),
                "warning_only": True,
            },
            {
                "name": "バックアップ保存先",
                "success": (self.user_root / "backup").exists(),
                "message": str(self.user_root / "backup"),
            },
            {
                "name": "ログ保存先",
                "success": (self.user_root / "logs").exists(),
                "message": str(self.user_root / "logs"),
            },
            {
                "name": "インストール先",
                "success": self.install_root.exists(),
                "message": str(self.install_root),
            },
        ]

        return checks

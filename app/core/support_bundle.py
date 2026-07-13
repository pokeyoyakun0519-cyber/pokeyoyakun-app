import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root, install_root
from core.self_test_manager import SelfTestManager
from core.version import APP_CHANNEL, APP_VERSION


class SupportBundle:
    SAFE_CONFIG_FILES = [
        "scheduler_settings.json",
        "behavior_settings.json",
        "update_settings.json",
        "user_state.json",
        "sources.json",
        "lotteries.json",
    ]

    EXCLUDED_NAMES = {
        "license.json",
        "password.dat",
        "external_notification_settings.json",
    }

    def __init__(self):
        self.user_root = app_root()
        self.install_root = install_root()

    def create(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        self_test_results = SelfTestManager().run_all()
        system_info = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "channel": APP_CHANNEL,
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "install_root": str(self.install_root),
            "user_root": str(self.user_root),
        }

        with zipfile.ZipFile(
            destination,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "system_info.json",
                json.dumps(
                    system_info,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            archive.writestr(
                "self_test.json",
                json.dumps(
                    self_test_results,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            logs_dir = self.user_root / "logs"
            if logs_dir.exists():
                log_files = sorted(
                    logs_dir.glob("*.log"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )

                for log_path in log_files[:20]:
                    archive.write(
                        log_path,
                        f"logs/{log_path.name}",
                    )

            config_dir = self.user_root / "config"
            if config_dir.exists():
                for filename in self.SAFE_CONFIG_FILES:
                    path = config_dir / filename
                    if (
                        path.exists()
                        and path.name not in self.EXCLUDED_NAMES
                    ):
                        archive.write(
                            path,
                            f"config/{path.name}",
                        )

            readme = self.install_root / "README.txt"
            if readme.exists():
                archive.write(
                    readme,
                    "README.txt",
                )

        return destination

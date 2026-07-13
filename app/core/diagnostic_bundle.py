import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root
from core.version import APP_CHANNEL, APP_VERSION


class DiagnosticBundle:
    def __init__(self):
        self.root = app_root()

    def create(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        system_info = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "app_channel": APP_CHANNEL,
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
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

            logs_dir = self.root / "logs"
            if logs_dir.exists():
                for log_path in logs_dir.glob("*.log"):
                    archive.write(
                        log_path,
                        f"logs/{log_path.name}",
                    )

            for relative in [
                "config/update_settings.json",
                "config/user_state.json",
            ]:
                path = self.root / relative
                if path.exists():
                    archive.write(path, relative)

        return destination

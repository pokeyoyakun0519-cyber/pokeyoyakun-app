import json
import shutil
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root, install_root, is_frozen


class UserDataMigration:
    """
    旧バージョンでEXEの横に保存していたデータを、
    LocalAppDataの新しい保存先へ移行する。
    """

    FOLDERS = [
        "config",
        "data",
        "logs",
        "backup",
    ]

    def __init__(self):
        self.destination_root = app_root()
        self.source_root = install_root()
        self.marker = (
            self.destination_root
            / "config"
            / "storage_migration.json"
        )

    def run(self) -> list[str]:
        if not is_frozen():
            return []

        if self.marker.exists():
            return []

        messages = []
        copied_files = []

        for folder_name in self.FOLDERS:
            source = self.source_root / folder_name
            destination = self.destination_root / folder_name

            if not source.exists():
                continue

            destination.mkdir(parents=True, exist_ok=True)

            for source_path in source.rglob("*"):
                if not source_path.is_file():
                    continue

                relative = source_path.relative_to(source)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)

                if target.exists():
                    continue

                shutil.copy2(source_path, target)
                copied_files.append(
                    f"{folder_name}/{relative.as_posix()}"
                )

        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(
            json.dumps(
                {
                    "migrated_at": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "source": str(self.source_root),
                    "destination": str(self.destination_root),
                    "copied_files": copied_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if copied_files:
            messages.append(
                f"旧データを{len(copied_files)}件移行"
            )
        else:
            messages.append(
                "新しいユーザーデータ保存先を初期化"
            )

        return messages

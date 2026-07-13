import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root


class BackupManager:
    KEEP_GENERATIONS = 10

    def __init__(self):
        self.root = app_root()
        self.backup_root = self.root / "backup"
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        reason: str = "manual",
        *,
        prune: bool = True,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.backup_root / f"{timestamp}_{reason}"
        destination.mkdir(parents=True, exist_ok=True)

        copied = []

        for folder_name in ["config", "data", "logs"]:
            source = self.root / folder_name
            target = destination / folder_name

            if source.exists():
                shutil.copytree(
                    source,
                    target,
                    dirs_exist_ok=True,
                )
                copied.append(folder_name)

        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "copied_folders": copied,
        }

        (destination / "backup_info.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if prune:
            self.prune_old_backups(self.KEEP_GENERATIONS)

        return destination

    def list_backups(self) -> list[Path]:
        return sorted(
            [
                path
                for path in self.backup_root.iterdir()
                if path.is_dir()
                and path.name != "program"
            ],
            reverse=True,
        )

    def restore_backup(self, backup_path: Path) -> None:
        if not backup_path.exists() or not backup_path.is_dir():
            raise FileNotFoundError("バックアップが見つかりません。")

        for folder_name in ["config", "data", "logs"]:
            source = backup_path / folder_name
            target = self.root / folder_name

            if source.exists():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)

    def delete_backup(self, backup_path: Path) -> None:
        if backup_path.exists() and backup_path.is_dir():
            shutil.rmtree(backup_path)

    def prune_old_backups(self, keep: int = 10) -> list[Path]:
        backups = self.list_backups()
        deleted = []

        for path in backups[max(1, int(keep)):]:
            shutil.rmtree(path)
            deleted.append(path)

        return deleted

    def export_backup_zip(
        self,
        backup_path: Path,
        destination: Path,
    ) -> Path:
        if not backup_path.exists():
            raise FileNotFoundError("バックアップが見つかりません。")

        destination.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(
            destination,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in backup_path.rglob("*"):
                if path.is_file():
                    archive.write(
                        path,
                        Path(backup_path.name) / path.relative_to(backup_path),
                    )

        return destination

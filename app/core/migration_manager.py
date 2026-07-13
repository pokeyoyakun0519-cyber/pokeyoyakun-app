import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from core.runtime_paths import app_root


class MigrationManager:
    """
    設定と商品データをZIPへ書き出し・読み込みする。
    パスワードやライセンス情報は安全のため対象外。
    """

    EXPORT_TARGETS = [
        "config/settings.json",
        "config/user_state.json",
        "config/sources.json",
        "config/lotteries.json",
        "config/site_master.json",
        "config/notifications.json",
        "data/products.json",
        "data/candidates.json",
    ]

    EXCLUDED_FILES = {
        "config/password.dat",
        "config/license.json",
    }

    def __init__(self):
        self.root = app_root()

    def export_package(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        metadata = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 1,
            "targets": [],
        }

        with zipfile.ZipFile(
            destination,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            for relative in self.EXPORT_TARGETS:
                path = self.root / relative

                if not path.exists():
                    continue

                archive.write(path, relative)
                metadata["targets"].append(relative)

            archive.writestr(
                "migration_info.json",
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        return destination

    def inspect_package(self, package_path: Path) -> dict:
        if not zipfile.is_zipfile(package_path):
            raise ValueError("正しいZIPファイルではありません。")

        with zipfile.ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())

            if "migration_info.json" not in names:
                raise ValueError("ポケヨヤ君の移行パックではありません。")

            metadata = json.loads(
                archive.read("migration_info.json").decode("utf-8")
            )

        return metadata

    def import_package(self, package_path: Path) -> list[str]:
        metadata = self.inspect_package(package_path)
        imported = []

        with zipfile.ZipFile(package_path, "r") as archive:
            for relative in metadata.get("targets", []):
                if relative in self.EXCLUDED_FILES:
                    continue

                if relative not in archive.namelist():
                    continue

                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)

                with archive.open(relative) as source:
                    with target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)

                imported.append(relative)

        return imported

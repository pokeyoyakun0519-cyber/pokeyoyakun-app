from pathlib import Path


class MaintenanceManager:
    """tempとlogsの一時ファイルを削除する。"""

    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[2]
        self.targets = [
            self.project_root / "temp",
            self.project_root / "logs",
        ]

    def calculate_size(self) -> int:
        total = 0
        for folder in self.targets:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        pass
        return total

    def clear(self) -> tuple[int, int]:
        removed_files = 0
        removed_bytes = 0

        for folder in self.targets:
            folder.mkdir(parents=True, exist_ok=True)

            for path in sorted(folder.rglob("*"), reverse=True):
                try:
                    if path.is_file():
                        removed_bytes += path.stat().st_size
                        path.unlink()
                        removed_files += 1
                    elif path.is_dir():
                        path.rmdir()
                except OSError:
                    pass

        return removed_files, removed_bytes


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)

    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{size} B"

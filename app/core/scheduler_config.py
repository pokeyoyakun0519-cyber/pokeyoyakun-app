import json
from pathlib import Path

from core.runtime_paths import app_root


DEFAULT_CONFIG = {
    "enabled": False,
    "interval_minutes": 30,
    "check_sources": True,
    "check_lotteries": True,
    "check_candidate_retail": True,
    "check_gmail_results": True,
    "candidate_retail_interval_minutes": 30,
    "last_run": "",
}


class SchedulerConfig:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else app_root()
        self.path = self.root / "config" / "scheduler_settings.json"

    def load(self) -> dict:
        if not self.path.exists():
            self.save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)

        result = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            result.update(data)

        try:
            result["interval_minutes"] = max(
                5,
                min(1440, int(result["interval_minutes"])),
            )
        except (TypeError, ValueError):
            result["interval_minutes"] = 30

        try:
            result[
                "candidate_retail_interval_minutes"
            ] = max(
                15,
                min(
                    1440,
                    int(
                        result[
                            "candidate_retail_interval_minutes"
                        ]
                    ),
                ),
            )
        except (TypeError, ValueError):
            result[
                "candidate_retail_interval_minutes"
            ] = 30

        return result

    def save(self, config: dict) -> None:
        value = dict(DEFAULT_CONFIG)
        value.update(config)
        value["interval_minutes"] = max(
            5,
            min(1440, int(value.get("interval_minutes", 30))),
        )
        value[
            "candidate_retail_interval_minutes"
        ] = max(
            15,
            min(
                1440,
                int(
                    value.get(
                        "candidate_retail_interval_minutes",
                        30,
                    )
                ),
            ),
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

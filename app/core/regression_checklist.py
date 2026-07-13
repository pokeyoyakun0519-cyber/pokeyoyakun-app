import json
from datetime import datetime

from core.runtime_paths import app_root


DEFAULT_ITEMS = [
    {"id": "login_enter", "label": "パスワード欄でEnter認証", "checked": False},
    {"id": "main_launch", "label": "メイン画面が正常に起動", "checked": False},
    {"id": "settings_launch", "label": "設定ソフトが起動", "checked": False},
    {"id": "self_test", "label": "セルフテストが全件成功", "checked": False},
    {"id": "scheduler", "label": "自動監視の今すぐ確認", "checked": False},
    {"id": "discord", "label": "Discordテスト通知", "checked": False},
    {"id": "tray", "label": "タスクトレイ格納と再表示", "checked": False},
    {"id": "support_zip", "label": "サポート診断ZIP作成", "checked": False},
    {"id": "update_page", "label": "アップデート画面表示", "checked": False},
    {"id": "exe_launch", "label": "ポケヨヤ君.exeから起動", "checked": False},
]


class RegressionChecklist:
    def __init__(self):
        self.path = app_root() / "config" / "regression_checklist.json"

    def load(self):
        if not self.path.exists():
            return {
                "updated_at": "",
                "items": [dict(item) for item in DEFAULT_ITEMS],
            }

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "updated_at": "",
                "items": [dict(item) for item in DEFAULT_ITEMS],
            }

        items_by_id = {
            str(item.get("id")): item
            for item in data.get("items", [])
            if isinstance(item, dict)
        }

        items = []
        for default in DEFAULT_ITEMS:
            saved = items_by_id.get(default["id"], {})
            items.append(
                {
                    "id": default["id"],
                    "label": default["label"],
                    "checked": bool(saved.get("checked", False)),
                }
            )

        return {
            "updated_at": str(data.get("updated_at", "")),
            "items": items,
        }

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "items": items,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self):
        self.save([dict(item) for item in DEFAULT_ITEMS])

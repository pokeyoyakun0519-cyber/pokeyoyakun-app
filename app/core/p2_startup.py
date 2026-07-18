from __future__ import annotations

from typing import Any

from core.auto_monitor_manager import AutoMonitorManager
from core.candidate_manager import CandidateManager
from core.site_monitor_sync import SiteMonitorSync


class P2StartupCoordinator:
    """User/Owner共通の安全なローカル同期。失敗しても起動を妨げない。"""

    def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {"site_sync": {}, "auto_monitor": {}}
        try:
            result["site_sync"] = SiteMonitorSync().sync()
        except (OSError, ValueError, TypeError) as error:
            result["site_sync"] = {"error": str(error)}
        try:
            candidates = CandidateManager().load_candidates()
            result["auto_monitor"] = AutoMonitorManager().add_due_candidates(candidates)
        except (OSError, ValueError, TypeError) as error:
            result["auto_monitor"] = {"error": str(error)}
        return result

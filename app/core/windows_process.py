from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_process_kwargs() -> dict[str, Any]:
    """Return portable Popen options that suppress Windows console flashes."""
    if not sys.platform.startswith("win"):
        return {}

    options: dict[str, Any] = {
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    }
    startup_type = getattr(subprocess, "STARTUPINFO", None)
    if startup_type is not None:
        startup = startup_type()
        startup.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startup.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        options["startupinfo"] = startup
    return options


def popen_hidden(command, **kwargs):
    """Launch a background helper without hiding its normal GUI windows."""
    options = hidden_process_kwargs()
    options.update(kwargs)
    return subprocess.Popen(command, **options)

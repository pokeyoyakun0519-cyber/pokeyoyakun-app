from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--owner", action="store_true")
    args = parser.parse_args()
    project = args.project_root.resolve()
    entry = project / "app" / ("owner_main.py" if args.owner else "monitor_main.py")
    with tempfile.TemporaryDirectory(prefix="pokeyoya_profile_") as directory:
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": str(project / "app"),
            "QT_QPA_PLATFORM": "offscreen",
            "POKEYOYA_DATA_ROOT": str(Path(directory) / "data"),
            "LOCALAPPDATA": directory,
        })
        started = time.perf_counter()
        process = subprocess.Popen(
            [sys.executable, str(entry), "--smoke-test"],
            cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        observed = psutil.Process(process.pid)
        peak_rss = 0
        peak_cpu = 0.0
        cpu_seconds = 0.0
        while process.poll() is None:
            try:
                peak_rss = max(peak_rss, observed.memory_info().rss)
                peak_cpu = max(peak_cpu, observed.cpu_percent(interval=0.02))
                cpu = observed.cpu_times()
                cpu_seconds = max(cpu_seconds, cpu.user + cpu.system)
            except psutil.Error:
                break
            if time.perf_counter() - started > 30:
                process.terminate()
                raise SystemExit("startup smoke timeout")
        process.wait(timeout=2)
        print(json.dumps({
            "edition": "owner" if args.owner else "user",
            "exit_code": process.returncode,
            "wall_seconds": round(time.perf_counter() - started, 3),
            "cpu_seconds": round(cpu_seconds, 3),
            "peak_cpu_percent": round(peak_cpu, 1),
            "peak_rss_mib": round(peak_rss / 1024 / 1024, 1),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()

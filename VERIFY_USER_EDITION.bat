@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "from pathlib import Path; r=Path('.'); bad=[p for p in r.rglob('*') if p.is_file() and any(x in str(p).lower() for x in ('admin_server','license_server','plugin_server','update_server','admin_cli','release_check'))]; print('User Edition verification: OK' if not bad else 'NG: '+str(bad)); raise SystemExit(0 if not bad else 1)"
pause

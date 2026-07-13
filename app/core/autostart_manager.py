import platform
import sys
from pathlib import Path
from core.runtime_paths import install_root, is_frozen

APP_RUN_NAME = "PokeyoyaKun"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

class AutoStartError(Exception):
    pass

class AutoStartManager:
    def is_enabled(self):
        if platform.system() != "Windows":
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_RUN_NAME)
            return True
        except OSError:
            return False

    def set_enabled(self, enabled):
        if platform.system() != "Windows":
            raise AutoStartError("Windows以外では自動起動を設定できません。")
        try:
            import winreg
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, APP_RUN_NAME, 0, winreg.REG_SZ,
                        self._build_command(),
                    )
                else:
                    try:
                        winreg.DeleteValue(key, APP_RUN_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as error:
            raise AutoStartError(str(error)) from error

    def _build_command(self):
        if is_frozen():
            return f'"{Path(sys.executable).resolve()}" --minimized'
        pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
        python_exe = pythonw if pythonw.exists() else Path(sys.executable).resolve()
        script = install_root() / "app" / "monitor_main.py"
        return f'"{python_exe}" "{script}" --minimized'

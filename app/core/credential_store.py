import base64
import ctypes
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32


class CredentialStore:
    """
    WindowsのDPAPIを使い、パスワードを現在のWindowsユーザーに紐付けて保護する。
    別PC・別Windowsユーザーでは復号できない。
    """

    def __init__(self):
        project_root = Path(__file__).resolve().parents[2]
        self.password_path = project_root / "config" / "password.dat"

    def save_password(self, password: str) -> None:
        if not password:
            self.delete_password()
            return

        encrypted = self._protect(password.encode("utf-8"))
        self.password_path.parent.mkdir(parents=True, exist_ok=True)
        self.password_path.write_bytes(base64.b64encode(encrypted))

    def load_password(self) -> str:
        if not self.password_path.exists():
            return ""

        try:
            encrypted = base64.b64decode(self.password_path.read_bytes())
            return self._unprotect(encrypted).decode("utf-8")
        except Exception:
            return ""

    def delete_password(self) -> None:
        if self.password_path.exists():
            self.password_path.unlink()

    @staticmethod
    def _to_blob(data: bytes):
        buffer = ctypes.create_string_buffer(data)
        blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def _protect(self, data: bytes) -> bytes:
        input_blob, input_buffer = self._to_blob(data)
        output_blob = DATA_BLOB()

        if not crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError()

        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

    def _unprotect(self, data: bytes) -> bytes:
        input_blob, input_buffer = self._to_blob(data)
        output_blob = DATA_BLOB()

        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError()

        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            kernel32.LocalFree(output_blob.pbData)

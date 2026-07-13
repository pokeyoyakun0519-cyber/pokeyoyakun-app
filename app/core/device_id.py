import hashlib
import platform
import uuid

def get_device_id() -> str:
    parts=[platform.node(), platform.system(), platform.machine(), str(uuid.getnode())]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            machine_guid,_=winreg.QueryValueEx(key,"MachineGuid")
            parts.append(str(machine_guid))
    except Exception:
        pass
    digest=hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()
    return "-".join(digest[i:i+4] for i in range(0,24,4))

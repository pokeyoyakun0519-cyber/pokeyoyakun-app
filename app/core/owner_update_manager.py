from core.owner_update_profile import OWNER_PROFILE
from core.update_manager_base import BaseUpdateManager


def _owner_token() -> str:
    try:
        import keyring
        return keyring.get_password("PokeyoyaKunOwnerUpdate", "owner") or ""
    except Exception:
        return ""


class OwnerUpdateManager(BaseUpdateManager):
    PROFILE = OWNER_PROFILE
    TOKEN_PROVIDER = staticmethod(_owner_token)

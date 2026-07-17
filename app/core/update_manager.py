from core.update_manager_base import BaseUpdateManager, UpdateError
from core.user_update_profile import USER_PROFILE


class UpdateManager(BaseUpdateManager):
    PROFILE = USER_PROFILE

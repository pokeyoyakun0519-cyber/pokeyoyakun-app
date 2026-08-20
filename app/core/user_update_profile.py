import re

from core.release_update import UpdateProfile


USER_REPOSITORY = "pokeyoyakun0519-cyber/pokeyoyakun-app"
USER_PROFILE = UpdateProfile(
    edition_id="user",
    metadata_url=f"https://api.github.com/repos/{USER_REPOSITORY}/releases",
    allowed_hosts=frozenset({
        "api.github.com", "github.com", "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }),
    asset_pattern=re.compile(
        r"^PokeyoyaKun_User_Setup_Ver(?P<version>\d+\.\d+\.\d+)"
        r"(?:_RC(?P<rc>\d+)(?:\.(?P<rc_revision>\d+))?)?\.exe$"
    ),
    updater_name="PokeyoyaKunUpdaterV2.exe",
    application_name="ポケヨヤ君.exe",
    public_github=True,
)

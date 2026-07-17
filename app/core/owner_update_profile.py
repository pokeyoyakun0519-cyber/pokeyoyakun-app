import re

from core.release_update import UpdateProfile


OWNER_PROFILE = UpdateProfile(
    edition_id="owner",
    metadata_url="https://pokeyoyakun.duckdns.org/api/v1/owner/updates/latest",
    allowed_hosts=frozenset({"pokeyoyakun.duckdns.org"}),
    asset_pattern=re.compile(
        r"^PokeyoyaKun_Owner_Setup_Ver(?P<version>\d+\.\d+\.\d+)"
        r"(?:_RC(?P<rc>\d+))?\.exe$"
    ),
    updater_name="PokeyoyaKunOwnerUpdater.exe",
    application_name="PokeyoyaKun_OwnerEdition.exe",
    public_github=False,
    enabled=False,
    disabled_reason="Owner更新サーバーが未構成です。",
)

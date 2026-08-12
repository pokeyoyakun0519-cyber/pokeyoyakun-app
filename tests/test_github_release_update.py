from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from core.release_update import (
    ReleaseUpdateClient, ReleaseVersion,
    StrictRedirectHandler, UpdateError, validate_url,
)
from core.owner_update_profile import OWNER_PROFILE
from core.user_update_profile import USER_PROFILE
from core.owner_update_manager import OwnerUpdateManager
from core.update_manager import UpdateManager


def asset(name: str, host: str = "github.com", size: int = 1234) -> dict:
    return {
        "name": name,
        "browser_download_url": f"https://{host}/download/{name}",
        "size": size,
    }


def release(tag: str, setup_name: str, *, prerelease=False, owner=False) -> dict:
    host = "pokeyoyakun.duckdns.org" if owner else "github.com"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": prerelease,
        "body": "更新内容",
        "assets": [asset(setup_name, host), asset("SHA256SUMS.txt", host)],
    }


class VersionTest(unittest.TestCase):
    def test_rc_and_stable_order(self):
        self.assertLess(ReleaseVersion.parse("v1.25.0-rc3"), ReleaseVersion.parse("v1.25.0"))
        self.assertLess(ReleaseVersion.parse("v1.25.0-rc3"), ReleaseVersion.parse("v1.25.0-rc4"))
        self.assertLess(ReleaseVersion.parse("v1.25.0-rc5"), ReleaseVersion.parse("v1.25.0-rc5.1"))
        self.assertLess(ReleaseVersion.parse("v1.25.0-rc5.1"), ReleaseVersion.parse("v1.25.0-rc5.2"))
        self.assertLess(ReleaseVersion.parse("v1.25.0-rc5.2"), ReleaseVersion.parse("v1.25.0-rc6"))
        self.assertLess(ReleaseVersion.parse("v1.25.0"), ReleaseVersion.parse("v1.25.1-rc1"))

    def test_invalid_tags_are_rejected(self):
        for value in ("1.25.0", "v1.25", "latest", "v1.25.0-beta1"):
            with self.subTest(value=value), self.assertRaises(UpdateError):
                ReleaseVersion.parse(value)


class UserReleaseTest(unittest.TestCase):
    def setUp(self):
        self.client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc3")

    def test_new_release_and_no_downgrade(self):
        payload = [
            release("v1.24.0", "PokeyoyaKun_User_Setup_Ver1.24.0.exe"),
            release("v1.25.0", "PokeyoyaKun_User_Setup_Ver1.25.0.exe"),
        ]
        with patch.object(self.client, "_json", return_value=payload):
            result = self.client.check()
        self.assertTrue(result["available"])
        self.assertEqual(result["tag"], "v1.25.0")

    def test_same_version_has_no_update(self):
        payload = [release("v1.25.0-rc3", "PokeyoyaKun_User_Setup_Ver1.25.0_RC3.exe", prerelease=True)]
        with patch.object(self.client, "_json", return_value=payload):
            self.assertFalse(self.client.check(allow_prerelease=True)["available"])

    def test_rc_channel_receives_prerelease_without_extra_opt_in(self):
        payload = [release("v1.25.0-rc4", "PokeyoyaKun_User_Setup_Ver1.25.0_RC4.exe", prerelease=True)]
        with patch.object(self.client, "_json", return_value=payload):
            self.assertTrue(self.client.check(allow_prerelease=False)["available"])
        with patch.object(self.client, "_json", return_value=payload):
            self.assertTrue(self.client.check(allow_prerelease=True)["available"])

    def test_stable_channel_does_not_receive_prerelease_without_opt_in(self):
        client = ReleaseUpdateClient(USER_PROFILE, "v1.24.0")
        payload = [release(
            "v1.25.0-rc4",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC4.exe",
            prerelease=True,
        )]
        with patch.object(client, "_json", return_value=payload):
            self.assertFalse(client.check(allow_prerelease=False)["available"])
        with patch.object(client, "_json", return_value=payload):
            self.assertTrue(client.check(allow_prerelease=True)["available"])

    def test_rc51_release_and_asset_are_selected(self):
        client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc5")
        payload = [release(
            "v1.25.0-rc5.1",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe",
            prerelease=True,
        )]
        with patch.object(client, "_json", return_value=payload):
            result = client.check(allow_prerelease=True)
        self.assertTrue(result["available"])
        self.assertEqual("v1.25.0-rc5.1", result["tag"])
        self.assertEqual(
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe",
            result["setup_name"],
        )

    def test_rc51_same_version_and_downgrade_are_not_updates(self):
        client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc5.1")
        payload = [
            release(
                "v1.25.0-rc5",
                "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.exe",
                prerelease=True,
            ),
            release(
                "v1.25.0-rc5.1",
                "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe",
                prerelease=True,
            ),
        ]
        with patch.object(client, "_json", return_value=payload):
            self.assertFalse(client.check(allow_prerelease=True)["available"])

    def test_rc51_updates_to_rc52_and_rc6(self):
        for tag, name in (
            ("v1.25.0-rc5.2", "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.2.exe"),
            ("v1.25.0-rc6", "PokeyoyaKun_User_Setup_Ver1.25.0_RC6.exe"),
        ):
            with self.subTest(tag=tag):
                client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc5.1")
                with patch.object(
                    client,
                    "_json",
                    return_value=[release(tag, name, prerelease=True)],
                ):
                    self.assertTrue(client.check(allow_prerelease=True)["available"])

    def test_test_and_finaltest_installers_are_not_selected(self):
        client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc5")
        for name in (
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1_Test.exe",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1_FinalTest.exe",
        ):
            with self.subTest(name=name), patch.object(
                client,
                "_json",
                return_value=[release("v1.25.0-rc5.1", name, prerelease=True)],
            ):
                self.assertFalse(client.check(allow_prerelease=True)["available"])

    def test_missing_installer_or_checksum_is_not_offered(self):
        client = ReleaseUpdateClient(USER_PROFILE, "v1.25.0-rc5")
        installer = release(
            "v1.25.0-rc5.1",
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe",
            prerelease=True,
        )
        no_installer = dict(installer, assets=[asset("SHA256SUMS.txt")])
        no_checksum = dict(installer, assets=[asset(
            "PokeyoyaKun_User_Setup_Ver1.25.0_RC5.1.exe"
        )])
        for payload in (no_installer, no_checksum):
            with self.subTest(assets=payload["assets"]), patch.object(
                client, "_json", return_value=[payload]
            ):
                self.assertFalse(client.check()["available"])

    def test_github_headers_and_release_list_endpoint(self):
        self.assertEqual(
            USER_PROFILE.metadata_url,
            "https://api.github.com/repos/pokeyoyakun0519-cyber/pokeyoyakun-app/releases",
        )
        with patch.object(self.client, "_json", return_value=[]) as request:
            self.client.check()
        headers = request.call_args.args[1]
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")
        self.assertIn("User-Agent", self.client._request_headers(headers))

    def test_owner_or_admin_assets_are_rejected(self):
        values = release("v1.25.0", "PokeyoyaKun_User_Setup_Ver1.25.0.exe")
        values["assets"].append(asset("PokeyoyaKun_Owner_Setup_Ver1.25.0.exe"))
        with patch.object(self.client, "_json", return_value=[values]):
            self.assertFalse(self.client.check()["available"])
        admin = [release("v1.25.0", "PokeyoyaKun_Admin_Setup_Ver1.25.0.exe")]
        with patch.object(self.client, "_json", return_value=admin):
            self.assertFalse(self.client.check()["available"])

    def test_wrong_repository_host_port_and_http_redirect_rejected(self):
        for url in (
            "http://github.com/file.exe",
            "https://evil.example/file.exe",
            "https://github.com:8443/file.exe",
        ):
            with self.subTest(url=url), self.assertRaises(UpdateError):
                validate_url(url, USER_PROFILE.allowed_hosts)
        handler = StrictRedirectHandler(USER_PROFILE.allowed_hosts)
        with self.assertRaises(UpdateError):
            handler.redirect_request(None, None, 302, "", {}, "https://evil.example/file")
        for url in (
            "https://api.github.com/repos/example/releases",
            "https://github.com/example/releases/download/file.exe",
            "https://objects.githubusercontent.com/file.exe",
            "https://release-assets.githubusercontent.com/file.exe",
        ):
            validate_url(url, USER_PROFILE.allowed_hosts)

    def test_sha_match_mismatch_interruption_and_cancel(self):
        content = b"verified setup"
        digest = hashlib.sha256(content).hexdigest()
        info = {
            "setup_name": "PokeyoyaKun_User_Setup_Ver1.25.0.exe",
            "setup_url": "https://github.com/setup.exe",
            "sha_url": "https://github.com/SHA256SUMS.txt",
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / info["setup_name"]
            with (
                patch.object(self.client, "_text", return_value=f"{digest}  {info['setup_name']}\n"),
                patch.object(self.client, "_download_once", side_effect=lambda _u, p, _pr, _c: p.write_bytes(content)),
            ):
                self.assertEqual(self.client.download(info, destination), destination)
            self.assertTrue(destination.with_suffix(".exe.sha256").is_file())
            with (
                patch.object(self.client, "_text", return_value=f"{'0' * 64}  {info['setup_name']}\n"),
                patch.object(self.client, "_download_once", side_effect=lambda _u, p, _pr, _c: p.write_bytes(content)),
                self.assertRaises(UpdateError),
            ):
                self.client.download(info, destination, retries=0)
            cancel = Event(); cancel.set()
            with (
                patch.object(self.client, "_text", return_value=f"{digest}  {info['setup_name']}\n"),
                patch.object(self.client, "_download_once", side_effect=UpdateError("更新ダウンロードをキャンセルしました。")),
            ):
                with self.assertRaises(UpdateError):
                    self.client.download(info, destination, cancel=cancel, retries=0)


class OwnerReleaseTest(unittest.TestCase):
    def test_owner_is_disabled_without_network_and_never_uses_public_github(self):
        client = ReleaseUpdateClient(OWNER_PROFILE, "v1.25.0-rc3")
        with patch.object(client, "_json") as network, self.assertRaisesRegex(
            UpdateError, "Owner更新サーバーが未構成"
        ):
            client.check()
        network.assert_not_called()
        self.assertFalse(OWNER_PROFILE.enabled)
        self.assertFalse(OWNER_PROFILE.public_github)
        self.assertNotIn("github", OWNER_PROFILE.metadata_url)

    def test_owner_accepts_only_private_owner_asset(self):
        enabled_profile = OWNER_PROFILE.__class__(
            **{**OWNER_PROFILE.__dict__, "enabled": True, "disabled_reason": ""}
        )
        client = ReleaseUpdateClient(
            enabled_profile, "v1.25.0-rc3", owner_token_provider=lambda: "credential-manager-token"
        )
        good = release(
            "v1.25.0", "PokeyoyaKun_Owner_Setup_Ver1.25.0.exe", owner=True
        )
        with patch.object(client, "_json", return_value=good):
            self.assertTrue(client.check()["available"])
        user = release(
            "v1.25.0", "PokeyoyaKun_User_Setup_Ver1.25.0.exe", owner=True
        )
        with patch.object(client, "_json", return_value=user):
            self.assertFalse(client.check()["available"])

    def test_owner_enabled_profile_without_token_fails_closed_before_http(self):
        enabled_profile = OWNER_PROFILE.__class__(
            **{**OWNER_PROFILE.__dict__, "enabled": True, "disabled_reason": ""}
        )
        client = ReleaseUpdateClient(enabled_profile, "v1.25.0-rc3")
        with patch("core.release_update.build_https_opener") as opener, self.assertRaisesRegex(
            UpdateError, "認証情報がプロビジョニングされていません"
        ):
            client.check()
        opener.assert_not_called()

    def test_edition_ids_and_updaters_are_build_fixed(self):
        self.assertEqual(UpdateManager.PROFILE.edition_id, "user")
        self.assertEqual(OwnerUpdateManager.PROFILE.edition_id, "owner")
        self.assertNotEqual(USER_PROFILE.updater_name, OWNER_PROFILE.updater_name)
        owner_source = (APP_DIR / "ui" / "owner_main_window.py").read_text(encoding="utf-8")
        user_source = (APP_DIR / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("OwnerUpdateManager", owner_source)
        self.assertNotIn("OwnerUpdateManager", user_source)
        self.assertNotIn("os.environ", (APP_DIR / "core" / "update_manager.py").read_text(encoding="utf-8"))


class PackagingAndGmailTest(unittest.TestCase):
    def test_builds_include_fixed_updaters_and_gmail_hidden_imports(self):
        user = (PROJECT_ROOT / "tools" / "build_user_edition.py").read_text(encoding="utf-8")
        owner = (PROJECT_ROOT / "tools" / "build_owner_edition.py").read_text(encoding="utf-8")
        self.assertIn("user_updater_main.py", user)
        self.assertIn("owner_updater_main.py", owner)
        for module in (
            "google.auth.transport.requests", "google.oauth2.credentials",
            "google_auth_oauthlib.flow", "googleapiclient.discovery",
        ):
            self.assertIn(module, user)
            self.assertIn(module, owner)
        for module in (
            "googleapiclient.errors", "googleapiclient.http",
            "google_auth_httplib2", "urllib3.util.ssl_",
        ):
            self.assertIn(module, user)
        self.assertIn("gmail_requests_compat.py", user)
        self.assertNotIn("FULL_RELEASE_TEST", (APP_DIR / "core" / "gmail_result_service.py").read_text(encoding="utf-8"))

    def test_installers_preserve_data_and_are_edition_specific(self):
        user = (PROJECT_ROOT / "installer" / "PokeyoyaKun_User_Setup.iss").read_text(encoding="utf-8")
        owner = (PROJECT_ROOT / "installer" / "PokeyoyaKun_Owner_Setup.iss").read_text(encoding="utf-8")
        self.assertIn("PokeyoyaKunUpdaterV2.exe", user)
        self.assertIn('Name: "{app}\\PokeyoyaKunUpdater.exe"', user)
        self.assertNotIn("OwnerUpdater", user)
        self.assertIn("PokeyoyaKunOwnerUpdater.exe", owner)
        for text in (user, owner):
            self.assertNotIn('Name: "{app}\\config"', text)
            self.assertNotIn('Name: "{app}\\data"', text)


if __name__ == "__main__":
    unittest.main()

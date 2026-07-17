from __future__ import annotations

import getpass


SERVICE = "PokeyoyaKunOwnerUpdate"
ACCOUNT = "owner"


def main() -> None:
    try:
        import keyring
    except ImportError as error:
        raise SystemExit("keyringをインストールしてください。") from error
    token = getpass.getpass("Owner更新用トークン: ").strip()
    if len(token) < 20:
        raise SystemExit("トークンが短すぎるため保存しません。")
    keyring.set_password(SERVICE, ACCOUNT, token)
    print("Owner更新資格情報をWindows資格情報マネージャーへ保存しました。")


if __name__ == "__main__":
    main()

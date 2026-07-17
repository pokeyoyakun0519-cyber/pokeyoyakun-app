Owner Edition 専用更新経路
============================

Owner Editionは公開GitHub Releasesを参照しません。
固定HTTPS API /api/v1/owner/updates/latest から、認証済みOwner専用メタデータと
PokeyoyaKun_Owner_Setup_*.exeだけを取得します。

認証トークンはEXE、設定JSON、環境変数、コマンドラインへ保存しません。
管理者PCで次を実行し、Windows資格情報マネージャーへプロビジョニングします。

  python tools/provision_owner_update_credential.py

サーバーは短期限・失効可能なOwner専用トークンを発行し、通常版Setupや公開Releaseを
応答へ含めないでください。トークンと専用API応答をログへ出力しないでください。

公開リポジトリへ置けるのはクライアントプロトコルまでです。サーバー側の発行ロジック、
トークン、Owner成果物、非公開メタデータは管理者版リポジトリ／秘密領域で管理します。

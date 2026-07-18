ポケヨヤ君 Owner Edition Ver.1.25.0 RC5
============================================================

開発者専用・配布禁止

この成果物は所有者本人のメインPCでのみ使用する専用ビルドです。
一般利用者への配布、GitHub Releasesへの掲載、第三者への譲渡を禁止します。

Owner Editionは専用エントリーポイントから生成され、ライセンス登録画面、
オンライン／オフラインライセンス検証、端末紐付け、期限確認を実行しません。
この動作はバイナリ生成時に固定され、設定ファイル、環境変数、コマンドライン
から有効化できません。通常のUser Editionは従来どおり認証が必須です。

Feedback・Roadmap等のHTTPS通信は通常版と同じ証明書検証を維持します。
SSL検証を無効化して使用しないでください。

ビルド:
  python tools/build_owner_edition.py

インストーラー:
  Inno Setupで installer/PokeyoyaKun_Owner_Setup.iss をコンパイル

出力先:
  release/owner_dist_rc5/
  release/owner_installer_rc5/

release/github_assets/ へコピーしないでください。

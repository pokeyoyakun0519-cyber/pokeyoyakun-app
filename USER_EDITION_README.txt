【ポケヨヤ君 User Edition Ver.1.24.0 RC】

一般利用者向けの製品版ビルド一式です。
管理サーバー、ライセンス発行CLI、配信サーバー、Release Checkなどの管理・開発機能は含まれていません。

オンラインライセンス認証:
初回起動時に、管理者から案内されたサーバーURLとオンラインキーを入力します。
「接続テスト」でサーバーの /health を確認してから認証できます。
設定は%LOCALAPPDATA%\PokeyoyaKun\configへ保存されます。

作成方法:
1. BUILD_USER_EDITION.batを実行
2. 初回のみ必要ライブラリが自動インストールされます
3. Inno Setup 6が入っていればインストーラーまで自動作成されます

完成ファイル:
release\user_installer\PokeyoyaKun_User_Setup_Ver1.24.0_RC.exe

インストール先:
%LOCALAPPDATA%\Programs\PokeyoyaKun

管理者権限:
不要です。設定・ログ・ライセンス情報は%LOCALAPPDATA%\PokeyoyaKunへ保存されます。

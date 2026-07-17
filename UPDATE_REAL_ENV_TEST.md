# GitHub Releases 実更新試験

通常User Editionの更新元は次の匿名アクセス可能な公開APIに固定する。

`https://api.github.com/repos/pokeyoyakun0519-cyber/pokeyoyakun-app/releases`

## 公開前提の確認

1. サインアウト状態でリポジトリURLとRelease一覧が200になることを確認する。
2. RC Releaseに `PokeyoyaKun_User_Setup_VerX.Y.Z_RCN.exe` と `SHA256SUMS.txt` を添付する。
3. Setup.exeのファイル名とReleaseタグ `vX.Y.Z-rcN` が一致することを確認する。
4. `SHA256SUMS.txt` にSetup.exeのSHA-256が記載されていることを確認する。

## 旧版から新版への実更新

1. 新版より低いバージョンの通常User EditionをWindowsテスト用ユーザーへインストールする。
2. ライセンス、ユーザー設定、受付履歴をテスト用の値で作成する。
3. テスター設定を有効にし、「更新を確認」を実行する。
4. Release一覧から現在版より新しいRCが選ばれることを確認する。
5. 「今すぐ更新」でSetup.exeとSHA256SUMS.txtを取得する。
6. SHA-256一致後に `PokeyoyaKunUpdater.exe` が起動することを確認する。
7. アンインストールせず同一インストール先へ上書きされ、新版が自動起動することを確認する。
8. バージョン、Edition表示、ライセンス、設定、履歴が維持されていることを確認する。
9. 同じ版で再確認し、更新なしになることを確認する。

正式版のテスター設定を無効にした状態ではPre-releaseを選択しない。Owner Editionはこの公開Releaseを参照しない。

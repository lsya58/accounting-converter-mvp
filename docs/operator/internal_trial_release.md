# 内部試用版の作成と配布前チェック（開発者用）

税理士による内部試用版（社内試用のみ・外部配布しない）を作るための手順です。
既存の [windows_release_checklist.md](windows_release_checklist.md) と
[windows_distribution_security.md](../security/windows_distribution_security.md) の方針に従います。

## 0. 前提

- 試用版の目的は「税理士がWindowsアプリで会計判断を行えるかの評価」です。機能追加ではありません。
- JDL本番環境への取込は、試用版では行いません（別途、検証用会社での取込検証が完了してから判断します）。
- 配布物は社内の受け渡しのみです。exeは未署名です（署名は限定外部配布の前に判断）。

## 1. ビルド前

1. 試用版に入れる変更をレビューし、commitする（`build_windows.ps1` は未commitの変更や
   未追跡ファイルがあると停止します）。
2. `git status --short` が空であることを確認する。
3. `git ls-files data/private` が0件であることを確認する。
4. Windows Defenderが有効で、定義が最新であることを確認する。

## 2. ビルド（既存スクリプト）

PowerShellでリポジトリのルートから実行します。

```powershell
Remove-Item -Recurse -Force .venv-build -ErrorAction SilentlyContinue
.\scripts\build_windows.ps1
```

`dist\AccountingConverter\` に exe、`_internal`、`release_manifest.json`、`BUILD_INFO.txt` が作られます。

## 3. 配布物の検査

```powershell
.\scripts\verify_trial_package.ps1
```

このスクリプトは次を確認し、問題があれば止まります（終了コード1）。

| 確認 | 内容 |
|---|---|
| 必須ファイル | exe・`_internal`・`release_manifest.json`・`BUILD_INFO.txt` |
| 顧客データ等の混入 | `data\private`・`companies`・`profiles`・`jdl-account-drafts`・`logs`・`tests` などのフォルダ、CSV/TSV/Excel/PDF/ログ/監査記録がないこと。最上位がexe・`_internal`・来歴ファイルだけであること |
| 依存ファイル | 全ファイルが `release_manifest.json` のSHA-256と一致し、manifestにないファイルがないこと |
| Defender | フォルダ全体とZIPを `MpCmdRun.exe` でスキャン（除外設定・無効化はしない） |
| ハッシュ | ZIPを作り、exeとZIPのSHA-256を `dist\AccountingConverter_InternalTrial.zip.sha256.txt` に記録（ZIPの外） |

Defenderが何か検出した場合は配布を止め、[windows_release_checklist.md](windows_release_checklist.md) の「Defender検出時」に従います。

## 4. 新しいPCでの起動確認

開発用PCではなく、アプリを入れたことのないWindows（別PC、新しいWindowsユーザー、
またはWindowsサンドボックス）で行います。顧客データは使わず、架空データか検証用の会社だけを使います。

1. ZIPを渡す前に、受け取ったZIPの `Get-FileHash -Algorithm SHA256` が記録と一致することを確認する。
2. ZIPを展開し、展開したフォルダをDefenderでスキャンする。
3. `AccountingConverter.exe` をダブルクリックで起動する。ネットワークを切った状態でも起動すること。
   - 「WindowsによってPCが保護されました」（SmartScreen）が出た場合は、未署名のためです。
     受け取る人に警告の無視を求めず、出たことを記録して配布方法を見直します。
4. 画面が明るい配色で表示され、文字が読めること（Windowsがダークモードでも）。
5. 「会社を追加」を開き、キャンセルで閉じられること。
6. `%LOCALAPPDATA%\AccountingConverter` が初回起動前に存在しなかったこと、起動後に作られる場合も
   会社設定が空であることを確認する。
7. アプリを閉じ、展開フォルダの中に新しいファイル（設定・ログ・CSV）が作られていないことを確認する。
8. 表示倍率100%と150%で、確認画面の表とボタンが見切れないこと（可能なら）。

## 5. 記録（試用版ごと）

```text
試用版: AccountingConverter internal trial
Git commit:
exe SHA-256:
ZIP SHA-256:
Defender（フォルダ / ZIP）: 検出なし / 定義バージョン:
新規PC起動確認: 合格 / 実施日・環境:
署名: 未署名（内部試用のみ）
渡した相手・日付:
```

## 6. 試用中の扱い

- 試用者の会社設定・ログ・出力は、試用者PCの `%LOCALAPPDATA%\AccountingConverter` と
  試用者が選んだ保存先にだけ作られます。開発者へ送ってもらう場合も、顧客名・金額・摘要を含むファイルは
  社内の安全な経路だけで受け取り、Git・外部サービスへは入れません。
- 不具合報告は、画面名・操作・表示されたメッセージ・件数で受け取ります。

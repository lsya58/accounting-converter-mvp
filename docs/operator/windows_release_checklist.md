# Windows Release Checklist

## Build前

1. Defenderを有効なままにし、定義を更新する。
2. release対象commitをreviewし、`git status --short`が空であることを確認する。
3. `git rev-parse HEAD`を記録する。
4. 前回の`.venv-build`をHumanが確認後に削除する。
5. customer/private dataがcloneやrelease stagingにないことを確認する。

## Clean build

PowerShellでrepository rootから実行する。

```powershell
Remove-Item -Recurse -Force .venv-build -ErrorAction SilentlyContinue
.\scripts\build_windows.ps1
```

scriptは既存`build/`と`dist/`だけをcleanし、Python 3.12のfresh environmentを作る。worktreeがdirtyなら停止する。

生成後に次を確認する。

```powershell
Get-Content .\dist\AccountingConverter\BUILD_INFO.txt
Get-Content .\dist\AccountingConverter\release_manifest.json
Get-FileHash .\dist\AccountingConverter\AccountingConverter.exe -Algorithm SHA256
```

## Scanとsmoke test

1. `dist/AccountingConverter`全体をDefenderでscanする。
2. 検出された場合は起動・配布せず、検出名、Defender version、時刻、hashを保存する。
3. 検出がない場合だけ、network未接続でも動くこととFirst Release acceptance flowを確認する。
4. Profile未登録、Profile追加、既存出力拒否、正常変換を確認する。
5. output CSVと検証reportにcustomer/private dataが混入していないことを確認する。

Defender無効化、除外設定、警告の無視を受領者へ依頼しない。

## ZIP作成

exeだけでなく`AccountingConverter`folder全体をZIPにする。`_internal`を削除しない。

```powershell
Compress-Archive -Path .\dist\AccountingConverter -DestinationPath .\AccountingConverter_FirstRelease.zip
Get-FileHash .\AccountingConverter_FirstRelease.zip -Algorithm SHA256
```

ZIP hashはrelease notes等のZIP外に記録する。ZIPをもう一度Defenderでscanし、可能ならcleanな別Windows PCで展開・scan・起動確認する。

## Defender検出時

1. 配布を停止する。
2. exeとZIPのSHA-256を記録する。Defenderがfile readをblockする場合はProtection Historyの情報を保存し、無理に復元しない。
3. 同じcommitからfresh environmentで再buildする。
4. manifest、dependency version、hash、検出結果を比較する。
5. source review後、Microsoft公式sample submissionへHumanが提出する。
6. Microsoft判定または原因調査が完了するまで「安全」「誤検知」と断定しない。

## Release gate

- clean tracked worktree
- all automated tests pass
- provenance files present
- exe/ZIP SHA-256 recorded
- Defender scan pass
- clean-PC smoke test pass
- no private JSON/CSV in ZIP
- code signing status explicitly documented

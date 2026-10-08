# Windows配布セキュリティ

## 基本方針

Microsoft Defenderによる検出を、根拠なく誤検知と断定しない。Defenderを無効化したり、未知のバイナリを除外設定へ追加したりしない。難読化、packer変更、binary patch等による検出回避も行わない。

`Trojan:Win32/Wacatac.C!ml`が表示されたartifactは配布停止とし、source、build環境、依存関係、hash、スキャン結果を再確認する。検出名だけでは真偽を確定できない。

## 現在のbuild chain

- Python 3.12のclean virtual environmentを作る。
- `pyproject.toml`の`build` extraからPyInstallerを導入する。
- 既定では`src/accounting_converter/ui_qt/app.py`をentry pointとするPySide6 one-folder buildである。`-TkFallback`指定時だけ従来の`src/accounting_converter/ui/app.py`を使用する。
- custom spec、hook、icon、downloaded binary、post-build binary patchは使用していない。
- Qt版bundleはPython runtime、PySide6、Qt platform plugins/styles/DLL、標準ライブラリとアプリのPython modulesを含む。Tk fallbackはTcl/Tkを含む。
- `_internal`は実行に必要であり、exe単体では配布しない。

`--collect-submodules accounting_converter`はアプリpackage全体を収集する。現時点では確実なpackagingを優先して維持するが、通常のimport解析だけでWindows smoke testを通せるかは将来検証し、不要であることが確認できた場合にのみ削減する。

## Source safety review

2026-10-06時点のtracked sourceには、外部network通信、credential収集、registry操作、startup登録、権限昇格、PowerShell起動、shell command実行、動的download、`eval`/`exec`、code injection、hidden telemetry、self-modifying処理は確認されていない。

正当なfile operationは次のとおり。

- ユーザーが選択したCSV/TXT/JSONのread。
- `%LOCALAPPDATA%/AccountingConverter/profiles`への確認済みProfile保存。
- 出力先と同じdirectoryへのtemporary file作成、検証成功後の`os.replace`。
- 失敗時のtemporary file削除。
- overwriteは明示許可がない限り拒否する。

`os.replace`とtemporary fileはatomic outputのためであり、任意file削除やpersistenceのためではない。Profile削除APIは指定されたProfile IDに対応するstore内JSONだけを対象とする。

## Dependency and reproducibility

runtime dependencyとして`PySide6>=6.8,<7`を宣言する。build dependencyはPyInstallerとそのtransitive dependenciesである。PySide6はQt runtime、plugins、DLLを同梱するためTkinter版よりartifact sizeが増える。network、telemetry、auto update、remote codeは追加しない。

現状の`pyinstaller>=6`は完全な再現性を保証しない。次回のclean Windows buildで実際のversion、dependency一覧、Defender scan、smoke testを記録し、その組合せを確認してからbuild lockを導入する。検証前のversionを推測で固定しない。

build scriptは次を記録する。

- Git commit SHA
- UTC build時刻
- Python version
- PyInstaller version
- build dependency名とversion
- exe SHA-256
- bundle内各fileのpath、size、SHA-256

ZIP作成後のSHA-256はZIP自身の外側に記録する。

## Signing roadmap

Authenticode署名はpublisher identityとartifact integrityを示し、SmartScreen reputation形成に役立つ。一方、署名はmalware scanの代替ではなく、Defender検出が自動的に解消する保証もない。

- 内部Pilot: clean build、hash、Defender scan、来歴記録を必須とする。未署名であることを利用者へ明示する。
- 限定外部配布前: 組織名義のstandard code signing certificateまたは管理型cloud signingを比較する。
- 広範な商用配布前: private key保護、timestamp signing、失効対応を含む署名運用を必須要件として判断する。EVは取得・運用コストと配布規模を比較して選択する。

## Microsoftへの提出

Microsoft Security Intelligenceの公式sample submissionで、Humanがfalse-positive reviewを依頼する。自動提出はしない。提出前に次を準備する。

```text
Product: AccountingConverter First Release
Detection: Trojan:Win32/Wacatac.C!ml
File: AccountingConverter.exe and/or distribution ZIP
Exe SHA-256: <clean rebuild hash>
ZIP SHA-256: <distribution ZIP hash>
Git commit: <40-character commit SHA>
Python: <version>
PyInstaller: <version>
Build dependencies: <release_manifest.jsonを添付>
Distribution context: Local-only accounting CSV converter; no network communication
Observed behavior: <Defender version, scan type, timestamp, exact result>
Expected behavior: Reads user-selected local files and writes a validated local CSV
Contact: <responsible developer/business contact>
Notes: Clean build and source review completed; requesting malware-analysis review
```

個人情報、顧客CSV、ConversionProfile、JDL Contextは提出物へ含めない。

## Packaging considerations

downloadされたZIPにはMark-of-the-Webが付き、展開後fileへ伝播する場合がある。これはWindowsの信頼判断へ影響し得るが、解除を安全性確認の代替にしない。配布者はhashと署名を提示し、受領者は一致を確認してからDefender scanを行う。

MSI/MSIXは将来のinstaller候補であり、install/uninstall、publisher表示、更新方針を整えられる。ただしinstaller化も署名やmalware reviewの代替ではない。First Releaseではone-folder ZIPを維持し、clean buildとprovenanceを先に確立する。

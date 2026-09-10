# JDL EXP-01 Import Candidate Experiment

## 目的

EXP-01は、完全架空の最小1仕訳をJDL import candidate fileとして生成し、JDL実機のテスト会社で手動Import試験するための研究用手順です。

これは正式JDLOutputAdapterではありません。JDL observed evidenceを正式仕様へ昇格しません。成功しても即production化しません。

## 安全条件

- 完全架空データのみ使用する。
- JDL側では必ずテスト会社を使用する。
- Import前にJDL側データをバックアップする。
- 実顧客CSV、実顧客名、実顧客の摘要、実金額を使わない。
- 生成CSVとmanifestは `data/private/experiments/` 配下に置き、Git管理しない。
- JDLエラーログは `data/private/` 配下に保存する。

## 生成内容

- 1仕訳のみ。
- CSV本体はObserved Headerと1 data recordのみ。
- JDL仕様上未確認の独自コメント行や独自metadata行は追加しない。
- metadataはCSVではなくprivacy-safe report/manifestへ記録する。
- statusは `EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT` のまま保持する。

## 事前設定

テンプレートをGit管理外へコピーする。

```bash
mkdir -p data/private/experiments/jdl_import/exp01
cp experiments/jdl_import/exp01_config.template.json \
  data/private/experiments/jdl_import/exp01/config.json
```

`config.json` の30列すべてを確認する。空欄にする列も、JDLテスト会社で空欄として試す意図を明示して空欄にする。

最低限、人間がJDL実機で確認して入力する値:

- 伝番
- 日付
- 借方科目コード
- 借方科目名
- 借方科目正式名称
- 貸方科目コード
- 貸方科目名
- 貸方科目正式名称
- 摘要
- 補助、部門、税区分、税入力方法、取引科目を空欄にしてよいか

## 生成コマンド

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.exp01_candidate \
  --config data/private/experiments/jdl_import/exp01/config.json
```

同名出力がある場合は失敗する。明示的に置換する場合だけ `--overwrite` を付ける。

生成物:

- `data/private/experiments/jdl_import/exp01/EXP-01_jdl_import_candidate.csv`
- `data/private/experiments/jdl_import/exp01/EXP-01_jdl_import_candidate.report.json`
- `data/private/experiments/jdl_import/exp01/EXP-01_manifest.json`

## 自動検証

生成後、少なくとも以下をself-validationする。

- CP932
- BOMなし
- CRLF
- Observed Header一致
- 30 columns
- 1 data record
- identifier flag `1000`
- 金額parse可能
- 借方合計と貸方合計が一致
- 必須mapping値が明示設定済み
- 暗黙defaultなし

privacy-safe reportには科目名、補助名、部門名、摘要、個別金額、raw CSV rowを出さない。

## JDL実機で確認するもの

Import後に以下を確認する。

- エラー有無
- 仕訳件数
- 借貸科目
- 金額
- 摘要
- 補助
- 部門
- 税区分
- 元帳/仕訳日記帳での表示

## 結果記録

Import成功時に記録する証拠:

- 実施日時
- JDL製品名/Version
- テスト会社であること
- Import件数
- 元帳/仕訳日記帳で確認した項目
- fingerprint差分

Import失敗時に保存するもの:

- JDL画面のエラーメッセージ
- JDLログファイル
- 生成CSVのprivacy-safe report

失敗ログはGit管理外の `data/private/` 配下へ保存する。

## production化しない理由

EXP-01は1件の最小候補の実験です。成功しても、JDLの正式CSV仕様、複合仕訳、税区分、補助、部門、月次大量データ、別Version互換性はまだ確定しません。

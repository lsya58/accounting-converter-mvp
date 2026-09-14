# JDL Import Experiments

JDL IBEX 出納帳のofficial documented 30-column CSV仕訳入力schemaと、JDL IBEX 出納帳35.5の実データから確認したobserved-compatible serializationを使い、JDL実機の取込条件を確認するための研究用環境です。

これは正式JDLOutputAdapterではありません。`OFFICIAL_DOCUMENTED` schemaを追加しても、実Import成功までは `VERIFIED_BY_REAL_IMPORT` へ昇格しません。

## EXP-01 import candidate

EXP-01専用の候補生成器は、official documented headerと1 data recordだけを生成します。CSV本体に独自コメント行、独自metadata行、JDL-origin export preambleは追加しません。

設定テンプレート:

```bash
cp experiments/jdl_import/exp01_config.template.json \
  data/private/experiments/jdl_import/exp01/config.json
```

生成:

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.exp01_candidate \
  --config data/private/experiments/jdl_import/exp01/config.json
```

マニュアルで不要時に空欄可と確認できた項目は、configで省略しても空欄列として出力します。ただし、列そのものは必ず30列生成します。科目master確認、補助master確認、会社の消費税処理確認、税項目の組み合わせ確認は明示確認が必要です。実機手順は `docs/experiments/jdl_exp01_import_candidate.md` を参照してください。

## 生成されるもの

`experiments/jdl_import/output/` に以下を生成します。

- `EXP-01_minimal_simple.csv`
- `EXP-02_with_description.csv`
- `EXP-03_with_tax.csv`
- `EXP-04_existing_subaccount.csv`
- `EXP-05_nonexistent_subaccount.csv`
- `EXP-06_observed_multi_record_sequence.csv`
- `experiment_manifest.json`

`output/` はGit管理対象外です。

## 生成方法

設定テンプレートをコピーし、取込先JDLで確認した完全架空の科目・補助科目・税区分を入力します。

```bash
cp experiments/jdl_import/experiment_config.template.json /tmp/jdl_experiment_config.json
```

生成:

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generate_cases \
  --config /tmp/jdl_experiment_config.json
```

設定ファイルの代わりにCLI引数でも指定できます。

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generate_cases \
  --debit-account-code "JDLで確認した借方科目コード" \
  --debit-account-name "JDLで確認した借方科目名" \
  --credit-account-code "JDLで確認した貸方科目コード" \
  --credit-account-name "JDLで確認した貸方科目名"
```

## 安全ルール

- 実顧客情報を入力しない
- 実顧客CSVをこのディレクトリへコピーしない
- JDLエラーログは `data/private/` などGit管理外へ保存する
- `experiment_manifest.json` の `actual_result` は `PASS` / `REJECTED` / `UNTESTED` のいずれかで記録する

`EXP-06_observed_multi_record_sequence` は `1110 -> 1100* -> 1101` のObserved Behavior検証用です。正式複合仕訳仕様とは断定しません。

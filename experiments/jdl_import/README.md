# JDL Import Experiments

JDL IBEX 出納帳のofficial documented 30-column CSV仕訳入力schemaと、JDL IBEX 出納帳35.5の実データから確認したobserved-compatible serializationを使い、JDL実機の取込条件を確認するための研究用環境です。

これは正式JDLOutputAdapterではありません。特定のgenerator-authored `1111` artifactは `EVID-JDL-GENERATOR-1111-001` として限定的に実Import検証済みですが、official schema全体、将来生成物、production capabilityは `VERIFIED_BY_REAL_IMPORT` へ昇格しません。

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

## Generator-authored 1111 candidate

`generator_authored_1111.py` は、成功済みJDL-origin round-tripの次段階として、explicit private configから `1111` の1行伝票を生成します。JDL source rowは生成後のbyte非同一確認にだけ使い、field constructionには使いません。

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generator_authored_1111 \
  --config data/private/experiments/jdl_import/generator_authored_1111/config.json \
  --comparison-source data/private/jdl_self_export_20261002.csv
```

configはofficial 30列と各列のdecision sourceを全件明示する必要があります。出力は `data/private/experiments/jdl_import/generator_authored_1111/` に限定し、同名ファイルがあれば上書きせず停止します。完全架空の特定artifactは実機Importと再Exportまで成功しましたが、新しく生成するartifactの初期statusは引き続き `GENERATOR_AUTHORED_1111_UNTESTED` です。runtimeで補完された再Export表現はgenerator defaultにしません。これはproduction JDLOutputAdapterではありません。

次段階のgenerator-authored `1000` candidateは既存 `exp01_candidate.py` を使用し、private configで1111成功candidateとの差をidentifier flagだけに限定します。statusは `GENERATOR_AUTHORED_1000_UNTESTED` で、実機結果が得られるまで成功扱いしません。

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

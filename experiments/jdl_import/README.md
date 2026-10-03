# JDL Import Experiments

JDL IBEX 出納帳のofficial documented 30-column CSV仕訳入力schemaと、JDL IBEX 出納帳35.5の実データから確認したobserved-compatible serializationを使い、JDL実機の取込条件を確認するための研究用環境です。

これは正式JDLOutputAdapterではありません。特定のgenerator-authored `1111` / `1000` artifactsは、それぞれ限定Evidenceとして実Import検証済みですが、official schema全体、将来生成物、production capabilityは `VERIFIED_BY_REAL_IMPORT` へ昇格しません。

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

generator-authored `1000` candidateも実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-1000-001` として限定的に検証済みです。generatorの将来生成物へ成功statusを継承せず、再Exportでnonblankになった表現もdefault化しません。貸方補助を追加した特定artifactも実機Importに成功しましたが、numeric representationの一般規則には昇格しません。

## Generator-authored 1000 + credit subaccount candidate

`generator_authored_1000_subaccount.py` は、成功済みgenerator-authored `1000` candidateを基準に、貸方補助コード/名称だけを変更する研究用wrapperです。全30列explicit config、取込先masterの親勘定科目context、no fuzzy matching、no automatic replacementを必須とし、成功済みcandidateとの差が2補助列以外にあればblockします。

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generator_authored_1000_subaccount \
  --config data/private/experiments/jdl_import/generator_authored_1000_subaccount/config.json \
  --comparison-source data/private/experiments/jdl_import/generator_authored_1000/jdl_generator_authored_1000_candidate.csv
```

出力は `data/private/experiments/jdl_import/generator_authored_1000_subaccount/` に限定します。この特定artifactは `EVID-JDL-GENERATOR-1000-SUBACCOUNT-001` として実機Import成功とpost-import re-export rawを確認済みです。candidate、target master、re-exportのnumeric representationは別Evidenceとして保持し、この1件からleading-zero規則やgenerator defaultを導出しません。新しいcandidateの初期statusは引き続き `GENERATOR_AUTHORED_1000_SUBACCOUNT_UNTESTED` です。

Import後に訂正したprivate configは、candidate表現とtarget master actual codeを分離した実験履歴であり、再生成用configではありません。generatorは両codeを正規化せず、不一致の新規candidateを引き続きblockします。

## Generator-authored 1000 + debit department candidate

`generator_authored_1000_department.py` は、成功済み補助なし `1000` candidateを基準に、借方部門コード/名称だけを変更する研究用wrapperです。全30列explicit config、部門処理有効、target department master完全一致、no fuzzy matching、no automatic replacementを必須とします。subaccount、税field、貸方部門は空欄を強制します。

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generator_authored_1000_department \
  --config data/private/experiments/jdl_import/generator_authored_1000_department/config.json \
  --comparison-source data/private/experiments/jdl_import/generator_authored_1000/jdl_generator_authored_1000_candidate.csv
```

official `借方部門名称` は4文字上限のため、5文字の登録正式名を切り詰めず、JDL masterで明示確認された短縮名を実験上のCSV表現として使用します。この選択は `GENERATOR_AUTHORED_1000_DEPARTMENT_UNTESTED` の仮説であり、一般仕様にはしません。

実機結果は `INCONCLUSIVE / NOT VERIFIED` です。CSVはImportされましたがdepartment表示を確認できず、初回試行には残存subaccount masterによる別要因errorも含まれました。この結果をdepartment対応やproduction capabilityのEvidenceには使用しません。

## Generator-authored 1111 + both-side department candidate

`generator_authored_1111_department.py` は、手入力した部門付き `1111` 伝票のJDL再Exportで借貸両側のdepartment code/短縮名が観測されたことを根拠に、両側を明示した次の研究用candidateを生成します。観測元rawはaccount/department Evidence確認とbyte非同一検査だけに使用し、data rowの構築元にはしません。

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.generator_authored_1111_department \
  --config data/private/experiments/jdl_import/generator_authored_1111_department/config.json \
  --comparison-source data/private/experiments/jdl_import/generator_authored_1000_department/JDL出納帳-0001-0816-仕訳.csv
```

全30列とdecision source、取込先account/department master、部門処理有効、免税条件をprivate configで明示します。subaccountと税fieldは空欄を強制し、同名出力は上書きしません。新規artifactの初期statusは `GENERATOR_AUTHORED_1111_DEPARTMENT_UNTESTED` です。

今回の特定artifactは実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-1111-DEPARTMENT-001` として限定的に検証済みです。candidateからre-exportへdepartment 4 fieldsは保持されましたが、UI表示差や両側入力の一般規則には昇格しません。片側departmentの `1000` 実験も引き続き `INCONCLUSIVE / NOT VERIFIED` です。

次のtax-inclusive candidateはまだ生成しません。課税・税込の会社設定、JDL UIで選択可能な課区/税区略称、手入力仕訳のraw Exportで税関連fieldの表現が確認できるまで追加Evidence待ちです。次の実験ではsubaccountとdepartmentを外し、税だけを変更変数にします。

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

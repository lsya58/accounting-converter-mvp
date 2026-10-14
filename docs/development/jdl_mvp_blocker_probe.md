# JDL MVP Blocker Probe

このprobeはJDL IBEX出納帳35.5の開発検証専用であり、production変換を有効化しない。実顧客値をcandidateへ転記せず、出力は`data/private/`配下に限定する。

## Privacy-safe plan

Money Forward CSVをローカル解析し、未観測税literalを不可逆hash、借貸side、件数、意味クラスだけで記録する。literal本文はplan、標準出力、tracked documentへ出さない。

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.jdl_mvp_blocker_probe \
  --private-root data/private plan \
  --mf-input data/private/research/moneyforward_real/仕訳帳.csv \
  --output data/private/jdl_mvp_blocker_probes/probe_plan.json
```

未観測税caseは、JDL UIで同じ意味の完全synthetic仕訳を手入力し、JDL自身の30列Exportから課区・税区・税入力方法・消費税・sideを確認するまでcandidate生成を停止する。既存6税区分との同値性をliteralの類似だけで判断しない。

## Trade partner

現在のofficial 30列には取引先専用列が確認されていない。次をHumanが確認する。

1. JDLの仕訳入力画面またはHELPに摘要とは独立した取引先項目があるか確認する。
2. 存在する場合だけ完全syntheticな取引先を入力し、JDL自身から仕訳CSVをExportする。
3. 30列のどこへ保持されたか、またはCSV外のmaster参照かを確認する。
4. 摘要へ自動連結しない。独立保持を確認できなければ`保持不能`のままBLOCKする。

## Multiple descriptions

既存の実Import検証済みcompound candidateをbaseにし、account・amount・flag sequenceを維持して摘要列だけを変えた3候補を作る。

- `description_same`: 全physical rowで同じ摘要
- `description_two_values`: 先頭rowと後続rowで異なる摘要
- `description_three_values`: 3 physical rowsで3種類の摘要

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.jdl_mvp_blocker_probe \
  --private-root data/private generate-descriptions \
  --base-candidate data/private/path/to/compound_candidate.csv \
  --base-manifest data/private/path/to/compound_candidate.manifest.json \
  --output-dir data/private/jdl_mvp_blocker_probes/descriptions \
  --first-date 20261114
```

各candidateを別々にImportし、JDLから再Exportする。比較は日付、flag sequence、account identity、amount、摘要のrow順をexact比較し、統合・消失・変更をPASS扱いしない。

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.jdl_mvp_blocker_probe \
  --private-root data/private compare-description \
  --candidate data/private/jdl_mvp_blocker_probes/descriptions/description_same.csv \
  --manifest data/private/jdl_mvp_blocker_probes/descriptions/description_same.manifest.json \
  --reexport data/private/jdl_mvp_blocker_probes/descriptions/description_same_reexport.csv \
  --result data/private/jdl_mvp_blocker_probes/descriptions/description_same_comparison.json
```

## Safety gates

- candidateとmanifestは上書きしない。
- base candidateのhash、case identity、`NOT_FOR_PRODUCTION`を必須とする。
- CP932、BOMなし、CRLF、official 30列を検証する。
- comparatorは曖昧なrow matchingや推測による正規化を行わない。
- Evidence取得だけではproduction Registry、MF READY、`production_allowed`を変更しない。

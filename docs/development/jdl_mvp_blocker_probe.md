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

既存の実Import検証済みcompound candidateをbaseにし、借方は同じruntimeで補助エラーがなかった科目、貸方3行はbase最終行で補助エラーがなく過去のImport/re-exportでもidentityが保持された科目1つへ統一する。普通預金・当座預金は現在のテスト事業所で補助必須とruntime確認されたため使用しない。補助・税・部門・取引科目fieldは明示的に空欄化し、amount・flag sequenceを維持して摘要列だけを変えた3候補を作る。

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

## Verified multiple-description result

`EVID-JDL-COMPOUND-PER-ROW-DESCRIPTION-ROUNDTRIP-001` records the successful
real-runtime round trip of the three synthetic description cases. Its scope is
limited to exact 1-debit/3-credit journals represented by
`1110 -> 1100 -> 1101`, with no subaccount, tax, department, trade partner,
tag, memo, or invoice fields. Each physical-row description was preserved in
order; the comparator does not accept merging, omission, duplication, or
reordering.

The MF parser retains each source-row description in line metadata. The JDL
output path uses it only under the dedicated Evidence profile. Other compound
shapes, CP932-incompatible values, and descriptions over 32 characters remain
blocked; values are never truncated. In the current private 482-journal audit,
none of the 41 multiple-description journals has this exact 1D3C shape, so all
41 remain blocked pending shape-specific Evidence.

## Remaining large compound shapes

The current private baseline has 11 remaining multiple-description blockers:
five `4D6C`, one `5D7C`, and five `5D8C`. Development-only candidates for
these exact shapes use only synthetic values and runtime-observed accounts that
did not require subaccounts. Tax, subaccount, department, trade-partner,
invoice, tag, and memo fields remain blank. Every physical row has a distinct
description, and only an exact ordered round trip may pass.

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.jdl_mvp_blocker_probe \
  --private-root data/private generate-large-descriptions \
  --output-dir data/private/jdl_mvp_blocker_probes/large_compound_descriptions
```

The generated cases dated `20261122`, `20261123`, and `20261124` passed strict
real-runtime Import/re-export comparison. Their Evidence remains limited to the
exact `4D6C`, `5D7C`, and `5D8C` shapes with no optional fields. Merging,
reordering, missing rows, duplicate rows, changed account identity, changed
amounts, shape mismatch, descriptions over 32 characters, and CP932-incompatible
descriptions remain blocked. Registry and general readiness are unchanged.

## Non-taxable sales probe

`tax_non_taxable_sales_with_subaccount` is an Evidence-gated synthetic `1111`
probe for the exact observed JDL IBEX 35.5 taxable/tax-included Context. It
requires a USER_CONFIRMED credit parent/subaccount mapping and emits the
Human-observed credit-side non-taxable-sales representation. The app-generated
candidate passed strict real-runtime Import/re-export comparison. The mapping is
still USER_CONFIRMED-only and exact-Context scoped; this does not promote
Registry or general production capability.

# JDL Tax Probe

## 目的

Money Forwardの税区分とJDL IBEX出納帳35.5の税fieldを推測で結び付けず、完全syntheticな1仕訳を使って1 categoryずつ実機Evidenceを取得する。probe infrastructureの存在はtax mappingの確認済み化やproduction READYを意味しない。

## Cases

- `tax_sales_10`
- `tax_purchase_10`
- `tax_sales_reduced_8`
- `tax_purchase_reduced_8`
- `tax_non_taxable_purchase`
- `tax_out_of_scope`

JDL側の課区、税区、税入力方法、消費税についてcase別Evidenceがない間、candidate生成は`PROBE_BLOCKED_MISSING_JDL_TAX_EVIDENCE`で停止する。MF literalからJDL codeや略称を推測しない。

`tax_purchase_10`は、Human手入力Exportの`EVID-JDL-TAX-PURCHASE-10-INCLUSIVE-HAND-001`と、app-generated candidateのImport・再Export比較`EVID-JDL-MF-TAX-PURCHASE-10-ROUNDTRIP-001`を持つ。後者はJDL IBEX出納帳35.5、課税・税込、1111、1 debit / 1 credit、補助・部門・取引先なしに限定した`VERIFIED_BY_REAL_IMPORT` Evidenceである。

## Evidence取得手順

1. JDL IBEX出納帳35.5の完全架空テスト事業所をバックアップする。
2. 対象caseだけを表す1 debit / 1 creditのsynthetic仕訳をJDL UIで手入力する。
3. 税以外の補助科目、部門、取引先、tag、memo、invoiceを使用しない。
4. JDLから仕訳CSVを再Exportし、raw fileを`data/private/`へ保存する。
5. 課区、税区、税入力方法、消費税、借貸side、会社の税処理modeを別Evidenceとして確認する。
6. 次のコマンドでprivate result templateを作り、Import/再Export結果を記録する。

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.generate_jdl_probe \
  --case tax_sales_10 \
  --result-template data/private/jdl_probe_results/tax_sales_10_result.json
```

7. Evidence-backed candidate generatorが追加された後だけ、1 caseをImportする。
8. 成功・拒否のどちらでも画面結果と再Exportをprivate領域へ保存する。
9. 結果が不明、再現しない、会社設定依存を分離できない場合はmappingへ昇格しない。

## Result Status

- `UNTESTED`: 未実施
- `PASS`: Importと再ExportをHumanが確認
- `REJECTED`: JDLが拒否。ログをprivate領域へ保存
- `AMBIGUOUS`: 結果またはfield意味を確定できない

結果JSONへ顧客情報、実科目、摘要、日付、金額、raw rowを記録しない。Evidence昇格時も適用製品、version、会社税処理、借貸side、rate、税込/税抜等のscopeを限定する。

## tax_purchase_10の限定scope

- MF source literal: `課税仕入 10%`
- JDL debit課区: 実機再Exportで観測したexact literal
- JDL debit税区: `10%`
- 税入力方法: 今回の税込条件ではcandidate上は空欄
- 消費税: official documented税込ruleに従いcandidate上は空欄
- 貸方側tax fields: 空欄
- 取引科目: 非消費税仕訳として空欄

再Export上の消費税・部門codeのゼロ表現はgenerator defaultへ昇格しない。`ConversionProfile.tax_mappings`には、Human-confirmedなtarget categoryと`jdl_` prefixのEvidence metadataだけを保存し、fuzzy mappingや自動確認は行わない。

生成例:

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.generate_jdl_probe \
  --case tax_purchase_10 \
  --output data/private/jdl_probe/tax_purchase_10.csv \
  --profile data/private/profiles/mf_to_jdl_tax_purchase_10_probe.json \
  --context data/private/jdl_tax_evidence/purchase_10_inclusive/jdl_target_context_taxable.json
```

## 現在のGate

`tax_purchase_10`はapp-generated candidateのJDL Import、再Export、Human手入力Evidenceとのsemantic comparisonまで成功した。ただし、これは1 category・1会社設定・1D1Cのexperimental scopeであり、production routeには未接続である。他の5 tax casesと`simple_with_tax`は引き続きBLOCKする。production RegistryとMF READYは変更しない。

会社設定Tax UIでは、このEvidenceに限り、Money Forward exact observed identityとJDL IBEX出納帳35.5の課税・税込Contextが一致した場合だけ候補を表示する。候補表示だけでは確定せず、ユーザーの「確認しました」操作後にのみ`USER_CONFIRMED`として保存する。他categoryとContext不一致は未解決のまま変換を停止する。これはproduction Registryやroute READYの拡張ではない。

再Export比較では、JDLがcandidateで空欄だったaccount master identityと消費税欄を再Export表現へ補完した。これは比較上の観測分類であり、generator defaultや一般的な正規化規則にはしない。

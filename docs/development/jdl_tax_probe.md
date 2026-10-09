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

## 現在のGate

既存JDL Evidenceには限定的な税込・税抜10%実機結果がある。ただしMF tax categoryとのcross-product mappingは未確認である。6 casesはすべてcandidate生成BLOCKであり、production Registry、MF READY、ConversionProfileのtax mappingを変更しない。

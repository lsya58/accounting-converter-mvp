# Money Forward -> JDL 実Import Probe

> **開発検証専用 / 実務データへの利用禁止**  
> DEVELOPMENT TEST ONLY. NOT FOR CUSTOMER ACCOUNTING USE. DO NOT USE FOR PRODUCTION BOOKS.

このCLIは、観測済みMoney Forward仕訳帳形式から、既存の`ConversionService`とJDL Output Adapterを通して小さな実機検証候補を生成する。GUI、production registry、READY判定は変更しない。

## 前提

- 明示選択したConversion ProfileとJDL Target Contextを必須とする。
- 科目・補助科目は確認済みmasterとの完全一致のみ。曖昧一致や自動置換は行わない。
- 出力は`data/private/`配下のみ。既存CSVまたはmanifestは上書きしない。
- `simple_with_tax`はMF税区分からJDL税項目への実機確認済みmappingがないためBLOCKする。
- 3D1C、2D2C、3D3Cは候補一覧へ公開しない。

## コマンド

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.generate_jdl_probe --list

PYTHONPATH=src python3 -m accounting_converter.tools.generate_jdl_probe \
  --case simple_no_tax \
  --output data/private/jdl_probe/simple_no_tax.csv \
  --profile data/private/profiles/mf_to_jdl.json \
  --context data/private/contexts/jdl_target.json
```

利用可能なcaseは`simple_no_tax`、`simple_two_journals`、`simple_with_tax`（現在BLOCK）、`simple_with_subaccount`（親科目付き確認済みmapping必須）、`compound_1d3c`である。

## Human実機試験

1. JDL IBEX 出納帳35.5で対象の完全架空テスト事業所を開く。
2. 出納帳ファイルを退避する。
3. `データ管理・選択`から`CSV入力`、データ種類`仕訳データ`を開く。
4. 生成したprobe CSVを選ぶ。
5. 画面で集計単位、対象日付範囲、決算整理の扱いを確認する。未確認値を推測しない。
6. Importを実行する。
7. 成功・拒否と、登録件数・重複の有無を記録する。
8. 拒否時はJDLログを`data/private/`へ保存する。
9. 成功時はJDLから再Exportし、`data/private/`へ保存する。
10. manifest、結果、再Exportを照合しEvidence化する。

結果JSONはprivate領域にのみ置き、`probe_case`、`imported`、`JDL_version`、`error_log_present`、`reexport_present`、`notes`を記録する。実科目名、摘要、金額などは共有用資料へ転記しない。

manifestには件数、総額一致、出力hash、context/profileの非可逆hash、Evidence scopeのみを記録し、会計本文を含めない。

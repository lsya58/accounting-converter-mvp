# Accounting Format Compatibility Matrix

**作成日:** 2026年9月2日
**目的:** 会計ソフト・バージョン差に強い変換基盤のための公開情報/観測情報整理

この表は調査メモであり、正式FormatProfileではない。公式情報が確認できない欄はUNKNOWNとし、推測で埋めない。

| Vendor | Product | Format | Import/Export | Known column count | Header | Encoding | Compound support | Evidence | Source URL | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Yayoi | Yayoi Accounting Desktop | 弥生取り込み（インポート）形式（弥生会計05以降） | Import | 25 | UNKNOWN | UNKNOWN | 2000/2111/2110/2100/2101 documented | OFFICIAL_DOCUMENTED | https://support.yayoi-kk.co.jp/faq_Subcontents.html?page_id=18545 | High for documented import layout | 実際に使用する弥生製品/version/実CSVは未確認。正式YayoiInputAdapterではない。 |
| Yayoi | Yayoi Accounting Next | インポートデータ記述形式 | Import | 25 or 27 | UNKNOWN | UNKNOWN | 識別フラグ体系 documented | OFFICIAL_DOCUMENTED | https://support.yayoi-kk.co.jp/subcontents.html?page_id=29611 | Medium | Desktopと同一仕様とは断定しない。Yayoi=常に25列は禁止。 |
| JDL | JDL IBEX 出納帳 | Observed 30-column CSV | Export/Import candidate | 30 observed | Observed header exists | CP932 observed | Identifier flags observed; meaning unresolved | OBSERVED | private real data observation | Medium | JDL IBEX出納帳35.5実データから観測。正常取込成功で検証済みではない。 |
| JDL | JDL IBEX 出納帳net | CSV入出力 | Import/Export | UNKNOWN | 1行目に項目名称が必要と公開情報から確認 | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://www.jdlibex.net/ab-net/renkei-csv.html | Medium | JDL IBEX出納帳35.5のObserved Schemaと同一視しない。 |
| JDL | JDL IBEX 会計 / net | JDL IBEX 会計形式 | Import candidate | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://www.jdlibex.net/ | Low | 詳細CSV仕様は未取得。正式JDL FormatProfileではない。 |
| Money Forward | Money Forward Cloud Accounting | JDL（IBEX 会計）仕訳エクスポート | Export | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://biz.moneyforward.com/support/account/guide/data02/dat01.html | Medium | JDL向けエクスポート機能と検索キー設定が案内されている。内部CSV仕様は推測しない。 |

## 確認済みの差分

- 弥生Desktop公式インポート形式は25項目として公開されている。
- 弥生会計 Next公式情報では25項目または27項目が示されている。
- JDL IBEX出納帳35.5の実データでは30列Observed Schemaが観測された。
- Money Forward Cloud AccountingにはJDL（IBEX 会計）向け仕訳エクスポート機能が案内されているが、内部CSV仕様はこの調査ではUNKNOWN。

## 未確定のまま残す事項

- 実際に使用する弥生製品/バージョン
- 実際の弥生エクスポート形式
- 弥生実CSVのencoding、header、line ending
- 正式YayoiInputAdapter
- 正式YayoiFormatProfile
- 正式JDLOutputAdapter
- 正式JDLFormatProfile
- JDLへの正常取込条件
- Money Forwardが出力するJDL向けファイルの内部Schema

## 運用方針

FormatIdentityの `evidence_level` で `OFFICIAL_DOCUMENTED`、`OBSERVED`、`VERIFIED_BY_REAL_IMPORT`、`INFERRED`、`UNKNOWN` を区別する。`INFERRED` を正式仕様として採用しない。

# Evidence-limited JDLOutputAdapter v0

## Status

`JDLOutputAdapter`と`JDLOutputValidator`は正式`src`配下に実装済み。ただしproduction `AdapterRegistry`には未登録で、YayoiからJDLへのreadinessは`ADAPTER_UNAVAILABLE`のままとする。ConversionService経由で生成したartifactのJDL実機Import確認後にのみ有効化を再評価する。

Target identityはJDL IBEX出納帳35.5 / Journal CSV Input / official documented 30-column schema。schema自体のEvidence levelは`OFFICIAL_DOCUMENTED`から変更しない。adapter behaviorだけを個別の`VERIFIED_BY_REAL_IMPORT` Evidenceへ結び付ける。

## Supported Profiles

| Profile | Evidence | Scope |
| --- | --- | --- |
| `SUPPORTED_1111_BASIC` | `EVID-JDL-GENERATOR-1111-001` | 免税、借貸各1行、補助/部門/税なし |
| `SUPPORTED_1000_BASIC` | `EVID-JDL-GENERATOR-1000-001` | 免税、非伝票、借貸各1行 |
| `SUPPORTED_1000_SUBACCOUNT` | `EVID-JDL-GENERATOR-1000-SUBACCOUNT-001` | 貸方補助1件、親科目contextと出力表現を明示確認 |
| `SUPPORTED_1111_DEPARTMENT` | `EVID-JDL-GENERATOR-1111-DEPARTMENT-001` | 借貸両側へ同じ確認済み部門を明示 |
| `SUPPORTED_1111_TAX_INCLUDED` | `EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001` | 原則課税・個別対応・税込、借方`仕　入`/`10%` |
| `SUPPORTED_1111_TAX_EXCLUDED` | `EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001` | 原則課税・個別対応・税抜、借方`仕　入`/`10%`/`内税`/明示税額。税額は検証済み10%内税・端数切捨てpatternと一致する場合だけ許可 |
| `SUPPORTED_COMPOUND_1D3C` | `EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001` | 免税、1借方対3貸方、exact 3-record sequence |

file-level multi-groupは`SUPPORTED_1111_BASIC`の後に`SUPPORTED_COMPOUND_1D3C`を同日で1件ずつ置くexact combinationだけを`EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001`で許可する。profileは仕訳metadataへ明示し、特徴から推測しない。

## Preflight

- exact product/version/format profile
- accountの確認済みtarget master完全一致
- subaccountのparent account context、target code、output representation確認
- department code/nameのtarget master完全一致
- fuzzy matching、自動置換、暗黙defaultなし
- Evidence profileごとのfeature combination完全一致
- 貸借一致、整数円、field長、日付、CP932 round-trip
- compound shape、順序、同一日付、group balance
- multiple groupのexact allow-list

1件でもErrorがあれば`ConversionService`は`BLOCKED_BY_OUTPUT_PREFLIGHT`を返し、一時出力前に停止する。

## Serialization And Validation

30列順序のsource of truthは`jdl_ibex_cashbook_official_journal_import_spec()`を使用する。出力はCP932、BOMなし、CRLF、preambleなし、first physical row exact header。伝番、未使用tax amount、未使用department code等にre-export由来の`0`を挿入しない。

`JDLOutputValidator`はCP932 byte round-trip、BOM、改行、header、30列、parse-back、Evidence planとのexact row一致、record/journal count、借貸合計を検証する。Verification ReportにはEvidence ID、schema identity、unsupported profile countを追加し、会計本文を含めない。

## Must Block

unknown product/version、未知Evidence profile、未確認master、1000+tax/department、department+tax、8%/売上側/未知tax literal、取引科目、compound内tax/subaccount/department、2借方対1貸方、many-to-many、2-record compound、複数compound、simple+simple、3 groups以上、nonblank伝番、CP932変換不能、truncate/normalize/inferred valueをblockする。

## Remaining Gate

production registry有効化前に、ConversionServiceが生成した完全架空artifactをJDL IBEX出納帳35.5へImportし、件数、group境界、科目、補助、部門、税、貸借、摘要、重複なしを実機確認する。release前にはsimple+simple、compound+compound、10-20 records mixed batchの必要性を再評価する。

# Money Forward Input Adapter v0 Design

## Status

設計のみ。production implementation、AdapterRegistry登録、GUI route、Money Forward -> JDL READY化は行わない。Evidenceは`EVID-MF-JOURNAL-EXPORT-OBSERVED-001`の`OBSERVED` scopeに限定する。

## Proposed Source Identity

- vendor: Money Forward
- product: Money Forward クラウド会計
- version/build: `UNKNOWN`
- route: 仕訳帳CSV Export
- schema: exact observed 19-column header
- encoding/newline: CP932、BOMなし、LF
- evidence level: `OBSERVED`

exact header、19 columns、encoding/newlineをすべて満たした場合だけcandidate identityとする。CSVにversion情報がないため、header一致を全versionのproduction supportへ一般化しない。

## Minimal Architecture

既存InputAdapter contractとYayoi adapterのfail-closed方針を再利用するが、Yayoi識別フラグや25-column parserへ依存させない。

```text
src/accounting_converter/adapters/input/moneyforward/
├── adapter.py          InputAdapter contract、profile identity、record/journal count
├── observed_parser.py  strict CSV parse、row model、grouping、JournalEntry候補生成
└── validator.py        structure/group/date/amount/balance/unsupported field validation
```

独立した`models.py`は、parser内の小さなprivate dataclassで十分な間は追加しない。

## Processing Design

1. bytesをCP932でstrict decode。BOM、非LF newline、decode errorはblock。
2. `csv.reader(strict=True)`でparseし、first rowのexact 19-column headerを検証。
3. 全data rowが19 columnsであることを検証。欠落・余剰・空fileをblock。
4. nonblank`取引No`を読み、同一番号の連続rowsをgroup candidate化。
5. 同じ番号の非連続再出現、group内date不一致をblock。
6. sideごとにaccount/amount pairを検証し、blank sideをlineへ変換しない。
7. dateをexact `YYYY/MM/DD`、amountを正の整数円としてstrict parse。zero/negativeはEvidence取得までblock候補。
8. groupの借方/貸方lineを構築し、total不一致をblock。
9. group内descriptionは0または1 distinct nonblankだけ許可。位置で意味を推測しない。
10. subaccount/department/tax raw literalを対応model fieldへ保持するが、未確認semantic mappingは別validationでblock可能にする。
11. partner/tag/memo/invoice nonblankはlossless traceabilityを保持できる構造を先に確定し、未確定の間はproduction conversionをblock。

## Unsupported / Ambiguous Conditions

- unknown header、列数、encoding、BOM、newline
- malformed CSV
- blank/noncontiguous/ambiguous transaction number
- group内date mismatch
- accountだけ/amountだけのpartial side
- parse不能date/amount、zero/negative amount（未観測）
- unbalanced group
- multiple distinct descriptions in one group
- nonblank invoice
- unknown tax literalを意味変換する要求
- partner/tag/memoをtargetでlosslessに保持できない変換
- Evidence外のcompound shapeを自動推測すること

## Traceability

- `SourceReference.file_name`: source file name
- `SourceReference.row_number`: 各lineのphysical CSV row
- `SourceReference.source_journal_id`: source-local transaction number
- `JournalEntry.id`: file identityとtransaction numberから衝突しないrun-local ID
- `JournalEntry.metadata`: Evidence ID、grouping basis、physical row numbers、raw metadata presenceをprivacy-safeに保持

会計本文をVerification Reportへ出さない。partner/tag/memoのraw valueは通常reportに含めず、presence/countだけを出す。

## Production Gate

実装後も、synthetic fixturesによるUnit testだけでproduction登録しない。追加raw Evidence、source identityの安定性、unsupported field policy、Common Journal Modelのlossless方針、正式ConversionService経路の検証を別gateとする。JDL OutputのEvidence requirementは緩和しない。

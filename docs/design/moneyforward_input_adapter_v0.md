# Money Forward Input Adapter v0 Design

## Status

Input Adapter v0実装済み。production AdapterRegistry登録、GUI route、Money Forward -> JDL READY化は行わない。Evidenceは`EVID-MF-JOURNAL-EXPORT-OBSERVED-001`の`OBSERVED` scopeに限定する。2026-10-08時点でConversionServiceを通るsynthetic E2Eを追加したが、これは配線とfail-closed動作の検証であり、MF -> JDL実機Import Evidenceではない。

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
7. dateをexact `YYYY/MM/DD`、amountを正の整数円としてstrict parse。zero/negativeはUIで登録拒否を観測したが、任意CSVでの意味は未確認なのでv0ではblock。
8. groupの借方/貸方lineを構築し、total不一致をblock。
9. group内descriptionは0または1 distinct nonblankだけ許可。位置で意味を推測しない。
10. subaccount/department/tax/invoice raw literalを対応model fieldへ保持する。tax amountは存在しないため計算しない。
11. 取引先は`JournalLine.metadata["moneyforward_trade_partner"]`へside別に保持する。
12. tag/memoはrow numberとraw valueを`JournalEntry.metadata`へ保持する。`|`を分割せず、摘要へ結合しない。

## Unsupported / Ambiguous Conditions

- unknown header、列数、encoding、BOM、newline
- malformed CSV
- blank/noncontiguous/ambiguous transaction number
- group内date mismatch
- accountだけ/amountだけのpartial side
- parse不能date/amount、zero/negative amount（未観測）
- unbalanced group
- multiple distinct descriptions in one group
- unknown tax literalを意味変換する要求
- partner/tag/memoをtargetでlosslessに扱えない変換経路
- Evidence外のcompound shapeを自動推測すること

## Traceability

- `SourceReference.file_name`: source file name
- `SourceReference.row_number`: 各lineのphysical CSV row
- `SourceReference.source_journal_id`: source-local transaction number
- `JournalEntry.id`: file identityとtransaction numberから衝突しないrun-local ID
- `JournalEntry.metadata`: Evidence ID、grouping basis、physical row numbers、tag/memo raw valuesを保持
- `JournalLine.metadata`: side別trade partner raw valueを保持

会計本文をVerification Reportへ出さない。partner/tag/memoのraw valueは通常reportに含めず、presence/countだけを出す。MappingEngineはdataclass `replace`によりline metadataを保持するが、JDL出力での表現は未定義なので正式E2E前にloss policyを追加する。

## Production Gate

実装済みv0はexact identityを指定した直接利用だけを許可し、production registryへ登録しない。source identityのversion識別、MF -> JDL実機Importを別gateとする。JDL OutputのEvidence requirementは緩和しない。

## Synthetic MF -> JDL E2E

既存`ConversionService`、`MappingEngine`、`ExplicitJdlEvidenceRoutePolicy`、`JdlOutputRuntimeFactory`、`JDLOutputValidator`を再利用し、test-onlyの明示Mapping/target contextで次を確認した。

- tax field空欄・補助/部門/取引先/tag/memo/invoiceなしのsimple 1件
- 同日simple 2件の確認済みJDL `1111 + 1111`構成
- exact 1D3Cの確認済みJDL `1110/1100/1101`構成
- source非変更、count/total、temp output validation、成功後だけのatomic publish

MF raw Evidenceで通常観測した`対象外`をJDL空欄へ変換するcross-product tax mappingは未確認であり、自動変換しない。`3D1C`、`2D2C`、`3D3C`はMF Inputでは解析できてもJDL Output v0 Evidence外なのでblockする。

`MoneyForwardToJdlLossRule`は、JDL Output v0で表現先が確認できない取引先、tag、memo、invoice classificationを値非表示のValidation Errorとしてblockする。source/evidence/grouping metadataは内部traceabilityであり、会計fieldの代替表現としてJDL CSVへ埋め込まない。将来loss acknowledgementを導入する場合も、明示的な利用者確認なしに破棄しない。

このsynthetic E2Eによってproduction Registry、GUI、READY判定は変更しない。実業務source profile、cross-product tax mapping、MF起点JDL実機Importと再Export比較が後続gateである。

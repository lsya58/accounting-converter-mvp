# Money Forward クラウド会計 仕訳帳Export Observed Evidence

## Evidence Identity

- Evidence ID: `EVID-MF-JOURNAL-EXPORT-OBSERVED-001`
- Evidence level: `OBSERVED`
- Product: Money Forward クラウド会計
- Runtime observation date: 2026-10-06
- Route: 仕訳帳からのCSV Export
- Environment: 法人、3月決算、無料トライアル、外部連携なし
- Data: Human-created synthetic test company / manual-entry journals
- Product version/build: CSV内に識別情報がなく`UNKNOWN`

このEvidenceはMoney Forward source CSVの観測であり、JDL Import成功、Money Forward全version、任意の仕訳構造を証明しない。`VERIFIED_BY_REAL_IMPORT`へ昇格せず、MF Input AdapterやMF -> JDL routeをproduction READYにしない。

## Raw Fingerprints

| File | Bytes | SHA-256 | Physical lines | Data rows | Logical journal candidates |
| --- | ---: | --- | ---: | ---: | ---: |
| `mf_01_simple_2journals.csv` | 467 | `76c19edda0a5901b08e2e5371aa41a27618bbdf9344714c1d8ced4a1b00ed17a` | 3 | 2 | 2 |
| `mf_02_compound_1d3c.csv` | 751 | `5afd108dc744028ddf5fc7c28e24d411aedd4b989ddb473c25ada2527d58d80a` | 6 | 5 | 3 |
| `mf_03_subaccount.csv` | 879 | `f7cd33b4a5d69a3ac859dde8bb1fbcc47a14a91c6aa270f2617ca7d08dbb4d58` | 7 | 6 | 4 |
| `mf_04_department.csv` | 1008 | `3a9acb91c85893b45644854a84a7a5d5688a8c752d9a427255c68458e85ffd48` | 8 | 7 | 5 |
| `mf_05_tax10.csv` | 1132 | `80c58691509cf08aabe42f4918cc7e24263f60136407e93716b7bcfd8f8239e2` | 9 | 8 | 6 |
| `mf_06_partner.csv` | 1261 | `0ef79a489cea0705c8c120f6561f273131dd9e79893001c6e961d67d06b449f2` | 10 | 9 | 7 |
| `mf_07_tag_memo.csv` | 1384 | `3b96e340ff06e3ffdbaccdae7dd3446a41239ca447514ca807ea1e041a92822a` | 11 | 10 | 8 |

7ファイルは累積Exportで、前ファイルの全data rowsが次ファイルのprefixとして完全一致した。`mf_02`は複合仕訳の3 rowsを追加し、それ以降は各1 rowを追加している。

## Observed Structure

- CP932 decode: success
- strict Shift_JIS decode: success for these artifacts
- UTF-8 decode: failure
- BOM: none
- line ending: LF only
- final LF: present
- delimiter: comma
- header: first physical/logical row
- column count: header/dataとも全row 19
- quoting: 全19 fieldsをdouble quoteで囲む表現を全rowで観測
- malformed/variable-width rows: 0

CP932とstrict Shift_JISの両方でdecodeできた事実は、全MF Exportがstrict Shift_JISであることを証明しない。v0 identityは今回のbytesを安全に読めるCP932を期待値とし、decode failureをfallbackで隠さない。

## Exact Observed Header

1. `取引No`
2. `取引日`
3. `借方勘定科目`
4. `借方補助科目`
5. `借方部門`
6. `借方取引先`
7. `借方税区分`
8. `借方インボイス`
9. `借方金額(円)`
10. `貸方勘定科目`
11. `貸方補助科目`
12. `貸方部門`
13. `貸方取引先`
14. `貸方税区分`
15. `貸方インボイス`
16. `貸方金額(円)`
17. `摘要`
18. `タグ`
19. `メモ`

順序・表記を含むexact headerをObserved identity候補とする。ただしheader一致だけでMoney Forward全version対応とは判定しない。

## Journal And Field Evidence

### Simple journals

- 取引No `1`、`2`は各1 physical row、別logical journal候補として観測
- 取引日は`YYYY/MM/DD`
- 借貸各1行、整数円、貸借一致
- 借貸税区分に`対象外`

### Compound 1 debit : 3 credit

- 同一取引No `3`が連続3 physical rows
- 3 rowsの取引日は同一
- 借方account/amountは先頭rowだけに存在
- 後続2 rowsの借方side fieldsはblank
- 貸方は3 rowsに分かれ、group totalで貸借一致
- 摘要は今回のgroupでは最後のrowだけに存在

摘要位置を「常に最後」と一般化しない。今回のEvidenceが支持するのは、group内に1個の非空摘要がありlogical journalへ関連付けられることまで。

### Additional populated fields

- 借方補助科目: synthetic subaccount 1件をfield 4で観測。貸方補助は未観測
- 貸方部門: synthetic department 1件をfield 12で観測。借方部門は未観測
- 借方税区分: CSV literal `課税仕入 10%`を1件観測
- 貸方税区分: 同tax journalでは`対象外`
- UI略称`課仕 10%`とCSV literalを同一表現として扱わない
- 借方/貸方インボイス: 全Evidenceでblank。非空 semanticsは未観測
- 貸方取引先: synthetic partner 1件をfield 13で観測。借方取引先は未観測
- タグ/メモ: synthetic値をfields 18/19で同一journalに観測。摘要はblank

## Physical Rows And Logical Journal Candidates

Observed scopeでは、連続する同じ非空`取引No`を1 logical journal candidateとして扱う強いEvidenceがある。v0 grouping案は次に限定する。

1. `取引No`は非空必須。
2. 同じ`取引No`が連続するrowsだけをgroup candidateとする。
3. 同じ番号が離れたblockで再出現した場合はmergeせずBLOCKする。
4. group内の取引日は全row一致必須。
5. 各sideはaccountとamountがともに非空、またはside全体がblankでなければならない。
6. amount/date parse failure、lineなし、group貸借不一致はBLOCKする。
7. group内に複数の異なる非空摘要がある場合は意味を推測せずBLOCKする。

取引Noの採番規則、export範囲変更時の安定性、欠番、再採番、period跨ぎ、任意compound shapeは未確認である。取引Noを会社横断・ファイル横断の永続IDとは扱わず、`file + 取引No`をsource-local traceability key候補とする。

## Common Journal Model Mapping Assessment

| MF field/concept | Common model candidate | Classification | Decision |
| --- | --- | --- | --- |
| 取引日 | `JournalEntry.date` | B: normalization required | exact `YYYY/MM/DD`を`date`へstrict parse |
| 取引No | `SourceReference.source_journal_id` / Entry ID | A + D | source-local identity。永続global IDとはしない |
| 借方/貸方 | `JournalLine.side` | A | populated sideから明示生成 |
| 勘定科目 | `JournalLine.account` | A | source名称を保持。target Mappingは別責務 |
| 補助科目 | `JournalLine.sub_account` | A | blankと非空を区別。親科目contextをMappingで保持 |
| 部門 | `JournalLine.department` | A | side別に保持 |
| 税区分 | `TaxInfo.category` | A/E | raw literal保持は可能。意味mappingは未実装・未解決 |
| インボイス | `TaxInfo.invoice_classification` | C/E | model slotはあるが非空Evidenceなし。v0では非空をBLOCK |
| 金額(円) | `JournalLine.amount` | B | blankを0にせず、非空整数を`Decimal`へstrict parse |
| 摘要 | `JournalEntry.description` | A | group内0または1 distinct nonblankのみ安全 |
| 取引先 | structured source metadata | C + D | 現モデルにline-level fieldなし。安易にdomain拡張しない |
| タグ | `JournalEntry.metadata` candidate | D | lossless target表現がなければ変換BLOCK/明示確認 |
| メモ | `JournalEntry.metadata` candidate | D | 摘要へ自動結合しない |
| tax amount | 対応source fieldなし | E | CSVから算出・推測しない |

取引先をEntry metadataへ平坦化すると借貸sideとphysical rowの関係を失うため、parser内部のstructured source-row metadata候補として設計し、Common Journal Model拡張は複数source formatで必要性を確認してから判断する。

## Unresolved Risks

- product version/buildをCSV単体から識別できない
- 取引Noの欠落、再採番、重複、非連続再出現
- 3 debit : 1 credit、many-to-many、複数摘要の表現
- 借方部門・取引先、貸方補助、両側同時population
- 課税売上、軽減8%、非課税、不課税、免税、税額、税込/税抜
- invoice nonblank、控除割合
- multiple tagsのdelimiter/escaping
- comma、double quote、改行を含む摘要・タグ・メモ
- zero/negative/very large amount
- Export option、期間、並び替えによる構造変化

## Next Human Experiments (Priority Order)

1. 3 debit : 1 creditとmany-to-manyのgrouping/blank-side表現
2. 同じ取引Noの安定性（期間を変えた再Export、欠番・削除後の再Export）
3. 借方部門・借方取引先・貸方補助、および両側同時population
4. group内の摘要入力位置variationと複数行摘要
5. 課税売上10%とCSV tax literal
6. 軽減税率8%、非課税、不課税、免税
7. invoice field nonblankと控除割合
8. 税込/税抜、tax amountのExport上の扱い
9. multiple tagsとcomma/double quote/newlineを含む摘要・タグ・メモ
10. zero/negative/large amountのUI rejectionまたはExport表現


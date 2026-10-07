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
| `仕訳帳_20261006_2021.csv` | 4416 | `2a3470eba1882f56de9c778e9076e0fedfd1c24d6e62d9f80d52167354a8c19f` | 35 | 34 | 27 |
| `仕訳帳_20261006_2035.csv` | 4558 | `504d884e5fe35d49b5f497581372932d1ed91dcfd2b1b2d114355da65e2e442b` | 36 | 35 | 28 |

7ファイルは累積Exportで、前ファイルの全data rowsが次ファイルのprefixとして完全一致した。`mf_02`は複合仕訳の3 rowsを追加し、それ以降は各1 rowを追加している。

追加の同日raw Evidenceとして、元ファイル名を維持した12ファイル（`1908`から`2035`）をprivate領域で再解析した。最大artifactは35 data rows / 28 logical journal candidatesで、19列、CP932、BOMなし、LF、exact header、全field quoteを維持した。全19 artifactsは既存`MoneyForwardInputAdapter v0`でparse成功し、全logical journal candidateが貸借一致した。

`2021`と`2035`で新たにraw確認した範囲は次のとおり。

- `2021`: 3D3C、multiple tagsの`|`表現、`課税売上 (軽)8%`、借貸双方の非`対象外`tax population、large integer amount、comma/double quote escaping
- `2035`: 上記構造の継続とinvoice raw literal `70%控除`
- 両artifactともraw multiline fieldは0。これはExport bytes上の事実であり、UI入力からの正規化規則そのものは証明しない。

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

### Additional grouping observations

- 3 debit : 1 credit、2 debit : 2 creditをprivate rawで再確認した。
- 3 debit : 3 creditを`2021`と`2035`のprivate rawで再確認した。
- v0はshape名をハードコードせず、各physical rowが各side最大1 line、同一非空取引Noが連続し、日付一致・side pair完全・group貸借一致の場合だけgroup化する。
- 金額編集後も取引Noが維持された一方、削除した番号が新規仕訳で再利用されたことをHuman操作で確認した。chronological raw snapshotでは`2021`から`2035`の間に、同一取引Noで内容が変化したcandidateが1件ある。ただしsnapshotだけでは編集と削除後再利用を区別できない。取引Noはfile-local traceabilityであり、永続/global IDではない。

### Additional populated fields

- 借方補助科目: synthetic subaccount 1件をfield 4で観測。貸方補助は未観測
- 貸方部門: synthetic department 1件をfield 12で観測。借方部門は未観測
- 借方税区分: CSV literal `課税仕入 10%`を1件観測
- 貸方税区分: 同tax journalでは`対象外`
- UI略称`課仕 10%`とCSV literalを同一表現として扱わない
- initial raw setでは借方/貸方インボイスはblank。追加Human runtime observationで限定条件下の`70%控除`を確認
- 貸方取引先: synthetic partner 1件をfield 13で観測。借方取引先は未観測
- タグ/メモ: synthetic値をfields 18/19で同一journalに観測。摘要はblank

追加Evidenceでは、借貸双方の補助・部門・取引先が同一physical rowに共存できること、借貸双方の税区分が同時に保持されることを確認した。CSV formal tax literalsとして`課税売上 10%`、`課税仕入 (軽)8%`、`課税売上 (軽)8%`、`非課税仕入`を観測し、`課税売上 (軽)8%`と両側tax populationは`2021` rawでも再確認した。UI略称から推測せずCSV literalをraw categoryとして保持する。

invoiceは、自動入力補完ON、登録番号なしの取引先、課税仕入、観測日付という限定条件でCSV literal `70%控除`をHuman確認し、`2035` rawの借方インボイスfieldでも再確認した。登録番号なしなら常に同値になるとは一般化しない。

multiple tagsは`|`を含む1つのCSV fieldとして`2021` rawで再確認した。comma/double quoteは`1957`以降のrawで標準CSV quotingにより保持された。摘要・メモのUI改行はHuman入力後のExportにraw multilineとして存在しなかったが、正規化規則は未確定でありAdapterでは追加変換しない。large integer amountは`2021` rawで再確認した。UIによるzero/negative拒否はHuman operation evidenceであり、CSV bytesからは証明できないため、全Exportへの不在は断定しない。

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
| インボイス | `TaxInfo.invoice_classification` | A/E | raw literalを保持。日付・取引先等から値を推測しない |
| 金額(円) | `JournalLine.amount` | B | blankを0にせず、非空整数を`Decimal`へstrict parse |
| 摘要 | `JournalEntry.description` | A | group内0または1 distinct nonblankのみ安全 |
| 取引先 | `JournalLine.metadata` | A + D | side別raw value保持。target表現がなければ変換BLOCK |
| タグ | `JournalEntry.metadata` | A + D | row numberとraw field保持。`|`を自動分割しない |
| メモ | `JournalEntry.metadata` | A + D | row numberとraw field保持。摘要へ自動結合しない |
| tax amount | 対応source fieldなし | E | CSVから算出・推測しない |

取引先をEntry metadataへ平坦化すると借貸sideとphysical rowの関係を失うため、parser内部のstructured source-row metadata候補として設計し、Common Journal Model拡張は複数source formatで必要性を確認してから判断する。

## Unresolved Risks

- product version/buildをCSV単体から識別できない
- product version/buildとschema variation
- 取引Noのfile間identity、欠落、非連続再出現
- 複数の異なる非空摘要を持つgroupの意味
- 不課税、免税、独立税額、税込/税抜の意味変換
- invoice値の条件と将来の別literal
- `|`を含むtag名のescaping規則
- newline正規化規則
- zero/negative amountを含む外部生成CSV
- Export option、期間、並び替えによる構造変化

## Private Real-Data Compatibility Audit (2026-10-07)

父親事務所由来のprivate CSV 1件を、値を記録せず構造だけ監査した。このfileはCP932 decode可能、BOMなし、LFという一部のstructural propertyは共有するが、仕訳帳Exportのexact 19-column identityとは異なる。

- physical rows: 51
- preamble candidates: 2 rows
- header candidate: physical row 3、6 columns
- data rows: 48、すべて6 columns
- 19-column仕訳帳header: 不一致
- `MoneyForwardInputAdapter v0`: expected BLOCK
- logical journal count: semantic columns不足のため算出不能
- tax/invoice/compound pattern: 対応fieldがなく評価対象外

この結果はAdapterの対応範囲を広げる根拠ではない。6-column fileを仕訳へ推測変換せず、`INCOMPATIBLE_EXPORT_FORMAT`として停止する。Money Forward内の別Export routeまたはmaster/list系formatの可能性はあるが、画面上のExport route Evidenceなしには正式identityを付与しない。

## Next Human Experiments (Priority Order)

1. product/versionまたはschema revisionを識別できるExport metadata
2. 不課税、免税、税込/税抜、tax amountのExport上の扱い
3. invoiceの別条件・別literalと適用期間境界
4. `|`を含むtag名とnewline正規化規則
5. zero/negative amountを含む外部生成CSVの製品側挙動
6. MF Input -> Mapping -> JDL Outputのloss policyと実機Import E2E

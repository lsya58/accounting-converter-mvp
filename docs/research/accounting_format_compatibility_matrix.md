# Accounting Format Compatibility Matrix

**作成日:** 2026年9月2日
**目的:** 会計ソフト・バージョン差に強い変換基盤のための公開情報/観測情報整理

この表は調査メモであり、正式FormatProfileではない。公式情報が確認できない欄はUNKNOWNとし、推測で埋めない。

| Vendor | Product | Format | Import/Export | Known column count | Header | Encoding | Compound support | Evidence | Source URL | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Yayoi | Yayoi Accounting Desktop | 弥生取り込み（インポート）形式（弥生会計05以降） | Import | 25 | UNKNOWN | UNKNOWN | 2000/2111/2110/2100/2101 documented | OFFICIAL_DOCUMENTED | https://support.yayoi-kk.co.jp/faq_Subcontents.html?page_id=18545 | High for documented import layout | 実際に使用する弥生製品/version/実CSVは未確認。正式YayoiInputAdapterではない。 |
| Yayoi | Yayoi Accounting AE 19 | 弥生インポート形式 direct export | Export evidence | 25 observed | no header observed | CP932 observed | 2000/2111 and 2110/2100/2101 observed | OBSERVED | private raw export observation | Medium for observed 2000/2111 and observed multi-record sequences | 複数の独立単一仕訳、借方/貸方の補助科目・部門ありrecord、1行振替伝票record、複数行振替伝票sequenceで再観測。最小YayoiInputAdapterはこのObserved identityに限定し、万能仕様へ昇格しない。 |
| Yayoi | Yayoi Accounting Next | インポートデータ記述形式 | Import | 25 or 27 | UNKNOWN | UNKNOWN | 識別フラグ体系 documented | OFFICIAL_DOCUMENTED | https://support.yayoi-kk.co.jp/subcontents.html?page_id=29611 | Medium | Desktopと同一仕様とは断定しない。Yayoi=常に25列は禁止。 |
| JDL | JDL IBEX 出納帳 | CSV仕訳データ入力 30項目 | Import target | 30 documented | 1行目に項目名称必須 | UNKNOWN in manual | 1000/1111/1110/1100/1101 documented | OFFICIAL_DOCUMENTED | JDL IBEX 出納帳 操作マニュアル P319-P322/P326-P327 | High for manual pages | CP932/CRLF/BOMなしはobserved evidence。Evidence-limited v0は実装済みだがregistry未登録で、Format全体は実Import未検証。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 single-row candidate | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-001 | High for this exact artifact/path only | explicit configから生成した完全架空1件。免税、科目名称identifier、補助なし、部門なし、税fieldなし。このEvidence単独は他flag、複合、Format全体には適用しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1000 single-row candidate | Import verification | 30 | first row exact official header | CP932 observed | 1000 non-voucher journal only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1000-001 | High for this exact artifact/path only | explicit configから生成した完全架空1件。仕訳帳で確認し、振替伝票には非表示。免税、補助なし、部門なし、税fieldなし。Format全体には適用しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1000 with credit subaccount | Import verification | 30 | first row exact official header | CP932 observed | 1000 non-voucher journal only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1000-SUBACCOUNT-001 | High for this exact artifact/path only | 完全架空1件。candidate補助表現 `0001`、target master code `1`、raw re-export表現 `1` を個別に確認。leading-zero規則やgenerator defaultへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 with department re-export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-DEPARTMENT-HAND-1111-001 | Medium for this exact observation only | UIでは借方側だけに部門指定、raw再Exportでは借貸両側の部門fieldが非空。Import成功Evidenceやgenerator defaultにはしない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 with both-side department | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-DEPARTMENT-001 | High for this exact artifact/path only | 完全架空1件。部門4 fieldを借貸両側へ明示しImport成功、raw再Exportでも4 field保持。片側入力、UI表示差、一般requirednessへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 taxable/tax-included export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-TAX-INCLUSIVE-HAND-1111-001 | Medium for this exact observation only | 課税・原則課税・個別対応方式・税込の限定設定。課区の全角spaceを保持。後続generator Import Evidenceとは別レイヤ。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 taxable/tax-included | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001 | High for this exact artifact/path only | 完全架空1件。raw-confirmedな借方課区/税区1組を明示してImport・再Export成功。U+3000を含む課区表現を保持。他税率、売上側課税、税抜、複数件へ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 taxable/tax-exclusive export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-TAX-EXCLUSIVE-HAND-1111-001 | Medium for this exact observation only | 会社設定の税抜とUI税抜入力を別Evidenceとして保持。raw税入力方法の意味を同一視しない。後続generator Import Evidenceとは別レイヤ。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 taxable/tax-exclusive | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001 | High for this exact artifact/path only | 完全架空1件。raw-confirmedな借方tax表現1組を明示してImport・再Export成功。UI入力方式との意味関係、他税率、売上側、複数件へ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered three-record compound export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1110/1100/1101 exact observed sequence | OBSERVED | EVID-JDL-COMPOUND-HAND-1110-1100-1101-001 | Medium for this exact observation only | 同一伝番・日付、group貸借一致をraw確認。generator-authored compound Import、blank伝番、他shapeは未検証。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored three-record compound | Import verification | 30 | first row exact official header | CP932 observed | 1110/1100/1101 exact sequence | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001 | High for this exact artifact/path only | candidate伝番blankで3 recordsを1伝票へgrouping。re-export伝番`0`はgenerator defaultにせず、複数group・別shape・compound内master/taxは未検証。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored simple + compound multi-group | Import verification | 30 | first row exact official header | CP932 observed | 1111 then 1110/1100/1101 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001 | High for this exact artifact/path only | 同日・candidate伝番blankの4 recordsがexactly 2 vouchersとしてImport。UI伝票番号blankとre-export伝番`0`を分離し、他group組合せやgenerator defaultへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Context-aware simple + simple pair | Import verification | 30 | first row exact official header | CP932 verified for artifact | 1111 then 1111 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001 | High for this exact formal route and pair only | 同日・candidate伝番blankの2 recordsがexactly 2 vouchersとしてImport。60 fieldsのsemantic difference 0。任意件数・順序やtax/subaccount/department付きbatchへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Windows packaged GUI simple pair | Import verification | 30 | first row exact official header | CP932 verified for artifact | 1111 then 1111 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-WINDOWS-GUI-E2E-001 | High for this exact packaged GUI route and pair only | GUIでProfile/Context/input/outputを明示選択し、正式ConversionService経路で生成。exactly 2 vouchers、60 fieldsのsemantic difference 0。scroll/resizeと未対応versionの安全停止も実機確認し、strict scopeだけproduction有効。 |
| JDL | JDL IBEX 出納帳 35.5 | Context-aware fixed mixed batch | Import verification | 30 | first row exact official header | CP932 verified for artifact | fixed 7 simple + 5 exact 1D3C compound journals | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MIXED-BATCH-RUNTIME-001 | High for this exact formal route and fixed batch only | 同日12 journals / 22 recordsがexactly 12 journalsとしてImport。4 boundaryと660 fieldsのsemantic difference 0を確認。任意件数・順序・feature combinationへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | ConversionService output v0 release gate | Import verification | 30 | first row exact official header | CP932 verified for artifact | 1111 then 1110/1100/1101 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-CONVERSION-SERVICE-E2E-001 | High for the formal v0 path and exact allow-list | confirmed ConversionProfile/Mappingからpreflight、serializer、validator、atomic publishを通した4 records。実機でexactly 2 vouchers、再Export120 fieldsのsemantic difference 0。registry context wiringとYayoi起点E2Eは別gate。 |
| JDL | JDL IBEX 出納帳 35.5 | Formal Yayoi AE19 to JDL strict route | Import verification | 30 | first row exact official header | CP932 verified for artifact | 1111 then 1110/1100/1101 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-YAYOI-TO-JDL-E2E-001 | High for this exact formal route and allow-list | Synthetic Yayoi 25-field sourceを正式YayoiInputAdapterから変換。免税、補助/部門/税なし、同日simple 1件 + exact 1D3C compound 1件を実機確認。context-aware wiringは後続Evidenceで別途確認。 |
| JDL | JDL IBEX 出納帳 35.5 | Context-aware formal Yayoi AE19 to JDL route | Import verification | 30 | first row exact official header | CP932 verified for artifact | 1111 then 1110/1100/1101 | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-CONTEXT-AWARE-RUNTIME-E2E-001 | High for this exact runtime wiring and allow-list | ConversionRequest、Registry、JdlOutputRuntimeFactory、validated Contextを経由。4 recordsをexactly 2 vouchersとしてImportし、120 fieldsのsemantic difference 0。production/GUI readinessへは自動昇格しない。 |
| JDL | JDL IBEX 出納帳 35.5 | JDL-origin 1111 preamble-stripped round-trip | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | private fully fictional runtime experiment | High for this exact path only | JDL-origin data rowをbyte-for-byte保持。免税、補助なし、部門なし、税fieldなし。generator outputやFormat全体には適用しない。 |
| JDL | JDL IBEX 出納帳 | Observed 30-column CSV | Export/Import candidate | 30 observed | Observed header exists, sometimes after preamble | CP932 observed | Identifier flags observed; meanings documented separately in manual layer | OBSERVED | private real data observation | Medium | JDL IBEX出納帳35.5実データから観測。JDL-origin round-tripと特定のgenerator-authored 1111/1000以外は正常取込未検証。 |
| JDL | JDL-origin export sample | Observed 30-column CSV | Export evidence | 30 observed | Observed header exists | CP932 observed | Identifier flags observed; meaning unresolved | OBSERVED | private export observation | Medium | Product/versionは未検証。35.5固有Evidenceへ無条件統合しない。Known Good Import Fileとは呼ばない。 |
| JDL | JDL IBEX 出納帳net | CSV入出力 | Import/Export | UNKNOWN | 1行目に項目名称が必要と公開情報から確認 | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://www.jdlibex.net/ab-net/renkei-csv.html | Medium | JDL IBEX出納帳35.5のObserved Schemaと同一視しない。 |
| JDL | JDL IBEX 会計 / net | JDL IBEX 会計形式 | Import candidate | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://www.jdlibex.net/ | Low | 詳細CSV仕様は未取得。正式JDL FormatProfileではない。 |
| Money Forward | Money Forward クラウド会計 | 仕訳帳CSV Export | Input adapter v0 / Export evidence | 19 observed | exact observed headerあり | CP932、BOMなし、LF observed | 同一非空取引Noの連続rows。simple、1D3C、3D1C、2D2C、3D3C observed | OBSERVED | EVID-MF-JOURNAL-EXPORT-OBSERVED-001 | Medium for exact observed identity only | 2026-10-06 runtime。補助、部門、取引先、tax/invoice raw、tag/memoを保持するevidence-limited Input Adapter v0実装済み。version/buildはUNKNOWN。production Registry未登録、MF -> JDL READY/real-import E2E未実施。 |
| Money Forward | Money Forward Cloud Accounting | JDL（IBEX 会計）仕訳エクスポート | Export | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | OFFICIAL_DOCUMENTED | https://biz.moneyforward.com/support/account/guide/data02/dat01.html | Medium | JDL向けエクスポート機能と検索キー設定が案内されている。内部CSV仕様は推測しない。 |

## 確認済みの差分

- 弥生Desktop公式インポート形式は25項目として公開されている。
- 弥生会計AE19 direct exportで、25項目、CP932、CRLF、BOMなし、識別フラグ2000/2111/2110/2100/2101、ヘッダーなし、貸借一致候補をraw bytes/parserで観測した。複数の独立単一仕訳、借方/貸方の補助科目・部門ありrecord、1行振替伝票record、`2110 -> 2100* -> 2101` の複数行振替伝票sequenceでも同じ構造が再観測された。
- 弥生会計 Next公式情報では25項目または27項目が示されている。
- JDL IBEX出納帳35.5の実データでは30列Observed Schemaが観測された。
- JDL IBEX出納帳操作マニュアルP319-P322/P326-P327で、CSV仕訳データ入力の30項目、1行目header requirement、identifier flag meanings、税処理ごとのconditional requirements、error CSV behaviorを確認した。
- Manualの30項目field names/orderと、JDL IBEX出納帳35.5 observed 30-column headerは一致した。JDL-origin `1111` round-tripとgenerator-authored `1111` / `1000` 各1件は、厳密に限定した条件で実Importに成功した。
- バージョン未検証のJDL由来Export sampleでも30列header family、CP932、CRLF、BOMなし、同じ識別フラグ集合が再観測された。ただし35.5固有仕様として統合しない。
- Money Forward クラウド会計の仕訳帳Exportでは、完全架空の段階的7 artifactsから19列exact header、CP932、BOMなし、LF、同一非空取引Noによる1D3C grouping候補、補助/部門/tax/取引先/tag/memo field populationを観測した。これはJDL向けExportとは別routeであり、同一schemaと仮定しない。

## 未確定のまま残す事項

- 実際に使用する弥生製品/バージョン
- 実際の弥生エクスポート形式
- 弥生実CSVのencoding、header、line ending
- すべての弥生製品/バージョンに対応する汎用YayoiInputAdapter
- 正式YayoiFormatProfile
- Evidence-limited JDLOutputAdapter v0のcontext-aware registry pathに対する実機再確認
- YayoiInputAdapterからJDLOutputAdapterまでのtax/subaccount/department付きE2E、任意batch/compound E2E
- 複数条件をカバーした `VERIFIED_BY_REAL_IMPORT` のJDL FormatProfile
- generator-authored補助は特定の貸方補助1件、departmentは借貸両側を明示した特定の1111 1件、税は課税・税込/税抜の借方tax表現各1組を持つ特定の1111各1件、compoundは特定の1 debit : 3 credit / 3-record artifactだけ検証済み。他の補助code/親科目、借方補助、片側/階層department、他税率/売上側課税、別compound shape、複数group・複数件の段階的な正常取込結果。
- JDLの課区・税区略称一覧
- JDL会社設定依存の税処理、伝票行数、入力開始月、日付範囲条件
- Money Forwardが出力するJDL向けファイルの内部Schema

## 運用方針

FormatIdentityの `evidence_level` で `OFFICIAL_DOCUMENTED`、`OBSERVED`、`VERIFIED_BY_REAL_IMPORT`、`INFERRED`、`UNKNOWN` を区別する。`INFERRED` を正式仕様として採用しない。

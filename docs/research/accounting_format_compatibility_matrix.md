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
| JDL | JDL IBEX 出納帳 35.5 | 科目一覧PDF（科目印刷） | Master evidence | 5 pages observed | repeated printed header | PDF text layer | N/A | OBSERVED_PRINTED_MASTER | EVID-JDL-MASTER-001 | Medium for this exact test-company print | 使用中のみ=Noで取得。code付き科目だけをmaster candidateとし、codeなし行を科目・補助へ昇格しない。FULL_MASTER、税mapping、production contextを意味しない。 |
| JDL | JDL IBEX 出納帳 35.5 | 科目一覧PDF explicit subaccount | Master evidence | 5 pages observed | parent marker + explicit 4-digit child code | PDF text layer | N/A | OBSERVED | EVID-JDL-MASTER-SUBACCOUNT-PRINT-001 | Medium for this exact synthetic parent/child | Human入力`1`、UI/PDF表示`0001`を別観測として保持。親marker直下の明示行だけを補助候補にし、leading-zero一般規則やproduction Contextへ昇格しない。 |
| JDL | JDL IBEX 出納帳 35.5 | 科目一覧PDF multiple explicit subaccounts | Master evidence | 5 pages observed | multiple children + parent transition | PDF text layer | N/A | OBSERVED | EVID-JDL-MASTER-SUBACCOUNT-PRINT-002 | Medium for this exact synthetic print | 2親・3補助、同一parentの複数child、parent切替、別parentで同じ4桁codeを観測。parent-scoped read Evidenceのみで、Import/outputや自動Mappingへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | 科目一覧PDF debit/credit parent subaccounts | Master evidence | 5 pages observed | explicit parent + 4-digit child | PDF text layer | N/A | OBSERVED | EVID-JDL-MASTER-SUBACCOUNT-PRINT-003 | Medium for these exact synthetic prints | 3借方child・1貸方childで共通構造と親子借貸一致を観測。parent-scoped read Evidenceのみで、Import code規則やproduction outputへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | 部門情報一覧PDF | Master evidence | 1 page / 1 department observed | printed department row | PDF text layer | N/A | OBSERVED | EVID-JDL-MASTER-DEPARTMENT-PRINT-001 | Medium for this exact synthetic print only | code/name/略名称とoptional設定欄を観測。`OBSERVED_PRINTED_MASTER`であり、FULL master、略名称生成、output representationへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | 部門情報一覧PDF multi-row | Master evidence | 1 page / 2 departments observed | one printed row per department | PDF text layer | N/A | OBSERVED | EVID-JDL-MASTER-DEPARTMENT-PRINT-002 | Medium for this exact synthetic print only | PDF1からPDF2への追加差分と2行連続構造を確認。FULL masterやoutput representationには昇格しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Tax human-export batch | Export observation | 30 | official header after preamble | CP932 observed | 1111 / scoped 1D1C cases | OBSERVED | five scoped Human Evidence IDs | Medium for exact exported tax fields | 売上10%、仕入/売上軽減8%、非課税仕入、対象外をHuman Exportで確認。Import round-trip前のためproduction mapping不可。 |
| JDL | JDL IBEX 出納帳 35.5 | App-generated sales 10% probe | Experimental import candidate | 30 | exact official header first | CP932 generated | 1111 / 1D1C / credit tax | HUMAN_OBSERVED / EVIDENCE_GATED_EXPERIMENTAL | EVID-JDL-TAX-SALES-10-INCLUSIVE-HAND-001 | Low until real Import | 課税・税込exact Context、補助/部門等なしに限定。candidate生成とself-validationのみで、VERIFIED/production READYではない。 |
| JDL | JDL IBEX 出納帳 35.5 | Sales 10% probe with credit subaccount | Experimental import candidate | 30 | exact official header first | CP932 generated | 1111 / 1D1C / credit tax + parent-scoped subaccount | HUMAN_OBSERVED / EVIDENCE_GATED_EXPERIMENTAL | EVID-JDL-SUBACCOUNT-TAX-CREDIT-HAND-001 | Low until real Import | 補助なしcandidateはtarget master前提条件で拒否。確認済み親子mapping付きの別candidateで再試験し、production READYにはしない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 single-row candidate | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-001 | High for this exact artifact/path only | explicit configから生成した完全架空1件。免税、科目名称identifier、補助なし、部門なし、税fieldなし。このEvidence単独は他flag、複合、Format全体には適用しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1000 single-row candidate | Import verification | 30 | first row exact official header | CP932 observed | 1000 non-voucher journal only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1000-001 | High for this exact artifact/path only | explicit configから生成した完全架空1件。仕訳帳で確認し、振替伝票には非表示。免税、補助なし、部門なし、税fieldなし。Format全体には適用しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1000 with credit subaccount | Import verification | 30 | first row exact official header | CP932 observed | 1000 non-voucher journal only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1000-SUBACCOUNT-001 | High for this exact artifact/path only | 完全架空1件。candidate補助表現 `0001`、target master code `1`、raw re-export表現 `1` を個別に確認。leading-zero規則やgenerator defaultへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 with department re-export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-DEPARTMENT-HAND-1111-001 | Medium for this exact observation only | UIでは借方側だけに部門指定、raw再Exportでは借貸両側の部門fieldが非空。Import成功Evidenceやgenerator defaultにはしない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 with both-side department | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-DEPARTMENT-001 | High for this exact artifact/path only | 完全架空1件。部門4 fieldを借貸両側へ明示しImport成功、raw再Exportでも4 field保持。片側入力、UI表示差、一般requirednessへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 taxable/tax-included export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-TAX-INCLUSIVE-HAND-1111-001 | Medium for this exact observation only | 課税・原則課税・個別対応方式・税込の限定設定。課区の全角spaceを保持。後続generator Import Evidenceとは別レイヤ。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 taxable/tax-included | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001 | High for this exact artifact/path only | 完全架空1件。raw-confirmedな借方課区/税区1組を明示してImport・再Export成功。U+3000を含む課区表現を保持。他税率、売上側課税、税抜、複数件へ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 sales 10% with credit subaccount | Import verification | 30 | first row exact official header | CP932 observed | exact 1D1C / credit tax and parent-scoped subaccount | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-SALES-10-SUBACCOUNT-ROUNDTRIP-001 | High for this exact artifact/master only | 課税・税込、貸方売上10%、exact親科目/補助でImport・再Export成功。補助なしや別master、他税区分、一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 reduced purchase 8% with debit subaccount | Import verification | 30 | first row exact official header | CP932 verified for artifact | exact 1D1C / debit reduced purchase 8% and parent-scoped subaccount | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-PURCHASE-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001 | High for this exact artifact/master only | 課税・税込、借方軽減8%、exact親子masterでImport・再Export成功。補助なしcaseはruntime拒否。別master・他税区分・一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 reduced sales 8% with credit subaccount | Import verification | 30 | first row exact official header | CP932 verified for artifact | exact 1D1C / credit reduced sales 8% and parent-scoped subaccount | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-SALES-REDUCED-8-SUBACCOUNT-ROUNDTRIP-001 | High for this exact artifact/master only | 課税・税込、貸方軽減8%、exact親子masterでImport・再Export成功。Human摘要残存値は比較から除外。補助なし、別master、他税区分、一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 non-taxable purchase with debit subaccount | Import verification | 30 | first row exact official header | CP932 verified for artifact | exact 1D1C / debit non-taxable purchase and parent-scoped subaccount | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-NONTAXABLE-PURCHASE-SUBACCOUNT-ROUNDTRIP-001 | High for this exact artifact/master only | 課区あり・税区blankの非課税仕入を対象外と分離。exact親子masterでImport・再Export成功。補助なし、別master、一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 out-of-scope with debit subaccount | Import verification | 30 | first row exact official header | CP932 verified for artifact | exact 1D1C / dedicated OUT_OF_SCOPE semantic identity and parent-scoped subaccount | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001 | High for this exact artifact/master only | Export tax fieldsはblank。専用profile・source mapping・manifestとexact親子masterでImport・再Export成功。通常tax未指定、非課税仕入、一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered 1111 taxable/tax-exclusive export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1111 single-line voucher only | OBSERVED | EVID-JDL-TAX-EXCLUSIVE-HAND-1111-001 | Medium for this exact observation only | 会社設定の税抜とUI税抜入力を別Evidenceとして保持。raw税入力方法の意味を同一視しない。後続generator Import Evidenceとは別レイヤ。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored 1111 taxable/tax-exclusive | Import verification | 30 | first row exact official header | CP932 observed | 1111 single-line voucher only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001 | High for this exact artifact/path only | 完全架空1件。raw-confirmedな借方tax表現1組を明示してImport・再Export成功。UI入力方式との意味関係、他税率、売上側、複数件へ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Hand-entered three-record compound export | Export observation | 30 | header after 3-row preamble | CP932 observed | 1110/1100/1101 exact observed sequence | OBSERVED | EVID-JDL-COMPOUND-HAND-1110-1100-1101-001 | Medium for this exact observation only | 同一伝番・日付、group貸借一致をraw確認。generator-authored compound Import、blank伝番、他shapeは未検証。 |
| JDL | JDL IBEX 出納帳 35.5 | Generator-authored three-record compound | Import verification | 30 | first row exact official header | CP932 observed | 1110/1100/1101 exact sequence | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001 | High for this exact artifact/path only | candidate伝番blankで3 recordsを1伝票へgrouping。re-export伝番`0`はgenerator defaultにせず、複数group・別shape・compound内master/taxは未検証。 |
| JDL | JDL IBEX 出納帳 35.5 | Compound per-row description probes | Import verification | 30 | first row exact official header | CP932 observed | exact 1110/1100/1101 1D3C only | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-COMPOUND-PER-ROW-DESCRIPTION-ROUNDTRIP-001 | High for the three exact synthetic cases only | 同一/2種類/3種類の摘要を各physical rowで順序どおり保持。merge・truncation不可。他compound shape、optional field併用、一般MF routeへ拡張しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Additional compound per-row descriptions | Human input / re-export observation | 30 | official header after preamble | CP932 observed | exact 2D1C, 2D2C, 2D3C shapes | HUMAN_OBSERVED_RUNTIME_REEXPORT | three scoped Evidence IDs | Medium for exact synthetic shapes | 各row摘要、flag順、借貸pairing、amount、orderを確認。app-generated round-tripではなく、他shape・optional field併用・production READYへ一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Non-taxable sales with credit subaccount | Generator import / re-export verification | 30 | first row exact official header; re-export header after preamble | CP932 verified | exact 1111 / 1D1C | VERIFIED_BY_REAL_IMPORT (scoped) | EVID-JDL-MF-TAX-NONTAXABLE-SALES-SUBACCOUNT-ROUNDTRIP-001 | High for exact synthetic Context/account/subaccount only | 貸方non-taxable sales、parent-scoped補助、opposite-side blank、摘要をstrict比較。USER_CONFIRMED必須で一般化しない。 |
| JDL | JDL IBEX 出納帳 35.5 | Large compound per-row descriptions | Generator import / re-export verification | 30 | first row exact official header; re-export header after preamble | CP932 verified | exact 4D6C, 5D7C, 5D8C shapes | VERIFIED_BY_REAL_IMPORT (scoped) | three exact-shape round-trip Evidence IDs | High for exact synthetic shapes only | 行摘要と順序、pairing、金額、flagをstrict比較。optional field併用、別shape、merge/truncate、production READYへ一般化しない。 |
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
| Money Forward | Money Forward クラウド会計 | 仕訳帳CSV Export | Input adapter v0 / Export evidence | 19 observed | exact observed headerあり | CP932、BOMなし、LF observed | 同一非空取引Noの連続rows。simple、1D3C、3D1C、2D2C、3D3C observed | OBSERVED | EVID-MF-JOURNAL-EXPORT-OBSERVED-001 | Medium for exact observed identity only | 補助、部門、取引先、tax/invoice raw、tag/memoを保持するevidence-limited Input Adapter v0実装済み。6税caseの限定single round-tripに加え、単一exact Contextのsynthetic 6件batchをJDL実機へImportし6/6 strict comparison成功。ただし実顧客batch、任意master/件数へ一般化せず、production Registry未登録、MF -> JDL READYではない。 |
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

## JDL-origin master migration pilot candidate (2026-10-19)

### Human attestation

- Humanは、privateなJDL CSVを最終的にJDLへ取り込みたい仕訳データ、privateな科目一覧PDFをその取込先会社のtarget master候補として提供した。
- 同一会社性はHuman attestationであり、ファイル内容から会社identityを推測していない。

### Observed files

- CSV SHA-256: d9e8564ff2ef0e0028d82ac4ff1c62303038aeaeb67bf9e102a367cb784af427
- PDF SHA-256: a7e09a33e95d0ef8b11f106781f9585e57d5b985876c452490288d4bd1ddde03
- CSVはCP932、BOMなし、CRLF、official 30-column header、1271 journal records、1158 logical journals。貸借合計は全1158 journalsで一致した。
- CSVには2657のJDL master-reference diagnostic rowsが混在する。これはそのままのformal Import candidateではない。
- PDFは7 pages、OBSERVED_PRINTED_MASTER、code-bearing enabled accounts 79、code-less excluded rows 298、observed subaccounts 0、account/subaccount conflict 0として現行parserで読み取れた。raw textのcode-bearing account 79、parser 79、Observed Master 79、refresh candidate 79が完全一致し、missing/extraは0。このPDFに対するprinted-master parser completenessは79/79 PASSとする。
- code-less 298行はすべて使用区分`×`であり、identityとなる明示codeがないため意図的に候補から除外する。当座預金が候補に出ないこともこの安全仕様によるもので、parser bugではない。JDL側で使用可能にし、明示code付きの最新PDFを再出力するまで候補化しない。
- CSVのunique account identities 40のうち35はcode + printed name identityがtarget masterとexact一致。5はidentity再確認が必要（same-code/name-change 1、same-name/code-change 1、no exact candidate 3）。ambiguous candidateは0。
- 5 account mismatchesの影響は、same-code/name-changeが1 identity/1 journal、same-name/code-changeが1 identity/3 journals、no-candidateが3 identities/14 journals。no-candidateのうち1 identity/1 journalだけがtargetのcode-less・使用`×`行と名称一致する。これはJDL側で有効化して明示codeを持つPDFを再取得する候補であり、converterでcodeを推測する対象ではない。残る4 identitiesはUSER_CONFIRMED mappingまたはtarget master側の明示的な追加・変更が必要。
- CSVのparent-scoped subaccount identities 4は、親account identity自体は4/4 exactだが、subaccountを持たない観測target masterにexact一致しない。476 physical rows / 476 journalsに影響する。各identityについてtargetに明示作成してpreserveするか、情報損失を理解した上でexplicit parent-only policyとするかHuman確認が必要であり、推測やsilent dropは行わない。
- tax categoryは3種/544 rows。貸方非課税売上の観測literal 8 rowsには限定的な1D1C real-import Evidenceがあるが、任意のJDL-origin shape/contextへの一般化はしない。他の2 literal（535 rowsと1 row）にexact real-import Evidenceはなく、target company/contextでのHuman probeが必要。税率だけで課区の同値性を推測しない。
- 摘要32文字超過は2 rows/2 journals（33文字と35文字）。CP932 encode自体は可能だが、現行JDL output preflightの32文字上限を超えるためBLOCKを維持する。自動truncationは不可で、対応するならHumanが変換後摘要を明示確認する別policy/Evidenceが必要。

### Route and readiness

- File classification: JDL official 30-column family with embedded diagnostic rows; normalization and old-master to new-master mapping are required.
- Route classification: JDL old master -> JDL new master。Money Forward -> JDL workflowへは押し込まない。
- production registryのinput adaptersはMoney ForwardとYayoiだけ。JDL-originにはstrict migration Input Adapterを追加したが、Human mappingとtax Evidenceのgateが未完了のためproduction registryには登録せず、formal outputも有効化しない。
- Formal dry-run: BLOCKED。Import candidate、partial output、Windows buildは生成しない。
- 対応には、diagnostic-row handling、exact 30-column JDL input adapter、USER_CONFIRMED account/subaccount migration、compound grouping preservation、tax/description validation、atomic outputを備えた独立routeが必要。小さなparser緩和としては扱わない。

### Minimum implementation scope

1. strict JDL 30-column Input Adapter: exact header/column count、CP932、BOM、CRLF、calendar/date、amount、flag sequenceを検証し、source bytesを変更しない。
2. diagnostic separation: journal rowsと2,657行のdiagnostic/master-reference rowsを構造的に分離し、不明行が1件でもあれば全体をBLOCKする。diagnosticを黙って通常journalへ変換しない。
3. Common Journal Model conversion: sourceのaccount/subaccount code+name、tax raw semantics、physical-row description、source row/order/flag/group identityをmetadataとしてlosslessに保持する。
4. JDL -> JDL CompanySetting: source/target FormatIdentity、target company context/master fingerprint、USER_CONFIRMED mappingsを会社単位で保存する。既存`expected_source_format_key` / `expected_target_format_key`とprofile/context fingerprintは再利用できる。
5. mapping: 35 exact accountsはidentity validation後に候補化できるがauto-confirmしない。5 mismatchesはHuman確認、4 subaccountsはparent-scoped preserveまたはexplicit parent-onlyをidentityごとに確認する。
6. tax preservation/validation: source tax literalをそのまま保持し、target contextとexact Evidenceが一致するものだけ出力する。未観測2 literalとEvidence scope外shapeはHuman probe終了までBLOCKする。
7. grouping/order/description: `1000/1111/1110/1100/1101`のgroup boundaryとphysical-row orderを保持し、貸借一致をjournalごとに再検証する。摘要は32文字、CP932 losslessを満たす場合だけ出力する。
8. atomic output: 全1158 journalsをpreflightし、1件でも未解決・未対応ならformal CSVを生成しない。成功時のみstrict JDL Output Adapter/Validatorで別pathへpublishし、overwriteしない。

### Human confirmation before implementation

- account mismatch 5 identities: source identityとtarget候補の対応を1件ずつ確認する。code-less・使用`×`と一致する1 identityは、JDL側で使用可能にしてcode付きPDFを再取得するか、別の有効targetへmappingするかを確認する。
- subaccount 4 identities: 各々をtarget JDLに新規作成して保持するか、source補助情報を引き継がないexplicit parent-onlyを許可するかを確認する。作成後は最新PDFでparent-scoped identityを再観測する。
- tax environment: target JDLのproduct/version、課税事業者区分、税込/税抜、課税方式、対応方式をHumanが確認する。未観測2 literalは最小synthetic Import/re-export probeでtarget受入とraw再出力を確認する。
- descriptions: 32文字超過2 journalsをformal migration対象からBLOCKするか、Human確認済みの置換文を使う新policyを必要とするかを確認する。

### Future route model

- `ConversionProfile`はsource/target `FormatIdentity`、`CompanySetting`はsource/target format keyとtarget context fingerprintをすでに分離している。そのため`Source: JDL` / `Target: JDL` / `Target Company: pilot_case_001`のモデルへは拡張可能。
- MVPではJDL input adapter/route registrationと既存CompanySettingのsource label追加に限定し、全面的なvendor selectorやoffice templateは後回しとする。MF固有のtax/optional-field normalizationは再利用せず、共通のmapping、target context、preflight、atomic conversion/output validationだけを再利用する。

### Foundation implementation status

- strict JDL migration Input Adapterはexact 30-column header、CP932、BOMなし、CRLF、official flags、calendar date、integer yen、balance、compound flag sequenceをfail-closedで検証する。production registryには未登録。
- diagnostic/master-reference rowは「30列・先頭fieldが`//`・残り29 fieldsがblank」の観測構造だけをsource diagnostic metadataに分離する。それ以外のunknown rowはBLOCKする。
- CJM metadataにsource account/subaccount code+name、tax scope/category/input method、raw 30 columns、physical row index、flag、voucher、row descriptionを保持する。
- migration preflightはaccount/subaccount USER_CONFIRMED mapping、tax Evidence、32文字、CP932、flags、balance、target context freshnessを一括判定する。実案件1,158 journalsは現在BLOCKで、output journalsは0。
- syntheticの検証済み1D1Cに限り既存JDL serializer/validatorへ接続するroute testを追加。実案件candidateは生成しない。

### Unverified

- Human attestationとfile consistencyは分離し、target JDL companyへのImport成功は未検証。
- PDF自体からJDL application versionを確定していない。現行parserの35.5 contextと同一と推測しない。
- 診断行の構造的分離、未解決mapping、targetに存在しないsubaccount、すべてのobserved compound shapes、未観測tax literal、長い摘要のformal outputは未検証。

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

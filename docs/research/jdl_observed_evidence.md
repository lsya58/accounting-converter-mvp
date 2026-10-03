# JDL Observed Evidence Log

**目的:** JDL CSVに関する実資料の観測結果を、正式仕様と混同しない形で匿名記録する。

この文書は研究ログであり、正式JDL FormatProfileではない。会社名、銀行名、日付、伝番、金額、摘要、個別科目名、個別補助科目名、実CSV行は記録しない。

## Evidence Levels

- `OFFICIAL_DOCUMENTED`: JDL公式マニュアル等で確認したが、生成CSVの実機取込成功では未確認。
- `OBSERVED`: 実ファイルまたは帳票から観測したが、正式仕様または実機取込成功では未確認。
- `VERIFIED_BY_REAL_IMPORT`: 特定のCSV生成経路とデータ条件について、対象JDLへ実際に取り込み、件数、貸借、内容確認まで完了。適用範囲を必ず明記し、Format全体へ一般化しない。

実ファイル・UI・帳票由来のEvidenceは原則 `OBSERVED` とする。実機Import成功を確認した経路だけを限定的に `VERIFIED_BY_REAL_IMPORT` として記録する。マニュアル由来の確認事項は別途 `OFFICIAL_DOCUMENTED` として保持し、限定的な成功だけでJDLOutputAdapterのEvidenceLevelは上げない。

## EVID-JDL-MANUAL-001

- source: JDL IBEX 出納帳 操作マニュアル P312-P327
- evidence level: `OFFICIAL_DOCUMENTED`
- manual footer date: 2024-02-14
- scope:
  - CSV入力条件
  - 仕訳データ30項目
  - 1行目header requirement
  - identifier flag meanings
  - 振替伝票sequence
  - 科目/補助科目identifier alternatives
  - target subaccount master requirement
  - 税処理ごとのconditional requirements
  - import operation and error-file behavior
- separation:
  - JDL IBEX出納帳35.5固有仕様とは断定しない
  - CP932/CRLF/BOMなしはmanual由来ではなくobserved evidenceのまま
  - JDL-origin data rowを保持したround-tripと、特定のgenerator-authored `1111` / `1000` artifactsは別Evidenceで実機成功を確認済み
  - 1件のscoped貸方補助artifactを除き、subaccount、department、tax、compound、Format全体は未検証
  - official schema identityは `VERIFIED_BY_REAL_IMPORT` へ昇格しない
- details: `docs/research/jdl_ibex_csv_manual_evidence.md`

## EVID-JDL-ROUNDTRIP-001

- source: 完全架空テスト事業所でJDL自身が出力した1仕訳CSV
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（下記round-trip経路に限定）
- candidate construction:
  - source exportはCP932、CRLF、BOMなし
  - source exportの先頭3 physical rows、83 bytesのpreambleだけを除去
  - official 30-column headerをfirst physical rowとした
  - headerとdata rowのsuffixはsource exportとbyte-for-byte一致
  - field value、quoting、encoding、newlineは変更していない
- runtime result:
  - `データ管理・選択 -> CSV入力 -> 仕訳データ` からImport
  - JDLが1件のデータとして認識
  - CSV変換終了messageを確認
  - 1伝票だけが登録され、重複なし
  - date、debit/credit account、debit/credit amount、description、balanceが元の架空仕訳と一致
- verified scope:
  - JDL-origin data rowのsame-runtime round-trip
  - identifier flag `1111` の1行伝票
  - 免税会社
  - 補助科目なし
  - 部門なし
  - 税関連fieldなし
  - observed export preamble除去とfirst-row official header requirement
- not verified:
  - generator-authored field values
  - identifier flag `1000`
  - compound voucher sequence
  - subaccount、department
  - taxable/tax-included、taxable/tax-excluded
  - tax code abbreviations、transaction account
  - YayoiからJDLへのend-to-end conversion
- separation:
  - official documented schemaは引き続き `OFFICIAL_DOCUMENTED`
  - production JDLOutputAdapterは未登録
  - YayoiからJDLへのproduction readinessは変更しない

## EVID-JDL-GENERATOR-1111-001

- source: official/manual、target master確認、explicit private configだけから生成した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと条件に限定）
- candidate structure:
  - CP932-compatible、CRLF、BOMなし
  - first physical rowはofficial 30-column header
  - preambleなし、30-column data rowが1件
  - identifier flag `1111`
  - JDL-origin data rowを構築元に使用していない
- runtime result:
  - JDLが1件として認識し、CSV変換終了を表示
  - 1伝票、重複なし、貸借一致を目視確認
  - date、account identity、debit/credit amount、descriptionを目視確認
  - Import後のJDL再Exportを取得
- privacy-safe raw comparison:
  - candidateから再Exportへ21 fieldsが入力表現のまま保持された
  - candidateでblankだった9 fieldsが再Exportではnonblank representationになった
  - 9 fieldsは伝番、借方/貸方の科目code、正式名称、消費税、部門code
  - 最初のJDL手入力reference exportと再Exportは29/30 fieldsが一致し、差分fieldは伝番だけ
- interpretation:
  - account名称だけをidentifierとして使う限定経路のImport成功を確認した
  - blankからnonblankへの変化はJDLの再Export表現としてのみ記録する
  - JDL内部保存値、一般的な補完規則、generator defaultとは断定しない
- not verified:
  - identifier flag `1000`
  - compound `1110/1100/1101`
  - subaccount、department
  - taxable/tax-included、taxable/tax-excluded
  - tax abbreviations、transaction account
  - multiple records、large data sets、other products/versions
  - YayoiからJDLへのend-to-end conversion
  - production JDLOutputAdapter
- separation:
  - official documented schema全体は `OFFICIAL_DOCUMENTED` のまま
  - production JDLOutputAdapterは未登録
  - YayoiからJDLへのproduction readinessは変更しない

## EVID-JDL-GENERATOR-1000-001

- source: 成功済み1111と同じexplicit private configを基に、identifier flagだけを変更した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと条件に限定）
- candidate structure:
  - CP932-compatible、CRLF、BOMなし
  - first physical rowはofficial 30-column header
  - preambleなし、30-column data rowが1件
  - identifier flag `1000`
  - JDL-origin data rowを構築元に使用していない
- runtime result:
  - JDLが1件として認識し、Importを正常完了
  - 仕訳帳に1件だけ表示され、貸借一致と内容を目視確認
  - 振替伝票画面には表示されず、Manualの「伝票以外の仕訳」という意味と整合
  - Import後のJDL再Exportを取得
- privacy-safe raw comparison:
  - candidateから再Exportへ21 fieldsが入力表現のまま保持された
  - candidateでblankだった9 fieldsが再Exportではnonblank representationになった
  - 9 fieldsは伝番、借方/貸方の科目code、正式名称、消費税、部門code
  - candidate/re-exportともflag `1000`、30-column data row 1件
- interpretation:
  - account名称だけをidentifierとして使う限定経路の非伝票仕訳Import成功を確認した
  - blankからnonblankへの変化はJDLの再Export表現としてのみ記録する
  - JDL内部保存値、一般的な補完規則、generator defaultとは断定しない
- not verified:
  - subaccount、department
  - taxable/tax-included、taxable/tax-excluded
  - tax abbreviations、transaction account
  - compound `1110/1100/1101`
  - multiple records、large data sets、other products/versions
  - YayoiからJDLへのend-to-end conversion
  - production JDLOutputAdapter
- separation:
  - official documented schema全体は `OFFICIAL_DOCUMENTED` のまま
  - production JDLOutputAdapterは未登録
  - YayoiからJDLへのproduction readinessは変更しない

## EVID-JDL-GENERATOR-1000-SUBACCOUNT-001

- source: 成功済みgenerator-authored `1000` を基に貸方補助2項目だけを変更した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと親科目/補助科目の組み合わせに限定）
- candidate/runtime facts:
  - candidateの貸方補助numeric representationは `0001`
  - target masterで人間が実際に登録・確認した補助codeは `1`
  - official Manualでは貸方補助は数値4桁
  - JDLが1件として認識し、Importを正常完了
  - 仕訳帳で親科目配下の対象補助、貸借一致、摘要保持、重複なしを確認
- re-export evidence:
  - post-import re-export rawはCP932 decode可能、BOMなし、CRLF
  - preamble 3行、4行目にofficial 30-column header、30-column data row 1件
  - re-exportもflag `1000`、貸方科目・貸方補助名称はcandidate/実機確認と一致
  - re-export rawの貸方補助numeric representationは `1`
  - candidate `0001`、target master actual `1`、re-export `1` を別Evidenceとして保持する
- interpretation limits:
  - `0001` から `1` への正規化規則とは断定しない
  - leading zeroを常に無視するとは断定しない
  - `0001` と `1` が全JDL環境で同一とは断定しない
  - generatorが `1` または `0001` のどちらを出すべきか一般化しない
- separation:
  - production JDLOutputAdapterは未登録
  - YayoiからJDLへのproduction readinessは変更しない

## EVID-JDL-001

- source: prior failed-import dataset
- product/version evidence: JDL IBEX出納帳 35.5として確認済みの実データ
- evidence level: `OBSERVED`
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 30-column header family
  - header first cell is `//識別フラグ`
  - pre-header metadata/comment rows and blank row exist
  - identifier flag values observed: `1000`, `1100`, `1101`, `1110`, `1111`
- observed behavior:
  - diagnostic message rows can follow data records
  - padded diagnostic message rows can have the same column count as data records
  - `1110 -> 0..n * 1100 -> 1101` contiguous group candidates were observed
  - multiple group candidates had same voucher/date and debit/credit balance
- UI evidence:
  - JDL IBEX出納帳 35.5に「会計データ変換」機能が存在する
  - 「会計データ入出力設定」画面で `CSVファイル -> 仕訳ファイル` の入力経路を観測
  - 同一画面で `仕訳ファイル -> CSVファイル` の出力経路を観測
  - `データ管理・選択 -> CSV入力` のflowを観測
  - CSV入力のデータ種類として `仕訳データ` を選択できることを観測
  - 取り込むCSVファイルを参照して選択するfile chooserを観測
  - import前に出納帳ファイルを退避する確認画面を観測
  - import対象の日付範囲指定画面を観測
  - 集計単位として日単位/月単位を選択するUIを観測
  - 決算整理を含む/含まない選択を観測
  - validation failure時にCSV入力全体が拒否され、ログ表示ボタンが提示されることを観測
- limits:
  - some field names/order now match official manual evidence, but this file itself remains observed evidence
  - not verified as a successful import file
  - identifier flag meanings are now official documented in the manual layer, but observed grouping behavior remains separately tracked
  - JDL-origin `1111` round-tripと特定のgenerator-authored `1111` / `1000` artifactsは実機成功済み
  - generator-authored CSVを含む一般的なexport/import symmetryは未検証
  - generator-authored `1000` の限定artifactは実機成功済みだが、一般的な1000生成規則には昇格しない
  - visible field mapping UI was not observed in this flow, but absence of a field mapping feature is not proven
  - partial success was not observed

## EVID-JDL-001-UI-REJECTION

- source: JDL IBEX出納帳 35.5 CSV入力 rejection UI
- evidence level: `OBSERVED`
- observed message family:
  - CSVファイル内のデータ件数を表示する
  - 項目その他の相違により取込不可である旨を表示する
  - ログファイル確認を促す
  - ログ表示ボタンが存在する
- relationship to prior 1271-record evidence:
  - the displayed data count matches the previously analyzed failed-import case count
  - file identity is not proven by the UI evidence alone
  - prior diagnostics found master mismatch candidates that are consistent with this rejection family
  - re-analysis of the prior error CSV observed 1271 data records and 493 master mismatch candidates
  - mismatch candidate categories included debit/credit account and debit/credit subaccount
  - this does not prove subaccount mismatch is the only cause
- interpretation:
  - JDL IBEX出納帳 performs validation before or during import and can reject the whole import with log guidance
  - this strengthens the need to preserve whole-file blocking behavior in this project
  - this does not prove the 30-column export family is the official import layout
  - target master mismatch is a stronger hypothesis than before, but remains unverified until the JDL log is reviewed

## EVID-JDL-005

- source: JDL IBEX出納帳 35.5 error-annotated CSV generated after CSV入力 rejection
- evidence level: `OBSERVED`
- file relationship:
  - a newly supplied private error-annotated CSV was byte-identical to the previously analyzed error CSV
  - the identity check was performed by hash comparison in the private workspace
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 30-column header family
  - data record count: 1271
  - diagnostic message count: 493
  - all diagnostic messages were linked to the preceding data record by the current parser
- diagnostic category aggregate:
  - debit subaccount mismatch candidates: 374
  - credit subaccount mismatch candidates: 102
  - debit account mismatch candidates: 16
  - credit account mismatch candidates: 1
- record-level aggregate:
  - records with diagnostic candidates: 493
  - records without diagnostic candidates: 778
  - records with multiple diagnostic candidates: 0
- subaccount aggregate:
  - non-empty debit subaccount records matched debit subaccount mismatch candidates in this file
  - non-empty credit subaccount records matched credit subaccount mismatch candidates in this file
  - subaccount mismatch candidates without non-empty subaccount were not observed in this file
- interpretation:
  - account/subaccount mismatch was observed as a JDL runtime diagnostic category
  - target master-aware preflight would likely block this class of rejection earlier
  - this strengthens, but does not prove, the target master mismatch hypothesis
- limits:
  - customer-specific account/subaccount values are not recorded here
  - this does not prove subaccount mismatch is the only failure cause
  - this does not prove the 30-column CSV structure is fully correct
  - this does not prove import success after correcting master mismatches

## EVID-JDL-002

- source: JDL-origin export sample
- product/version evidence: JDL origin strongly suggested; product version unverified
- evidence level: `OBSERVED`
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 30-column header family
  - pre-header metadata/comment rows and blank row exist
  - data records are 30 columns
  - identifier flag values observed: `1000`, `1100`, `1101`, `1110`, `1111`
- observed behavior:
  - `1110 -> 0..n * 1100 -> 1101` contiguous group candidates were re-observed
  - observed group candidates had same voucher/date and debit/credit balance in aggregate
  - file-level debit and credit totals matched in diagnostic aggregate
- limits:
  - version is `UNVERIFIED`
  - not merged into the 35.5 version-specific evidence as confirmed behavior
  - not called a known-good import file
  - no importability claim is made

## EVID-JDL-MASTER-001

- source: JDL account master report
- scope: customer-specific target master evidence
- evidence level: `OBSERVED_PENDING_TEXT_REVIEW`
- current status:
  - a private PDF report exists as candidate master evidence
  - this development environment has no PDF text extraction utility/library available
  - report contents were not transcribed into tracked files
- review targets:
  - whether account code/name list exists
  - whether subaccounts appear under accounts
  - whether subaccount display-code format differs from CSV field representation
- limits:
  - customer-specific account/subaccount values are not format rules
  - no normalization rule such as display-code to CSV-code conversion is established
  - this supports the need for future master-aware Mapping Review, not automatic mapping

## EVID-JDL-003

- source: JDL会計 仕訳一覧CSV
- product/version evidence: JDL会計由来として実務上確認。versionは未確認。
- evidence level: `OBSERVED`
- purpose: post-import verification candidate / read-only evidence
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 21-column journal list export family
  - pre-header rows exist
  - header names/order differ from JDL IBEX出納帳30-column observed schema
  - data rows are 21 columns in the observed main body
- observed behavior:
  - account, subaccount, amount, description, tax-scope/tax-category-like fields are visible in the journal-list header
  - date values are not yet safely interpreted as calendar dates by the current analyzer
  - footer/summary-like non-21-column rows can appear after the main body
- separation:
  - not a 30-column import candidate format
  - not used for EXP-01 CSV generation
  - not merged into JDL IBEX出納帳35.5 observed import/export evidence
  - not verified as an importable CSV format
- limits:
  - version is `UNKNOWN`
  - field semantics are read-only verification candidates only
  - no claim is made that JDL会計 and JDL IBEX出納帳 share a CSV specification
  - no `VERIFIED_BY_REAL_IMPORT` promotion is made

## EVID-JDL-004

- source: JDL会計 / server-side financial system operation notes
- evidence level: `OBSERVED`
- observed topology:
  - day-to-day entry is performed on standalone JDL IBEX出納帳 installations
  - closing/reporting work uses the server-side JDL financial/accounting system
  - server-side system is operationally auto-updated
  - a JOBMENU screen displayed `財務システム38`
- separation:
  - `財務システム38` is not hardcoded as a product version
  - JDL会計/server-side exports are downstream evidence, not MVP import target evidence
  - JDL IBEX出納帳 35.5 remains the primary candidate for MVP direct import target

## Tax / Department Notes

- Tax and department columns are treated as observed fields only.
- Empty or repeated values in one dataset do not establish tax mapping, department mapping, default rules, or code meaning.
- Formal tax/category/department behavior requires additional real data and JDL import verification.

## Next Verification Gate

The JDL-origin `1111` round-trip and one explicit-config artifact for each of `1111` and `1000` are now scoped `VERIFIED_BY_REAL_IMPORT`. The next gate remains narrow:

1. Register one fully fictional subaccount under one already tested account in the same test company.
2. Record its exact parent account and identifier in private target-master evidence; do not use fuzzy matching or an unconfirmed value.
3. Only then generate one `1000` candidate whose sole semantic change is that subaccount.
4. Continue with department, tax-inclusive, tax-exclusive, then compound voucher.
5. Keep the official schema, production JDLOutputAdapter, and Yayoi-to-JDL readiness unchanged until their own evidence requirements are met.

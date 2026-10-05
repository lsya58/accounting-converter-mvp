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
  - subaccount、department、tax、compoundはそれぞれ限定artifactだけ実機検証済みで、Format全体は未検証
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
  - 当該Evidence取得時点ではproduction JDLOutputAdapterは未登録。現在はcontext-aware implementationを登録済みだが、production利用は無効
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
  - 当該Evidence取得時点ではproduction JDLOutputAdapterは未登録。現在はcontext-aware implementationを登録済みだが、production利用は無効
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
  - 当該Evidence取得時点ではproduction JDLOutputAdapterは未登録。現在はcontext-aware implementationを登録済みだが、production利用は無効
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
  - 当該Evidence取得時点ではproduction JDLOutputAdapterは未登録。現在はcontext-aware implementationを登録済みだが、production利用は無効
  - YayoiからJDLへのproduction readinessは変更しない

## EVID-JDL-DEPARTMENT-HAND-1111-001

- source: 完全架空テスト事業所で部門付き1行振替伝票を手入力し、JDL自身から再Exportしたraw CSV
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `OBSERVED`（Import検証ではなくmanual-entry/export観測）
- raw structure:
  - CP932 decode可能、BOMなし、CRLF
  - preamble 3行、4行目にofficial 30-column header
  - 30-column data row 1件、identifier flag `1111`
- department observation:
  - operatorは画面上で借方側だけに対象部門を指定
  - re-export rawでは借方・貸方の部門code/nameが両側とも非空
  - 両側のcode representationは `1`
  - 両側の名称representationは確認済み短縮名
- limits:
  - flag `1000`でも両側departmentが必要とは断定しない
  - すべての仕訳で片側指定が両側へ複製されるとは断定しない
  - departmentが片側指定不可とは断定しない
  - production capabilityまたはgenerator defaultへ昇格しない

## EVID-JDL-GENERATOR-1111-DEPARTMENT-001

- source: official/manual、target master確認、手入力department Export observationを根拠にexplicit configから生成した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactだけに限定）
- candidate/runtime scope:
  - official 30-column first-row header、CP932-compatible、BOMなし、CRLF
  - identifier flag `1111`、1行伝票、1 data record、貸借一致
  - 免税、補助なし、税fieldなし、部門処理有効
  - 確認済み部門masterのcode/短縮名を借貸両側4 fieldへ明示
  - JDLが1件と認識してImportを正常終了
  - 振替伝票画面で1伝票、貸借、摘要、借方部門表示、重複なしを確認
- raw re-export:
  - preamble 3行、official 30-column header、30-column data row 1件
  - candidateから23 fieldsを同じ表現で保持
  - candidateでblankだった7 fieldsがre-exportでnonblank
  - 借方/貸方の部門code/name 4 fieldsはすべてcandidate表現を保持
- interpretation limits:
  - UIでは借方部門が見え、貸方部門欄は空欄に見えた一方、raw re-exportでは借貸両側に部門表現がある
  - JDL内部保存、UI表示差の理由、両側部門の一般的requirednessは未確定
  - 片側department input、他部門、階層/配賦、税、複合、複数件には適用しない
  - production JDLOutputAdapterまたはYayoiからJDLへのreadinessへ昇格しない

## EVID-JDL-TAX-INCLUSIVE-HAND-1111-001

- source: 完全架空テスト事業所で課税・税込の1行振替伝票を手入力し、JDL自身からExportしたraw CSV
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `OBSERVED`（manual-entry/export観測。generator Import成功ではない）
- company setting scope:
  - 課税、原則課税、個別対応方式、税込
  - 売上/仕入端数は切り捨て、別記消費税は使用しない
  - department processing無効
- raw structure:
  - CP932-compatible、BOMなし、CRLF
  - preamble 3行、official 30-column header、30-column data row 1件
  - identifier flag `1111`、補助なし、貸借一致
- tax representation:
  - 借方課区は `仕　入`。中央はU+3000 IDEOGRAPHIC SPACE
  - 借方税区は `10%`
  - 借方税入力方法と借方取引科目はblank
  - 貸方の課区/税区/税入力方法/取引科目はblank
  - 借貸消費税と借貸部門codeはre-exportで `0`
- limits:
  - re-exportの税額/部門code `0`をgenerator defaultにしない
  - 課区の全角spaceを除去・半角化・trimしない
  - 他税率、他課区/税区、税抜、簡易課税、別の仕入税額控除方式へ一般化しない
  - transaction accountが常に不要とは断定しない
  - production capabilityへ昇格しない

## EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001

- source: Official Manual、上記の手入力Export observation、確認済みtarget masterだけから全30 fieldsを明示して生成した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと会社設定に限定）
- verified scope:
  - official 30-column headerを先頭行に持つCP932-compatible、BOMなし、CRLFのCSV
  - identifier flag `1111`、1行伝票、補助なし、部門なし、貸借一致
  - 課税、原則課税、個別対応方式、税込、売上/仕入端数切り捨て、別記消費税なし
  - raw-confirmedな借方課区 `仕　入`（中央U+3000）と借方税区 `10%` の1組
  - 実機が1件として認識し、Import完了後に1伝票、対象日付、貸借、摘要、税区分表示、重複なしを目視確認
  - post-import raw re-exportを取得
- candidate / re-export comparison:
  - 21 fieldsは入力表現を保持
  - candidateでblankだった9 fieldsがre-exportでnonblank
  - 借方課区、借方税区、借方税入力方法、借方金額、借方取引科目、貸方tax classification、貸方金額、貸方取引科目は入力表現を保持
  - 借貸消費税と借貸部門codeのre-export表現はgenerator defaultへ昇格しない
- limits:
  - 他の課区、税区、税率、軽減8%、売上側課税、税抜、税入力方法variant、明示税額、取引科目を検証していない
  - flag `1000` の課税、複合、混在税率、複数件、大量データを検証していない
  - production JDLOutputAdapterまたはYayoiからJDLへのreadinessへ昇格しない

## EVID-JDL-TAX-EXCLUSIVE-HAND-1111-001

- source: 完全架空テスト事業所で課税・税抜の1行振替伝票を手入力し、JDL自身からExportしたraw CSV
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `OBSERVED`（manual-entry/export観測。generator Import成功ではない）
- company / UI setting scope:
  - 課税、原則課税、個別対応方式、会社設定は税抜
  - 売上/仕入端数は切り捨て、別記消費税は使用しない
  - operatorが伝票入力UIの入力方式を税抜入力へ明示変更
  - company accounting settingとUI input modeは別Evidenceとして保持
  - department processing無効
- raw structure:
  - 564 bytes、CP932-compatible、BOMなし、CRLF
  - preamble 3行、official 30-column header、30-column data row 1件
  - identifier flag `1111`、補助なし、貸借一致
- tax representation:
  - 借方課区は `仕　入`。中央はU+3000 IDEOGRAPHIC SPACE
  - 借方税区は `10%`
  - 借方税入力方法は `内税`、借方消費税はnonblank
  - 貸方の課区/税区/税入力方法/取引科目はblank
  - 貸方消費税と借貸部門codeはself-exportで `0`
- interpretation limits:
  - UIの税抜入力とCSVの `内税`を同義化せず、この1条件で併存した観測事実だけを保持する
  - 税込Evidenceとは金額条件も異なるため、差分原因を税方式だけに帰属しない
  - self-exportの貸方消費税/部門code `0`をgenerator defaultにしない
  - 他税率、他課区/税区、売上側、別の税入力方法、取引科目へ一般化しない
  - production capabilityへ昇格しない

## EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001

- source: Official Manual、上記の手入力Export observation、確認済みtarget masterだけから全30 fieldsを明示して生成した完全架空1件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと会社・税設定に限定）
- verified scope:
  - official 30-column headerを先頭行に持つCP932-compatible、BOMなし、CRLFのCSV
  - identifier flag `1111`、1行伝票、補助なし、部門なし、貸借一致
  - 課税、原則課税、個別対応方式、会社設定は税抜
  - raw-confirmedな借方課区 `仕　入`、税区 `10%`、税入力方法 `内税`、明示税額の1組
  - 実機が1件として認識し、Import後に1伝票、貸借、摘要、tax表示、重複なしを目視確認
  - post-import raw re-exportを取得
- candidate / re-export comparison:
  - 22 fieldsは入力表現を保持
  - candidateでblankだった8 fieldsがre-exportでnonblank
  - 借方課区、税区、税入力方法、金額、消費税、取引科目は入力表現を保持
  - 貸方消費税と借貸部門codeのre-export表現はgenerator defaultへ昇格しない
- limits:
  - UIの税抜入力とCSVの `内税`を同義化しない
  - 他の課区、税区、税率、売上側、税入力方法、明示税額、取引科目を検証していない
  - flag `1000` の課税、複合、混在税率、複数件、大量データを検証していない
  - production JDLOutputAdapterまたはYayoiからJDLへのreadinessへ昇格しない

## EVID-JDL-COMPOUND-HAND-1110-1100-1101-001

- source: 完全架空テスト事業所で手入力した3行振替伝票のJDL self-export
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `OBSERVED`
- observed structure:
  - CP932-compatible、BOMなし、CRLF、3-row preamble、official 30-column header
  - 3 data recordsはいずれも30 columns
  - exact sequenceは `1110 -> 1100 -> 1101`
  - 3 recordsの伝番と日付はそれぞれ同一
  - group全体の借方合計と貸方合計は一致
  - 先頭recordは借貸両側、後続2 recordsは借方account blank / 借方金額 `0` / 貸方側nonblank
  - 摘要は先頭recordだけnonblank
- evidence boundaries:
  - Manualの3-record sequenceと、既存Observed `1110 -> 1100* -> 1101` familyに整合する
  - 既存2-record `1110 -> 1101` 観測を否定しないが、Manualの3-record例と同一仕様であるとは断定しない
  - generator-authored compound Import、伝番blank時のruntime grouping、他の行構成は未検証
  - self-exportの税額/部門code `0`をgenerator defaultへ昇格しない
  - production JDLOutputAdapterまたはYayoiからJDLへのreadinessへ昇格しない

## Generator-authored compound experiment

- candidate creation status: `GENERATOR_AUTHORED_COMPOUND_UNTESTED`
- construction: Official Manual、上記Observed Evidence、確認済みtarget account masterだけを根拠に全3 records / 全30 fields / decision sourceを明示
- candidate: `1110 -> 1100 -> 1101`、免税、補助なし、部門なし、tax fieldsなし、group貸借一致
- voucher field: Manual上optionalのため全行blank。自動採番やblank groupingを推測せず、runtime verification pendingとして扱う
- missing-side amount: Manual上requiredの金額列とObserved rawの双方を根拠に、後続recordの借方金額を明示的な`0`とした
- result: 下記の単一artifactについて実機Importと再Exportに成功。生成時statusは履歴として維持し、将来生成物へ成功を継承しない

## EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001

- source: Official Manual、手入力Export observation、確認済みtarget masterから全90 fieldsを明示した完全架空3-record artifact
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと会社設定に限定）
- verified scope:
  - official 30-column headerを先頭行に持つCP932-compatible、BOMなし、CRLFのCSV
  - exact sequence / row order `1110 -> 1100 -> 1101`
  - candidate伝番は3 recordsすべてblank、日付は同一、group貸借一致
  - 実機が3 recordsを認識し、1つの振替伝票へgrouping
  - 先頭recordだけ摘要あり、後続摘要blank、重複なしをUIで確認
  - post-import raw re-exportを取得
- candidate / re-export comparison:
  - 90 fields中67 fieldsは入力表現を保持
  - 23 fieldsはcandidate blankからre-export nonblankへ変化
  - sequence、row order、日付、金額配置、摘要配置は保持
  - candidate伝番blankとre-export伝番`0`は別Evidenceとして保持
  - `0`はruntime re-export表現であり、generator defaultへ昇格しない
- limits:
  - 複数group、nonblank伝番、別の借貸構成、長いmiddle sequenceを検証していない
  - compound内のtax、subaccount、department、mixed tax rateを検証していない
  - blank伝番が常に安全、JDLが常にsequenceだけでgroupingするとは一般化しない
  - production JDLOutputAdapterまたはYayoiからJDLへのreadinessへ昇格しない

## EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001

- source: 検証済みsimple/compoundのexplicit configを再利用し、同日4 recordsを明示生成した完全架空artifact
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このartifactと会社設定に限定）
- candidate structure:
  - official 30-column headerを先頭行に持つCP932-compatible、BOMなし、CRLFのCSV
  - flag / row orderは `1111 -> 1110 -> 1100 -> 1101`
  - 全4 recordsは同日、伝番はすべてblank
  - `1111`単独groupと`1110 -> 1100 -> 1101` compound groupは個別に貸借一致
- runtime result:
  - JDLは4 recordsを認識してImportを正常終了
  - UIではsimple 1伝票とcompound 1伝票のexactly 2 vouchersを確認
  - merge、compound内部のsplit、duplicateは観測されず、順序、貸借、摘要を確認
  - 両voucherのUI伝票番号欄はblankとして観測
- raw re-export:
  - 875 bytes、CP932/Shift_JISの双方でdecode可能な文字範囲、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 4 rows
  - flag order、日付、account/amount/description配置を保持
  - 120 fields中88 fieldsは入力表現を保持し、32 fieldsはcandidate blankからre-export nonblankへ変化
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`に分類される差分は今回0
- voucher evidence separation:
  - candidate raw: 全4伝番blank
  - runtime UI: 2 vouchersとも伝票番号欄blank
  - self re-export raw: 全4伝番`0`
  - 限定的に「今回の未指定伝番はself-exportで`0`表現になった」とだけ扱う
  - JDLが伝番0を採番した、blankが常に0になる、generatorが0を出すべき、とは解釈しない
- group-boundary interpretation:
  - 今回の同日 `1111 + 1110/1100/1101` は、candidate伝番blankでも2 groupsとしてImportされた
  - 同日かつre-export伝番`0`だけでは、今回のlogical boundaryを表現できない
  - voucher numberが常にgroupingと無関係、flagだけで常に判定可能、JDL内部algorithmが判明した、とは一般化しない
  - diagnosticsのblank voucherを含む未知ケースは引き続き保守的に`UNRESOLVED`とする
- limits:
  - simple+simple、compound+compound、3 groups以上、nonblank伝番は未検証
  - 同flag type同士のboundary、任意順序、長いmiddle sequence、2 debit : 1 credit、many-to-manyは未検証
  - compound内tax/subaccount/department、large batch、他製品/version、YayoiからJDL E2Eは未検証
  - production JDLOutputAdapterとYayoiからJDLへのreadinessは変更しない

## EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001

- source: 完全架空Yayoi 25-field sourceからcontext-aware正式経路で生成した同日simple 2件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このexact 2-journal artifactと会社設定に限定）
- verified path/scope:
  - `YayoiInputAdapter`、confirmed Mapping、`ConversionRequest.target_runtime_context`、Registry、`JdlOutputRuntimeFactory`、Validator、atomic publishを経由
  - 免税、補助なし、部門なし、tax fieldsなし
  - official 30-column first-row header、CP932、BOMなし、CRLF、preambleなし
  - 同日2 records、flag order `1111 -> 1111`、candidate伝番は両方blank
  - JDLは2 recordsを認識し、UIでexactly 2 vouchersを確認
  - merge、split、duplicateは観測されず、row order、科目配置、金額、摘要、各voucherの貸借を確認
- raw re-export:
  - 672 bytes、SHA-256 `61193a1eef697b1e2fb2bb51a382a4e924a7cc4316aa3dced54d4583b289b1e0`
  - CP932/Shift_JIS strict round-trip可能、UTF-8不可、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 2 rows
  - candidate/re-export 60 fields中42 `PRESERVED`、18 `BLANK_REEXPORT_NONBLANK`
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`は0。semantic differenceも0
- voucher evidence separation:
  - candidate raw: 2 recordsとも伝番blank
  - runtime UI: 2 vouchersとも伝票番号欄blank
  - self re-export raw: 2 recordsとも伝番`0`
  - 「今回の未指定伝番はself-export上で`0`表現になった」とだけ扱う
  - JDLが`0`を採番した、blankが常に`0`、generatorも`0`を出すべき、とは一般化しない
- strict allow-list decision:
  - exact 2 journals、同日、両方`SUPPORTED_1111_BASIC`の組合せを許可する
  - 3件以上、任意batch size、異なる日付、tax/subaccount/department付きsimple、別製品/versionには拡張しない
  - production registryは`UNAVAILABLE`、一般Yayoi -> JDL readinessはNOT READYを維持する

## EVID-JDL-WINDOWS-GUI-E2E-001

- source: Windows packaged applicationのTkinter GUIから完全架空Yayoi CSV、明示選択Profile、明示選択JDL Contextを使用して生成した同日simple 2件
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このGUI経路、artifact、会社設定に限定）
- verified path/scope:
  - GUI -> `FirstReleaseConversionWorkflow` -> `ConversionRequest` -> Registry -> `JdlOutputRuntimeFactory` -> `ConversionService` -> Adapter/Validator
  - confirmed exact Mapping 4/4、unresolved 0、validated target Context、免税、補助/部門/taxなし
  - 2 logical journals / 2 physical records、同日、flag order `1111 -> 1111`
  - JDLは2 recordsを認識し、exactly 2 vouchersとして正常Import
  - merge、split、duplicateなし。UIで科目配置、金額、摘要、各voucherの貸借を確認
  - scroll修正版packaged appでmouse wheel、scrollbar、resize後の結果/検証欄到達を確認
  - target version `99.9`のprivate test ContextはpreflightでBLOCKされ、作成button無効、変換未実行、出力なしを確認
- raw candidate/re-export:
  - candidateは483 bytes、CP932、BOMなし、CRLF、preambleなし、official header、30-column data 2 rows
  - re-exportは672 bytes、SHA-256 `79b749277d3f2952ecf0cbfd0a520d9978e1d764a90232bbc098435c49b598ac`
  - re-exportはCP932、BOMなし、CRLF、preamble 3 rows、official header、30-column data 2 rows
  - 60 fields中42 `PRESERVED`、18 `BLANK_REEXPORT_NONBLANK`。`NORMALIZED`、`DIFFERENT`、`UNKNOWN`、semantic differenceは0
  - runtime追加は伝番、account code/正式名称、tax amount 0、department code 0として観測したが、generation defaultへ昇格しない
- voucher evidence separation:
  - candidate rawは両recordとも伝番blank
  - runtime UIは両voucherとも伝票番号欄blank
  - re-export rawは両recordとも伝番`0`
  - 今回の未指定伝番がself-export上で`0`表現になったことだけを示し、採番、一般blank-to-zero規則、generator defaultとはしない
- limits/readiness:
  - arbitrary Profile/customer Context、tax、department、subaccount、任意batch、他製品/versionへ一般化しない
  - core engine、context-aware runtime、Windows packaged GUIのstrict verified scopeはruntime acceptance済み
  - positive/negative packaged acceptance完了後、JDL IBEX出納帳35.5のexact identityと既存Evidence allow-listに限りproduction Registryを有効化する
  - Context、confirmed Mapping、no-overwrite等の既存停止条件は維持し、allow-list外はREADYにしない

## EVID-JDL-MIXED-BATCH-RUNTIME-001

- source: 完全架空Yayoi 25-field sourceからcontext-aware正式経路で生成したmixed batch
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このexact batch sequenceと会社設定に限定）
- verified structure:
  - 同日12 logical journals / 22 physical records
  - simple 7件は`1111`、compound 5件はexact `1110 -> 1100 -> 1101`
  - simple-simple、simple-compound、compound-compound、compound-simpleの4 boundaryを含む固定順
  - candidate伝番は全22 recordsでblank、免税、補助/部門/tax fieldsなし
  - confirmed 4-account Mapping、validated runtime Context、OutputValidator、atomic publishを経由
- runtime result:
  - JDLは22 recordsを認識してImportを正常終了
  - UIでexactly 12 logical journalsを確認
  - merge、split、duplicateは観測されず、全groupの科目・金額・摘要・貸借を確認
- raw re-export:
  - 2883 bytes、SHA-256 `46a2f5686ddcf61020941683bf9d51c14c90827f803f7f78b76391de3eb052dc`
  - CP932/Shift_JIS strict round-trip可能、UTF-8不可、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 22 rows
  - candidate/re-export 660 fields中482 `PRESERVED`、178 `BLANK_REEXPORT_NONBLANK`
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`は0。semantic differenceも0
- voucher evidence separation:
  - candidate raw: 全22 recordsの伝番blank
  - runtime UI: voucher number未指定として観測
  - self re-export raw: 全22 recordsの伝番`0`
  - 今回の未指定伝番がself-export上で`0`表現になったことだけを示す
  - 採番、一般的なblank-to-zero規則、generation defaultとは解釈しない
- strict allow-list decision:
  - 今回の固定12-journal profile順、同日、strict basic/1D3C feature scopeだけを許可する
  - 任意件数・順序、別compound shape、tax/subaccount/department付きbatch、別製品/versionへ一般化しない
  - production registryは`UNAVAILABLE`、一般Yayoi -> JDL readinessとGUI-safe判定は変更しない

## EVID-JDL-CONVERSION-SERVICE-E2E-001

- source: 完全架空JSONを正式`ConversionService`経路で変換したrelease-gate artifact
- product/version evidence: JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（下記formal pathとstrict allow-listに限定）
- formal generation path:
  - Synthetic Input Adapter -> Structural Validation -> Common Journal Model
  - confirmed `ConversionProfile` -> `MappingEngine` -> Business Validation
  - `JdlOutputPreflight` -> `JDLOutputAdapter v0` -> temporary output
  - `JDLOutputValidator` -> Verification Report -> atomic publish
- verified scope:
  - official 30-column first-row header、CP932、BOMなし、CRLF、preambleなし
  - 同日`1111 -> 1110 -> 1100 -> 1101`、2 logical journals / 4 physical records
  - confirmed account mappings、unresolved 0、unsupported profile 0、貸借合計一致
  - JDL実機は4 recordsを認識し、exactly 2 vouchersとして正常Import
  - simple/compoundのmerge、compound split、duplicateは観測されなかった
  - 日付、科目名称、金額配置、摘要、flag順、group境界、貸借をUIとself re-exportで確認
- raw re-export:
  - 873 bytes、CP932/Shift_JISの双方でdecode可能な文字範囲、UTF-8不可、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 4 rows
  - candidate/re-export 120 fields中88 `PRESERVED`、32 `BLANK_REEXPORT_NONBLANK`
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`は0。semantic differenceも0
- voucher evidence separation:
  - candidate: 全4 recordsの伝番blank
  - runtime UI: 2 vouchersの伝票番号欄blank
  - self re-export: 全4 recordsの伝番`0`
  - 「今回の未指定伝番がself-export上で`0`表現になった」とだけ扱う
  - JDLが0を採番した、blankが常に0、generatorも0を出すべき、とは一般化しない
- release decision:
  - Adapter behaviorのformal runtime release gateは通過した
  - 当該Evidence取得時点ではexplicit target contextのruntime配線が未実装だった。現在はcontext-aware factoryを登録済みだが、この新経路の実機再検証前なのでproduction利用は無効
  - このEvidence単独ではYayoiInputAdapter起点E2Eを検証していなかった。後続の`EVID-JDL-YAYOI-TO-JDL-E2E-001`でstrict scopeのruntime E2Eを別途確認した
- limits:
  - simple+simple、compound+compound、10-20 records mixed batchは未検証
  - 任意のgroup順・件数・feature combination、他JDL製品/versionへ一般化しない
  - re-exportの科目code/正式名称、税額`0`、部門code`0`をgeneration defaultへ昇格しない

## EVID-JDL-YAYOI-TO-JDL-E2E-001

- source: 完全架空のYayoi AE19 observed 25-field CSVを正式変換経路へ入力したartifact
- product/version evidence: Yayoi Accounting AE 19 observed direct-export identity -> JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（下記formal routeとstrict allow-listに限定）
- formal route:
  - `YayoiInputAdapter` -> Structural Validation -> Common Journal Model
  - confirmed `ConversionProfile` / `MappingEngine` -> Business Validation
  - explicit Evidence route assignment -> `JdlOutputPreflight` / `JDLOutputAdapter`
  - `JDLOutputValidator` -> Verification Report -> atomic publish
- verified scope:
  - sourceはCP932、BOMなし、CRLF、headerなし、25 fieldsの4 physical records
  - source groupingはsimple 1件とexact 3-record compound 1件、合計2 logical journals
  - account mapping 4件は明示確認済み。fuzzy/implicit mappingなし
  - outputは同日`1111 -> 1110 -> 1100 -> 1101`、4 physical records / 2 logical journals
  - 免税、補助なし、部門なし、tax fieldsなし
  - JDL実機は4 recordsを認識して正常終了し、UIでexactly 2 vouchersを確認
  - merge、split、duplicateは観測されず、貸借、科目配置、摘要、group境界を確認
- raw re-export:
  - 873 bytes、CP932/Shift_JIS strict round-trip可能な文字範囲、UTF-8不可、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 4 rows
  - candidate/re-export 120 fields中88 `PRESERVED`、32 `BLANK_REEXPORT_NONBLANK`
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`は0。semantic differenceも0
- voucher evidence separation:
  - candidate raw: 全4 recordsの伝番blank
  - runtime UI: 2 vouchersの伝票番号欄blank
  - self re-export raw: 全4 recordsの伝番`0`
  - 「今回の未指定伝番はself-export上で`0`表現になった」とだけ扱う
  - 採番、一般的なblank-to-zero規則、generator defaultとは解釈しない
- readiness decision:
  - strict scopeのcore Yayoi -> JDL conversion engineはruntime validated
  - 当該Evidence時点ではcontext-aware経路自体が実機未確認だった。後続の`EVID-JDL-CONTEXT-AWARE-RUNTIME-E2E-001`で限定scopeのruntime wiringを確認した
  - 一般的なYayoi -> JDL routeとGUIはNOT READY
- limits:
  - tax、subaccount、department付きYayoi -> JDLは未検証
  - simple+simple、compound+compound、10-20 records mixed batch、任意batch sizeは未検証
  - 任意compound shape、別Yayoi/JDL製品・version、Format全体へ一般化しない

## EVID-JDL-CONTEXT-AWARE-RUNTIME-E2E-001

- source: 完全架空Yayoi AE19 observed 25-field CSVをcontext-aware正式経路へ入力したartifact
- product/version evidence: Yayoi Accounting AE 19 observed identity -> JDL IBEX出納帳 35.5
- evidence level: `VERIFIED_BY_REAL_IMPORT`（このruntime wiringとstrict allow-listに限定）
- verified runtime path:
  - `ConversionRequest.target_runtime_context` -> `AdapterRegistry`
  - `JdlOutputRuntimeFactory` -> immutable `JdlTargetContext` validation
  - confirmed Mappingとtarget masterのexact cross-check
  - `JDLOutputAdapter` -> `JDLOutputValidator` -> Verification Report -> atomic publish
- verified scope:
  - 免税、補助/部門/税なし、同日simple 1件 + exact 1D3C compound 1件
  - outputは`1111 -> 1110 -> 1100 -> 1101`の4 records
  - JDL実機は4 recordsを認識し、exactly 2 vouchersとして正常Import
  - merge、compound split、duplicateなし。UIで貸借、科目配置、摘要、group境界を確認
- raw re-export:
  - 873 bytes、SHA-256 `d303545279f99e013fea773eeba21e5da69898a85eb79bdd33c50c62a45f0546`
  - CP932/Shift_JIS strict round-trip可能、UTF-8不可、BOMなし、CRLF
  - preamble 3 rows、official header 1 row、30-column data 4 rows
  - 120 fields中88 `PRESERVED`、32 `BLANK_REEXPORT_NONBLANK`
  - `NORMALIZED`、`DIFFERENT`、`UNKNOWN`は0。semantic differenceも0
- voucher evidence separation:
  - candidateは全4 recordsの伝番blank
  - runtime UIは2 vouchersとも伝票番号欄blank
  - re-exportは全4 recordsの伝番`0`
  - 今回の未指定伝番がself-export上で`0`表現になったことだけを示す。採番、一般的なblank-to-zero規則、generation defaultとはしない
- limits/readiness:
  - core engineとcontext-aware wiringはこのscopeでruntime validated
  - 任意customer context、simple+simple、compound+compound、10-20 records batchは未検証
  - tax/subaccount/department、別製品/version、一般GUI workflowへ一般化しない
  - 当該Evidence取得時点ではproduction lookupは`UNAVAILABLE`、一般的なYayoi -> JDL routeとGUIはNOT READYとしていた。現在判断は末尾のNext Verification Gateを参照

## Generator-authored 1000 department experiment

- result: `INCONCLUSIVE / NOT VERIFIED`
- candidate: flag `1000`、借方部門のみ、補助なし、免税、1件
- runtime observation:
  - CSV自体はImportされた
  - JDL仕訳帳画面ではdepartment表示を確認できなかった
  - 初回試行には以前のsubaccount masterが残ったことによる別要因errorもあった
- interpretation:
  - department Import成功Evidenceにはしない
  - flag `1000` 固有挙動、片側department表現、master状態の影響を分離できていない
  - production readinessは変更しない

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

単一simple、単一compound、限定master/tax条件、同日simple+compound、同日simple+simple、正式YayoiInputAdapter起点artifact、context-aware registry/factory経路、固定12-journal mixed batch、Windows packaged GUIの実機Import・UI確認・self re-export比較まで完了した。さらにscroll/resizeと未対応target versionの安全停止もWindows実機で確認した。

1. JDL IBEX出納帳35.5のexact identityに限りproduction Registryを`AVAILABLE`とする。別version/製品は`UNAVAILABLE`のままとする。
2. selected ConversionProfile、confirmed target master、tax/company settingsから`JdlTargetContext`をruntime構築し、factory経由でAdapterを生成する経路は実機確認済み。context欠落・不整合は引き続き明示的にblockする。
3. strict scopeのcore engine、context-aware runtime、Windows packaged GUI、Yayoi AE19からJDL IBEX出納帳35.5へのFirst Release経路はREADYとする。
4. subaccount/tax/department付きYayoi routeと任意batch拡張は別の限定Evidence取得後に判断する。
5. 未確認の組合せは引き続きstrict preflightでblockし、official schema identityをFormat全体の実機検証済みへ昇格しない。

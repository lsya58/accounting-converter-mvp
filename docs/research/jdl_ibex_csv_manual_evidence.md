# JDL IBEX 出納帳 CSV Manual Evidence

**目的:** JDL IBEX 出納帳のCSV仕訳データ入力について、操作マニュアルから確認できた仕様を `OFFICIAL_DOCUMENTED` evidenceとして整理する。

この文書はマニュアル画像そのものを保存しない。顧客データ、科目名、補助名、日付、金額、摘要、raw CSV rowは記録しない。

## Evidence

- source: JDL IBEX 出納帳 操作マニュアル P312-P327
- relevant pages:
  - P319: CSV入力条件
  - P320: 仕訳データ30項目の仕様
  - P321: 仕訳CSV例、列は常に必要
  - P322: 伝票sequence、税項目の条件
  - P326-P327: CSV入力操作、エラーCSV出力
- manual footer date: 2024-02-14
- copyright footer: Japan Digital Laboratory
- evidence level: `OFFICIAL_DOCUMENTED`
- scoped real import verification: JDL-origin `1111` round-trip and explicit-config generator-authored `1111` / `1000` artifacts
- full format / subaccount, department, tax, compound and bulk conditions: pending

JDL IBEX 出納帳35.5で観測したUI/実CSVとは別Evidenceとして扱う。マニュアルをVersion 35.5固有仕様としては扱わない。

## Official Documented Input Conditions

- CSV拡張子は `.csv`。
- 仕訳日付は処理中の会計年度内であること。
- 入力開始月が設定されている場合、入力開始月以降の日付であること。
- 1行目には項目名称が正しく入力されていること。
- 項目名称の前後または途中に空白を入れないこと。
- 不要なデータは空欄にできるが、列そのものは削除しない。

## 30-Column Journal Input Schema

マニュアルP320の仕訳データは30項目。

1. `//識別フラグ`
2. `伝番`
3. `日付`
4. `借方科目`
5. `借方科目名称`
6. `借方科目正式名称`
7. `借方補助`
8. `借方補助名称`
9. `借方課区`
10. `借方税区`
11. `借方税入力方法`
12. `借方金額`
13. `借方消費税`
14. `貸方科目`
15. `貸方科目名称`
16. `貸方科目正式名称`
17. `貸方補助`
18. `貸方補助名称`
19. `貸方課区`
20. `貸方税区`
21. `貸方税入力方法`
22. `貸方金額`
23. `貸方消費税`
24. `摘要`
25. `借方取引科目`
26. `貸方取引科目`
27. `借方部門コード`
28. `借方部門名称`
29. `貸方部門コード`
30. `貸方部門名称`

既存のJDL IBEX出納帳35.5 observed 30-column headerとは列名・順序が一致した。ただし、official documented schema と observed schema はEvidence layerを分けて保持する。

## Identifier Flags

マニュアルP320で以下の意味が確認できた。

- `1000`: 伝票以外の仕訳
- `1111`: 伝票1行の仕訳
- `1110`: 伝票1行目の仕訳
- `1100`: 伝票n行目の仕訳
- `1101`: 伝票最終行の仕訳

マニュアルP322では、振替伝票取込時のsequenceとして `1110 -> 1100 -> 1101` の順序が示されている。既存observed evidenceでは `1110 -> 1100* -> 1101` を観測しているが、0件以上の`1100`を一般仕様として断定しない。

JDL IBEX出納帳35.5の完全架空3行振替伝票self-exportでも、`1110 -> 1100 -> 1101`、同一伝番、同一日付、group貸借一致を観測した（`EVID-JDL-COMPOUND-HAND-1110-1100-1101-001`）。これはManualとのruntime export上の整合であり、generator-authored Import成功Evidenceではない。既存の2-record `1110 -> 1101` Observed Behaviorを正式仕様へ昇格または否定するものでもない。

その後、同じ3-record構造をOfficial Manual、Observed Evidence、target master確認から明示生成し、candidate伝番を全行blankとした単一artifactの実機Importに成功した（`EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001`）。実機は3 recordsを1伝票へgroupingし、再Exportでは全伝番が`0`になった。blank Import成功とre-export `0`は別Evidenceであり、`0`をgenerator defaultへ昇格せず、複数groupでも同じ挙動になるとは扱わない。

さらに、同日・全伝番blankの `1111 + 1110 -> 1100 -> 1101` を1 CSVに置いたgenerator-authored artifactが実機でexactly 2 vouchersとしてImportされた（`EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001`）。同じcontext-aware正式経路で生成した同日`1111 + 1111`もexactly 2 vouchersとしてImportされ、self re-export比較60 fieldsのsemantic differenceは0だった（`EVID-JDL-SIMPLE-PLUS-SIMPLE-RUNTIME-001`）。いずれもUI伝票番号欄はblank、self re-exportの伝番は`0`だった。この結果はManualのflag semanticsと整合するが、JDL内部grouping algorithm、任意件数・順序、blank/`0`の一般規則を証明しない。candidate raw、runtime UI、re-export rawの3層を分離して保持する。

同じ正式経路で生成した固定12-journal mixed batchも、22 recordsからexactly 12 logical journalsとしてImportされた（`EVID-JDL-MIXED-BATCH-RUNTIME-001`）。simple/compoundを繰り返す4種類のboundary、各group貸借、row orderをUIとself re-exportで確認し、660 fieldsのsemantic differenceは0だった。これは当該固定順とstrict feature scopeのEvidenceであり、任意batch size/orderやJDL内部grouping algorithmを示さない。

## Account And Master Rules

- 勘定科目は、科目コード、科目名称、科目正式名称のいずれか1つが入力されていれば取り込めると記載されている。
- 補助科目は、補助コードまたは補助名称のいずれか1つが入力されていれば取り込めると記載されている。
- ただし、取込先の出納帳ファイルに補助科目が登録されていない場合は取り込めない。

これは既存の1271件error-annotated CSVで観測したaccount/subaccount mismatch diagnosticsと整合する。ただし、master mismatchを直せば必ずImport成功するとは断定しない。

## Tax Rules

課区、税区、税入力方法、消費税は、取込先会社の消費税処理に従う。

- 免税: 課区、税区、税入力方法、消費税は不要。
- 課税 / 税込処理: 課区、税区は必要。税入力方法、消費税は不要。
- 課税 / 税抜処理: 課区、税区、税入力方法、消費税が必要。

課区・税区の組み合わせが正しくない場合、また必要項目が不足または不要項目が入力されている場合は取り込めない。課区・税区の略称一覧は今回のEvidenceでは未取得のため、コードでは値一覧を推測しない。

借方/貸方金額は税抜処理の場合でも消費税を合算した金額を入力し、出納帳ファイルには税込金額で取り込まれる。

借方/貸方取引科目は消費税仕訳のときのみ必要。通常仕訳に0などを自動入力しない。

JDL IBEX出納帳35.5の課税・原則課税・個別対応方式・税込という限定会社設定で、手入力 `1111` のself-exportを観測した。借方課区/税区は非空、税入力方法はblankで、Manualの税込requirednessと整合した。self-exportの借貸消費税は `0` だったが、Manual上は税込処理で消費税fieldは不要であるため、`0`をInput generatorのdefaultにはしない。貸方税classificationがblankだったことも、この1仕訳・科目組み合わせのObserved Evidenceに限定する。

同じ実機の課税・原則課税・個別対応方式・税抜という限定会社設定で、operatorがUIの税抜入力を選んだ手入力 `1111` self-exportも観測した。借方課区/税区/税入力方法/消費税はすべて非空で、Manualの税抜requirednessと整合する。金額はManualどおり消費税込み総額として記録された。一方、UI入力方式とCSV税入力方法の文言は一致しないため、同義とは解釈しない。通常仕訳の非課税側と取引科目はblankであり、self-exportの貸方消費税/部門code `0`はgenerator defaultにしない。

## Import Operation And Error File

マニュアルP326-P327で以下を確認した。

- `データ管理・選択 -> CSV入力`
- 取り込むデータ種類とCSVファイルを指定する。
- import前に現在データの退避確認がある。
- 仕訳データでは取込日付範囲を指定する。
- 実行前に取込件数を確認する。
- 指定日付範囲外のデータは取り込まれない。
- 取り込めないデータがある場合はmessageが表示される。
- ログ表示でerror内容を確認できる。
- error dataには対象仕訳の下の行に `//` とerror内容が表示される。
- error内容を記述した `JDL出納帳CSVエラー.csv` が作成される。
- 成功時はCSV変換終了messageが表示される。

## Export Preamble Difference

Official input requirementでは、1行目が30列の項目名称headerである。一方、既存JDL-origin export evidenceでは、metadata/comment row、period row、blank rowの後に30-column headerが現れるケースを観測している。

完全架空テスト事業所のJDL IBEX出納帳35.5で、JDL自身がExportした `1111` の1 data rowについて、先頭3 physical rows、83 bytesのpreambleだけを除去し、header + data suffixをbyte-for-byte保持したcandidateの再Importに成功した。これにより、この限定round-trip経路ではfirst physical rowのofficial headerとpreamble除去が実機検証された。

さらに、official/manual、target master確認、explicit configだけから生成した完全架空の `1111` 1件も同じ実機へImportでき、登録内容の目視確認とJDL再Exportまで完了した。この限定経路では、科目名称だけをaccount identifierとして使い、免税、補助なし、部門なし、税fieldなしの組み合わせが実機検証された。

Import後の再Exportでは、candidate入力の21 fieldsが同じ表現で保持され、blank入力だった9 fieldsがnonblank表現になった。これは再Export表現の観測であり、JDL内部保存値、一般的な補完規則、generator defaultとは扱わない。30-column Format全体も検証済みとは扱わない。

同じ条件でidentifier flagだけを `1000` に変更したgenerator-authored 1件も実機Importに成功した。`1111` は振替伝票画面で1行伝票として確認し、`1000` は仕訳帳で確認して振替伝票画面には表示されなかった。この差はManualの `1111 = 伝票1行の仕訳`、`1000 = 伝票以外の仕訳` と整合する。1000の再Exportでも21 fields保持、同じ9 blank fieldsのnonblank表現を観測したが、default規則には昇格しない。

部門処理を有効にし、確認済み部門masterのcode/短縮名を借貸両側へ明示したgenerator-authored `1111` 1件も実機Importと再Exportに成功した。raw比較ではdepartment 4 fieldsを含む23 fieldsが保持され、blank入力7 fieldsがre-exportでnonblankになった。UIで借方部門だけが見えた理由や、部門を常に両側へ入力すべきかはManualから確定できないため、このartifactを一般規則にはしない。

課税・税込の手入力Exportで観測した借方課区/税区1組とManual requirednessを使い、全30 fieldsを明示したgenerator-authored `1111` 1件も実機Importと再Exportに成功した。借方課区のU+3000を含む表現と借方税区はraw再Exportで保持された。candidateの21 fieldsが保持され、blank入力9 fieldsがnonblankになったが、再Exportの税額/部門code表現をgenerator defaultにはしない。この検証は当該会社設定、税表現、1 artifactに限定する。

課税・税抜の手入力Exportで観測した借方tax表現1組とManual requirednessを使い、全30 fieldsを明示したgenerator-authored `1111` 1件も実機Importと再Exportに成功した。借方課区のU+3000、税区、税入力方法、明示税額は保持された。candidateの22 fieldsが保持され、blank入力8 fieldsがnonblankになったが、貸方消費税/部門codeの再Export表現をgenerator defaultにはしない。UI入力方式とCSV税入力方法の意味関係も未確定のままとする。

## Remaining Blockers

- 貸方補助、借貸両側部門、単一3-record compoundの特定artifactsは限定的に実Import検証済み。その他の補助/部門表現、各税処理、複数group・複数件は未検証。
- 部門処理を有効にした手入力 `1111` の再Exportでは、画面上の借方側指定に対してraw CSVの借貸両側部門fieldが埋まることを観測した。これはExport observationであり、generator-authored department Importの成功Evidenceではない。
- 借方部門だけを明示したgenerator-authored `1000` 実験はImport後の部門表示を確認できず、別要因errorも混在したため `INCONCLUSIVE / NOT VERIFIED`。
- 課税・税込の借方課区/税区1組は限定artifactで実Import検証済み。他税率/税区、売上側課税、明示税額、transaction account、複数件は引き続きblockする。
- 課税・税抜の借方tax表現1組は限定artifactで実Import検証済み。UI入力方式とCSV税入力方法の意味関係、別の税額/税率、売上側、取引科目は未確認。
- 取込先テスト会社の科目master確認。
- 補助科目を使う場合の親科目配下登録確認。
- 取込先会社の消費税処理確認。
- 課区・税区略称一覧。
- 日付範囲、伝番、振替伝票行数など会社設定依存項目。

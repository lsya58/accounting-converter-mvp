# JDL EXP-01 Import Candidate Experiment

## 目的

EXP-01は、完全架空の最小1仕訳をJDL IBEX出納帳 35.5の `データ管理・選択 -> CSV入力 -> 仕訳データ` 経路で手動Import試験するための研究用手順です。

これは正式JDLOutputAdapterではありません。JDL IBEX 出納帳操作マニュアルP319-P322/P326-P327で確認した `OFFICIAL_DOCUMENTED` schemaと、実CSVから観測したCP932/CRLF/BOMなしserializationを組み合わせた実験です。成功しても即production化しません。

Manual evidenceにより、30列CSV仕訳データ入力schema、1行目header requirement、identifier flag meanings、税処理ごとのconditional requirements、error CSV behaviorは確認済みです。JDL-origin data rowを保持した限定round-tripと、explicit configから生成した特定の `1111` / `1000` artifactsは実機成功済みです。次の補助科目candidateはtarget master確認待ちです。

今回観測した操作flow:

1. `データ管理・選択 -> CSV入力`
2. データ種類で `仕訳データ` を選択
3. 取り込むCSVファイルを参照して選択
4. 出納帳ファイルを退避するか確認
5. 取込対象の日付範囲を指定
6. 集計単位と決算整理の扱いを選択
7. 実行

このflowではvisibleなfield mapping UIは観測されていない。ただしfield mapping機能が存在しないとは断定しない。

## Round-Trip Baseline

完全架空テスト事業所のJDL IBEX出納帳35.5で、JDL自身がExportした `1111` の1行伝票を使ったround-trip Importに成功した。source exportの先頭3 physical rows、83 bytesのpreambleだけを除去し、official headerとdata rowはbyte-for-byte保持した。JDLは1件として認識し、Import後に1伝票、重複なし、日付、貸借科目、貸借金額、摘要、貸借一致を確認した。

この結果のEvidence levelは、そのsame-runtime round-trip経路だけ `VERIFIED_BY_REAL_IMPORT` とする。generator-authored field values、`1000`、補助、部門、税、compound voucher、YayoiからJDLへの変換には適用しない。

## Generator-Authored 1111 Candidate

次段階のcandidateは、30列すべてと各列のdecision sourceをprivate configで明示し、JDL-origin data rowを構築元に使わない。flag、日付、科目名称、金額、摘要の制御対象semanticsはround-trip rowと一致する。

伝番、科目コード/正式名称、消費税、部門コード等は、JDL source値をコピーせず、official Manual上の任意項目、科目名称によるidentifier alternative、免税、補助/部門なしという根拠でblankにする。このためraw rowには複数列の差分があり、byte-levelで「originだけが唯一の差」とは扱わない。Import結果はgenerator-authored manual semanticsの検証として評価する。

candidate、config、privacy-safe report、manifestは `data/private/experiments/jdl_import/generator_authored_1111/` だけに保存した。この特定artifactは `EVID-JDL-GENERATOR-1111-001` として限定的に実機Import検証済みである。generatorが今後作る別artifactの初期statusは引き続き `GENERATOR_AUTHORED_1111_UNTESTED` とし、成功Evidenceを自動継承しない。

Import後のJDL再Exportでは、candidateの21 fieldsが入力表現のまま保持され、blankだった9 fieldsがnonblank representationになった。これは再Export表現の観測であり、内部保存値やgenerator defaultとは扱わない。

## Generator-Authored 1000 Candidate

次のcandidateは、成功したgenerator-authored `1111` のexplicit configを基に、identifier flagだけを `1000` へ変更した。JDL-origin data rowは構築元に使用していない。伝番はManual上の任意項目としてblankを維持し、他の29 fields、会社条件、target master確認、tax確認を変えていない。

private生成物は `data/private/experiments/jdl_import/generator_authored_1000/` に保存した。この特定artifactは `EVID-JDL-GENERATOR-1000-001` として限定的に実機Import検証済みである。generatorが今後作る別artifactの初期statusは `GENERATOR_AUTHORED_1000_UNTESTED` のままとし、成功Evidenceを自動継承しない。

1000は仕訳帳で1件として確認され、振替伝票画面には表示されなかった。1111が振替伝票画面で確認されたこととの違いは、Manualのidentifier flag semanticsと整合する。再Exportでは21 fieldsが保持され、blankだった同じ9 fieldsがnonblank representationになったが、内部保存値やgenerator defaultとは扱わない。

## 安全条件

- 完全架空データのみ使用する。
- JDL側では必ずテスト会社を使用する。
- Import前にJDL側データをバックアップする。
- JDLの退避確認では、必ず出納帳ファイルを退避する。
- date rangeはEXP-01の対象1仕訳だけに限定する。
- 決算整理は通常仕訳なら「含まない」を第一候補として人間が確認する。
- 「含まない」を仕様として自動固定しない。
- Import rejection時はログ表示からログを保存する。
- rejection時も元帳/仕訳ファイルに変更がないことを確認する。
- 実顧客CSV、実顧客名、実顧客の摘要、実金額を使わない。
- 生成CSVとmanifestは `data/private/experiments/` 配下に置き、Git管理しない。
- JDLエラーログは `data/private/` 配下に保存する。

## 生成内容

- 1仕訳のみ。
- CSV本体はOfficial documented 30-column headerと1 data recordのみ。
- first physical rowは必ずofficial header。
- JDL-origin exportで観測したmetadata/comment/preamble行は入れない。
- JDL仕様上未確認の独自コメント行や独自metadata行は追加しない。
- metadataはCSVではなくprivacy-safe report/manifestへ記録する。
- generatorが作る未試験1000 artifactのstatusは `GENERATOR_AUTHORED_1000_UNTESTED` とする。特定artifactのruntime成功はprivate manifestとEvidence IDで別管理する。

## 事前設定

テンプレートをGit管理外へコピーする。

```bash
mkdir -p data/private/experiments/jdl_import/exp01
cp experiments/jdl_import/exp01_config.template.json \
  data/private/experiments/jdl_import/exp01/config.json
```

`config.json` の最小入力項目を確認する。マニュアルで不要時に空欄可と確認できた項目は、configで省略しても生成時に空欄列として30列に展開される。列そのものは削除されない。

`target_master_validation` の全項目も、JDLテスト会社のマスターを人間が確認して `true` にする。未確認のまま候補CSVを生成しない。

最低限、人間がJDL実機で確認して入力する値:

- 伝番を入力する場合は8桁以内の数字。空欄はManual上の任意項目として明示する
- 日付は `YYYYMMDD`
- 借方科目コード、借方科目名、借方科目正式名称の少なくとも1つ
- 貸方科目コード、貸方科目名、貸方科目正式名称の少なくとも1つ
- 摘要
- 取込先会社の消費税処理が免税、税込処理、税抜処理のどれか
- 課区/税区を使う場合、略称と組み合わせがJDLで有効であること
- 補助、部門、税区分、税入力方法、取引科目を空欄にしてよいか
- 借方科目が取込先JDLマスターに存在すること
- 貸方科目が取込先JDLマスターに存在すること
- 補助科目を使う場合、正しい親勘定科目の下に存在すること
- 補助科目を使わない場合、空欄表現として試す意図が明確であること
- fuzzy matchingや自動置換を行っていないこと

## 生成コマンド

```bash
PYTHONPATH=src python3 -m experiments.jdl_import.exp01_candidate \
  --config data/private/experiments/jdl_import/generator_authored_1000/config.json \
  --output-dir data/private/experiments/jdl_import/generator_authored_1000
```

同名出力がある場合は失敗する。実機試験用candidateはoverwriteせず、再生成が必要なら既存artifactを別途保全してから人間が判断する。

生成物:

- `data/private/experiments/jdl_import/generator_authored_1000/jdl_generator_authored_1000_candidate.csv`
- `data/private/experiments/jdl_import/generator_authored_1000/jdl_generator_authored_1000_candidate.report.json`
- `data/private/experiments/jdl_import/generator_authored_1000/EXP-01_manifest.json`

## 自動検証

生成後、少なくとも以下をself-validationする。

- CP932
- BOMなし
- CRLF
- Official documented Header一致
- 30 columns
- 1 data record
- identifier flag `1000`
- 日付が `YYYYMMDD` 8桁
- 金額parse可能
- 借方合計と貸方合計が一致
- 必須mapping値が明示設定済み
- target master validationが明示確認済み
- 税処理に応じた課区/税区/税入力方法/消費税のrequiredness
- 不要項目は空欄列として出力し、0などを推測入力しない

privacy-safe reportには科目名、補助名、部門名、摘要、個別金額、raw CSV rowを出さない。

## JDL実機で確認するもの

Import後に以下を確認する。

- エラー有無
- 仕訳件数
- 借貸科目
- 金額
- 摘要
- 補助
- 部門
- 税区分
- 元帳/仕訳日記帳での表示

## 結果記録

Import成功時に記録する証拠:

- 実施日時
- JDL製品名/Version
- テスト会社であること
- Import件数
- 元帳/仕訳日記帳で確認した項目
- fingerprint差分

Import失敗時に保存するもの:

- JDL画面のエラーメッセージ
- JDLログファイル
- 生成CSVのprivacy-safe report
- JDL側で退避/復元したかどうか
- 元帳/仕訳ファイルの変更有無

失敗ログはGit管理外の `data/private/` 配下へ保存する。

## production化しない理由

EXP-01はgenerator-authored最小候補を段階検証する実験です。特定のgenerator-authored `1111` / `1000`、貸方補助、借貸両側部門、借方tax表現、3-record compound artifactsは成功しましたが、別の複合構造、複数group、月次大量データ、別Version互換性は確定しません。

Manual evidenceで30-column CSV仕訳入力schemaは確認できた。一方、JDL-origin exportにはpreambleがあるため、Export CSVをそのままImport可能とは扱わない。EXP-01 candidateはpreambleなしで1行目にofficial headerを置く。

過去の1271件rejection UIと既存診断結果は、CSV構造認識後にtarget master mismatch等でwhole importが拒否された可能性と整合する。ただし、補助科目不一致だけが原因とは断定しない。

error-annotated CSVの再解析では、account/subaccount mismatch candidatesがJDL runtime diagnosticとして観測された。EXP-01では、科目・補助科目のtarget master確認を候補生成前の必須条件として扱う。

## JDL会計21列仕訳一覧との関係

JDL会計から取得した21列の仕訳一覧CSVは、EXP-01の30列import candidateとは別構造として扱う。

- 30列JDL出納帳Observed: JDL IBEX出納帳 35.5 import candidate research
- 21列JDL会計仕訳一覧Observed: post-import verification candidate

21列仕訳一覧は、JDLへ取り込んだ後にJDL側で登録された内容をread-onlyに確認するための候補Evidenceであり、30列import formatへ流用しない。

現時点では、21列仕訳一覧から見える項目だけを比較対象候補にする。日付表記、footer行、一覧固有の列、税関連列の意味が未確定な場合は、JDL実機取込後Verificationで `INSUFFICIENT_EVIDENCE` または `PARSE_FAILED` として扱う。

## 次に取得するEvidence

generator-authored `1111` / `1000` minimal candidatesは実機Importと再Exportまで成功した。取込先テスト会社で完全架空の補助科目が既存親勘定科目の直下に登録済みであることを人間が確認し、そのprivate evidenceを用いて貸方補助だけを変更したcandidateを生成した。

このcandidateは全30列をexplicit configで保持し、成功済み1000との差分を `貸方補助` / `貸方補助名称` だけに限定した。`MappingKey`相当の親勘定科目context、no fuzzy matching、no automatic replacementをself-validationした。

実機Importは成功し、`EVID-JDL-GENERATOR-1000-SUBACCOUNT-001` としてこのartifactに限り検証済みとした。candidateの貸方補助numeric representationは `0001`、target masterで人間が実際に登録したcodeは `1`、post-import re-export rawのrepresentationは `1` だった。Manual上の型は数値4桁だが、この結果からleading-zeroの一般規則やgeneratorが出力すべき表現を決めない。

訂正後のprivate configは実験履歴として保持し、再生成入力には使わない。generatorは新規candidateについてcode不一致を正規化せずblockする。

- 失敗時の `ログ表示` 内容とerror CSV
- department実験前に、テスト事業所の部門処理設定と完全架空の部門code/nameを実機確認
- 課区・税区略称一覧
- 取込先会社の消費税処理設定
- 伝票行数上限など会社設定依存項目

### Generator-authored 1000 + department

部門処理を有効化した完全架空テスト事業所で、成功済み補助なし `1000` を基準に借方部門だけを追加したcandidateを生成した。差分は `借方部門コード` / `借方部門名称` の2列だけで、statusは `GENERATOR_AUTHORED_1000_DEPARTMENT_UNTESTED` とする。

登録正式名はofficial 4文字上限を超えるため切り詰めず、JDL画面で別途確認済みの4文字以内の短縮名を `借方部門名称` の実験値として明示設定した。これは実機検証対象の仮説であり、部門名称列が常に短縮名を要求するとは断定しない。貸方部門、借貸の補助、税fieldは空欄を維持する。

実機ではCSV自体はImportされたが、仕訳帳画面でdepartment表示を確認できなかった。初回試行には残存subaccount masterによる別要因errorも含まれたため、この1000実験は `INCONCLUSIVE / NOT VERIFIED` とし、department成功Evidenceへ昇格しない。

借貸両側へ確認済みdepartment code/短縮名を明示したgenerator-authored `1111` 1件は実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-1111-DEPARTMENT-001` として限定的に検証済みとした。candidate/re-export比較ではdepartment 4 fieldsを含む23 fieldsが保持された。UIでは借方部門が見え、貸方部門欄は空欄に見えたため、JDL内部保存やUI表示差、両側入力の一般的requirednessは未確定のままにする。

### 次のtax-inclusive実験

テスト事業所を課税・原則課税・個別対応方式・税込へ変更し、department/subaccountなしの単純仕訳を手入力したraw Exportを取得した。`EVID-JDL-TAX-INCLUSIVE-HAND-1111-001` として、借方課区 `仕　入`（中央U+3000）、借方税区 `10%`、その他のtax classification/input method/transaction accountのblank状態を観測した。

Manual上、課税・税込処理では課区/税区が必要で、税入力方法/消費税は不要とされる。このためgenerator-authored candidateではraw-confirmedな借方課区/税区だけを設定し、税入力方法/消費税はblankにした。self-exportで観測した消費税 `0`、department code `0` は再Export表現であり、candidateへコピーしていない。

この特定candidateは実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-1111-TAX-INCLUSIVE-001` として限定的に検証済みとした。JDLは1件として認識し、1伝票、税区分表示、貸借、摘要、重複なしを確認した。raw比較では21 fieldsが保持され、借方課区のU+3000と借方税区も保持された。blankからnonblankになった9 fieldsは再Export表現であり、generator defaultにはしない。

新しく生成するartifactの初期statusは引き続き `GENERATOR_AUTHORED_1111_TAX_INCLUSIVE_UNTESTED` とする。他の税率/課区/税区、売上側課税、税抜、transaction account、別会社設定へ値を継承しない。次の最小実験は税抜会社設定での手入力・self-export evidence取得であり、そのraw確認前にcandidateを生成しない。

### Tax-exclusive実験

会社設定を課税・原則課税・個別対応方式・税抜へ変更し、operatorが伝票入力UIの入力方式を税抜入力へ切り替えた手入力 `1111` raw Exportを取得した。`EVID-JDL-TAX-EXCLUSIVE-HAND-1111-001` として、借方の課区/税区/税入力方法/消費税が非空、貸方tax classificationと取引科目がblankであることを観測した。UI入力方式とCSV税入力方法は同義化しない。

Manualは税抜時に課区/税区/税入力方法/消費税を必要とし、金額には消費税を含めるとしている。generator candidateはManual requirednessと0820 exact raw valuesの双方を根拠に借方tax fieldsを明示した。通常仕訳の貸方非課税側と取引科目はblankを維持し、self-exportの貸方消費税/部門code `0`はcandidateへ入れていない。

この特定candidateは実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-1111-TAX-EXCLUSIVE-001` として限定的に検証済みとした。raw比較では22 fieldsを保持し、借方tax fieldsはすべて入力表現を保持した。blankからnonblankになった8 fieldsは再Export表現であり、generator defaultにはしない。

新しく生成するartifactの初期statusは引き続き `GENERATOR_AUTHORED_1111_TAX_EXCLUSIVE_UNTESTED` とする。全30 fieldsとdecision sourceを明示し、source row copy、implicit default、値のnormalize、production capabilityへの昇格を禁止する。

### 次のcompound実験

完全架空テスト事業所で3行振替伝票を手入力し、self-export rawから `1110 -> 1100 -> 1101`、同一伝番、同一日付、group貸借一致を再確認した。`EVID-JDL-COMPOUND-HAND-1110-1100-1101-001` として `OBSERVED` に留め、既存 `1110 -> 1100* -> 1101` familyや2-record `1110 -> 1101` を一般仕様へ昇格しない。

このObserved EvidenceとManual requirednessを使い、3 records / 各30 fieldsをexplicit configから作る実験candidateを生成した。生成時statusは `GENERATOR_AUTHORED_COMPOUND_UNTESTED`。伝番はManual上optionalなので全行blankとし、自動採番値を推測しなかった。

候補は免税、補助なし、部門なし、tax fieldsなし。後続2 recordsの借方金額`0`だけは、金額列のManual requirednessとraw observationの両方を根拠とする。self-exportで見えた税額/部門codeの`0`はcandidateへ昇格しない。

この単一candidateは実機Importと再Exportに成功し、`EVID-JDL-GENERATOR-COMPOUND-1110-1100-1101-001`として限定的に検証済みとした。実機は3 recordsを1つの振替伝票へgroupingした。candidate伝番は全行blank、re-exportは全行`0`だったが、複数groupにおけるblank伝番や`0`のgenerator利用へ一般化しない。production capabilityとYayoiからJDLへのREADY判定は変更しない。

次の優先候補は、1 CSV内にsimpleとcompoundを含む複数groupを置き、group boundaryと意図しないmergeの有無を検証する実験である。ただし、複数groupをすべてblank伝番にする安全性は未確認のためcandidateはまだ生成しない。

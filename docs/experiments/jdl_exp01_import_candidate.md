# JDL EXP-01 Import Candidate Experiment

## 目的

EXP-01は、完全架空の最小1仕訳をJDL IBEX出納帳 35.5の `データ管理・選択 -> CSV入力 -> 仕訳データ` 経路で手動Import試験するための研究用手順です。

これは正式JDLOutputAdapterではありません。JDL IBEX 出納帳操作マニュアルP319-P322/P326-P327で確認した `OFFICIAL_DOCUMENTED` schemaと、実CSVから観測したCP932/CRLF/BOMなしserializationを組み合わせた実験です。成功しても即production化しません。

Manual evidenceにより、30列CSV仕訳データ入力schema、1行目header requirement、identifier flag meanings、税処理ごとのconditional requirements、error CSV behaviorは確認済み。ただし、EXP-01 candidateがJDL実機で受理されることは未検証です。

今回観測した操作flow:

1. `データ管理・選択 -> CSV入力`
2. データ種類で `仕訳データ` を選択
3. 取り込むCSVファイルを参照して選択
4. 出納帳ファイルを退避するか確認
5. 取込対象の日付範囲を指定
6. 集計単位と決算整理の扱いを選択
7. 実行

このflowではvisibleなfield mapping UIは観測されていない。ただしfield mapping機能が存在しないとは断定しない。

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
- statusは `EXPERIMENTAL_NOT_VERIFIED_BY_REAL_IMPORT` のまま保持する。

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

- 伝番
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
  --config data/private/experiments/jdl_import/exp01/config.json
```

同名出力がある場合は失敗する。明示的に置換する場合だけ `--overwrite` を付ける。

生成物:

- `data/private/experiments/jdl_import/exp01/EXP-01_jdl_import_candidate.csv`
- `data/private/experiments/jdl_import/exp01/EXP-01_jdl_import_candidate.report.json`
- `data/private/experiments/jdl_import/exp01/EXP-01_manifest.json`

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

EXP-01は1件の最小候補の実験です。成功しても、JDLの正式CSV仕様、複合仕訳、税区分、補助、部門、月次大量データ、別Version互換性はまだ確定しません。

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

- EXP-01 candidateの実Import結果
- 成功時の取込件数確認画面とJDL側登録結果
- 失敗時の `ログ表示` 内容とerror CSV
- 課区・税区略称一覧
- 取込先会社の消費税処理設定
- 伝票行数上限など会社設定依存項目

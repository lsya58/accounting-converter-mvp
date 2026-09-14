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
- real import verification: pending

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

したがって、`JDL自身がExportしたCSVをそのままImport可能` とは扱わない。必要な候補変換としては、Export preambleを除去し、1行目をofficial headerに正規化する処理が考えられるが、実Import成功までは `VERIFIED_BY_REAL_IMPORT` にしない。

## Remaining Blockers

- EXP-01 candidateの実Import成功。
- 取込先テスト会社の科目master確認。
- 補助科目を使う場合の親科目配下登録確認。
- 取込先会社の消費税処理確認。
- 課区・税区略称一覧。
- 日付範囲、伝番、振替伝票行数など会社設定依存項目。

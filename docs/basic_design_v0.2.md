# 会計ソフト間仕訳データ変換システム 基本設計書

- 文書バージョン: 0.3
- 対象リリース: MVP
- 上位文書: 要求仕様書 v0.5 / 要件定義書 v0.5
- 対象変換: 弥生会計 → JDL
- ステータス: 実装進行・実データ検証待ち
- 最終更新日: 2026年8月27日

## 1. 設計目的
本設計は、弥生会計の仕訳データを共通仕訳モデルへ正規化し、検証・マッピング後にJDL取込形式へ出力するローカル変換アプリケーションを定義する。

重要方針:
1. 弥生固有仕様とJDL固有仕様をAdapterへ隔離する。
2. Common Journal Modelを変換の中心に置く。
3. Silent Failureを禁止する。
4. 複合仕訳の採用/非採用のどちらでも共通モデルを変更しない。
5. Mapping処理後に会計上のBusiness Validationを実行する。
6. 検証レポートを任意保存でき、保存をUI上で推奨する。
7. 会計データを外部送信しない。
8. MVPでは弥生1形式・JDL1形式のみ正式対応する。
9. 公式ドキュメント仕様、Observed Behavior、正式FormatProfileを分離する。
10. Application層はオーケストレーションに徹し、CSV列変換や会計ソフト固有仕様を持たない。
11. 部分出力とSilent Failureを禁止する。

## 2. アーキテクチャ

```text
弥生CSV
  |
  v
File / Encoding / CSV Structural Validation
  |
  v
Yayoi Input Adapter
  |
  v
Common Journal Model
  |
  v
Mapping Engine
  |
  v
Business Validation Engine
  |
  v
JDL Output Adapter
  |
  v
Output Validation
  |
  +--> Atomic Save -> JDL取込CSV
  |
  +--> Verification Report
```

現在の実装では、正式YayoiInputAdapterと正式JDLOutputAdapterは未実装である。ConversionServiceはDemo AdapterによりE2Eテスト済みであり、正式Adapterは実データ取得後に接続する。

### 2.1 Validationの二段階化

**Pre-Mapping Structural Validation**
- ファイル存在
- CSV構文
- 文字コード
- 必須列
- 日付解析可能性
- 仕訳識別構造
- 複合仕訳らしき構造の検出

**Post-Mapping Business Validation**
- 未解決マッピング
- 勘定科目
- 補助科目
- 税区分
- 貸借一致
- 金額完全性
- JDL表現可否
- 文字数制約

MappingとBusiness Validationを並列実行しない。

## 3. 対応形式・バージョン方針

### 3.1 MVP
MVPでは以下を1形式ずつ正式対応する。
- 弥生: 1製品/1出力形式
- JDL: 1製品/1取込形式

対象製品・バージョンは実データ確認後にFormatProfileとして確定する。

現在、弥生については公式サポート文書「弥生取り込み（インポート）形式（弥生会計05以降）」の25項目仕様を `OFFICIAL_DOCUMENTED` / `REAL_DATA_VERIFICATION_PENDING` として保持している。これは正式FormatProfileではない。

JDLについては、JDL IBEX出納帳 35.5 の実データからObserved SchemaとObserved Behaviorを診断機能で確認している。これは正式JDL FormatProfileではない。

### 3.2 FormatProfile
ソフト固有のフォーマット差異をAdapter内部のif分岐へ埋め込まず、FormatProfileとして分離する。

```text
FormatProfile
- software
- product
- version
- format_id
- encoding
- delimiter
- columns
- required_fields
- date_format
- journal_structure
- max_lengths
```

将来的にバージョンを追加する際は、新しいProfileまたは必要に応じて専用Adapterを追加し、既存Profileを書き換えない。

## 4. 主要コンポーネント

### CMP-01 FileController
- 入力選択
- 出力保存
- 元ファイル保護

### CMP-02 EncodingDetector
- 文字コード判定
- 情報損失検出

### CMP-03 CSVParser
- CSV構文のみを担当
- 会計ロジックを持たない

### CMP-04 YayoiInputAdapter
- Profile判定
- 弥生列→共通モデル変換
- 仕訳識別情報取得
- 複合構造候補検出

現在は未有効化。実データ取得後に正式実装する。

### CMP-04a YayoiOfficialSpecification
- 弥生公式ドキュメント上の25項目仕様を保持
- 識別フラグ `2000` / `2111` / `2110` / `2100` / `2101` を保持
- `OFFICIAL_DOCUMENTED`
- `REAL_DATA_VERIFICATION_PENDING`
- 正式YayoiInputAdapterとしては有効化しない

### CMP-05 JournalBuilder
- 入力レコード群からJournalEntryを構築

### CMP-06 MappingEngine
- 科目/補助科目/税区分/部門の対応付け
- 不明値を推測確定しない

### CMP-07 StructuralValidationEngine
- Mapping前の構造検証

### CMP-08 BusinessValidationEngine
- Mapping後の会計検証

### CMP-09 JDLOutputAdapter
- 共通モデル→JDL形式

### CMP-10 OutputValidator
- 生成CSVの自己再検証

### CMP-11 VerificationReportGenerator
- 変換検証レポート生成

### CMP-12 SessionManager
- 一時データ
- セッション内マッピング
- 終了時削除

### CMP-13 ConversionService
- InputAdapter、Validation、Mapping、OutputAdapter、OutputValidator、VerificationReportGeneratorを統括
- CSV列変換や会計ソフト固有仕様を持たない
- Error/Fatal/未解決Mapping/Output Validation失敗時は正式出力しない
- 一時ファイルへ出力後、成功時のみatomic replace
- 既存出力ファイルはデフォルトで上書きしない
- input path == output pathを拒否

### CMP-14 JdlCsvDiagnosticAnalyzer
- JDL取込失敗CSVの構造診断
- JDL診断メッセージ解析
- マスター不一致候補集計
- Schema Fingerprint生成
- Observed Schema保持
- Observed Journal Group Candidate検出
- 変換コアや正式JDL Output Adapterとは独立

## 5. 共通仕訳モデル

### 5.1 JournalEntry
```text
JournalEntry
- id
- source_reference
- date
- description
- lines[]
- metadata
```

### 5.2 JournalLine
```text
JournalLine
- side
- account
- sub_account
- department
- amount
- tax_info
- source_reference
```

金額は浮動小数点ではなく、整数円または10進型で扱う。

### 5.3 TaxInfo
将来のMF/freee等で税区分の意味が増えても共通モデルを壊しにくくするため、単一文字列ではなく構造化する。

```text
TaxInfo
- category
- rate
- tax_inclusion
- reduced_rate
- invoice_classification
- tax_amount
- metadata
```

各項目はoptionalとし、MVPでは実仕様で必要な項目のみ使用する。

明細税額を保持する必要性は弥生/JDL実仕様確認後に確定する。

### 5.4 SourceReference
```text
SourceReference
- file_name
- row_number
- source_journal_id
```

出力/エラーから元弥生仕訳まで追跡できること。

## 6. 複合仕訳

Common Journal Modelは最初から複数JournalLineを保持する。

### RD-03採用時
複数行を1 JournalEntryとして構築する。

### RD-03非採用時
複合仕訳らしき構造をStructural Validationで検出し、VR-15としてError化する。
単純仕訳へ分解しない。

## 7. Mapping

### MappingStatus
- RESOLVED
- UNRESOLVED
- USER_CONFIRMED

### MappingRule
入力値と出力値の単純な1:1変換のみを前提にしない。
詳細設計前に、税区分について以下を確認する。
- 1:1
- 多対1
- 1対多
- 条件付き変換

複数属性を必要とする場合はTaxInfoを入力として変換ルールを評価する。

## 8. ValidationResult

```text
ValidationResult
- severity
- rule_id
- journal_id
- source_reference
- field
- input_value
- message
- suggested_action
```

Severity:
- INFO
- WARNING
- ERROR
- FATAL

正式出力条件:
- ERROR = 0
- FATAL = 0
- unresolved mapping = 0

## 9. 重複データ

仕訳内容が同一という理由だけで重複と判断・削除しない。

実取引として同内容の仕訳が複数存在する可能性があるためである。

ただし、入力仕様上「一意であることが保証された仕訳ID」が存在する場合、そのIDの重複検出を追加できる。

MVPでの重複検出採否は実CSV確認後に確定する。

## 10. 処理シーケンス

```text
User
 |
 v
Select Yayoi CSV
 |
 v
File / Structural Validation
 |
 v
Yayoi Input Adapter
 |
 v
Common Journal Model
 |
 v
Mapping Engine
 |
 v
Business Validation
 |
 +--> Error -> UI -> User mapping correction -> Re-validation
 |
 v
JDL Output Adapter
 |
 v
Temporary Output File
 |
 v
Output Validation
 |
 +--> Error -> Output failure
 |
 v
Atomic Replace
 |
 v
Result Preview
 |
 +--> Save JDL CSV
 |
 +--> Save Verification Report
```

正式出力停止条件:

- Structural Error >= 1
- Fatal >= 1
- unresolved mapping >= 1
- Business Error >= 1
- Output Validation失敗
- 予期しない例外
- 既存出力ファイルがあり、上書き許可がない
- input path == output path

停止時は正式出力を生成せず、一時ファイルを削除する。正常な一部仕訳だけを部分出力しない。

## 11. 画面構成

### SCR-01 ファイル選択
- 入力ファイル
- 対応形式
- 読込

### SCR-02 読込結果
- レコード数
- 仕訳数
- 貸借合計
- 複合構造の有無

### SCR-03 マッピング/エラー
- 元行
- 仕訳
- 項目
- 入力値
- 問題
- 対応

### SCR-04 変換確認
- 入力仕訳数
- 出力予定数
- 借方/貸方総額
- Error
- Warning
- 未解決Mapping

Error=0の場合のみ生成可能。

### SCR-05 完了
- JDL CSV保存
- 「検証レポートも保存する（推奨）」をデフォルトON
- 検証結果表示

検証レポート保存をOFFにして完了する場合、以下の趣旨の確認を表示する。

「検証レポートを保存しない場合、JDL取込エラー発生時に変換時の検証結果を確認できなくなります。保存せず終了しますか？」

保存は強制しない。

## 12. 検証レポート

保存項目:
- 実行日時
- アプリバージョン
- 入力/出力ファイル名
- 対象FormatProfile
- 入力/出力仕訳数
- 入力/出力レコード数
- 借方/貸方総額
- Error/Warning件数
- 未解決Mapping件数
- JDL形式検証結果
- ConversionStatus
- Output Validation結果

会計本文は原則含めない。

表現:
「本システムが検証可能なデータ項目についてエラーは検出されませんでした。」

「JDL側が原因」と断定しない。

## 13. 一時データ/アクセス権

一時データはWindowsの現在ログインユーザー専用領域に保存する。

原則:
- OSユーザープロファイル配下
- 共有フォルダを使用しない
- アプリケーションのインストールフォルダへ保存しない
- 他OSユーザーから通常アクセスできない領域を利用する

終了時削除:
- 入力内部コピー
- 中間仕訳
- 一時Mapping
- 仮出力
- 一時レポート

削除対象外:
- 利用者保存済みJDL CSV
- 利用者保存済み検証レポート

異常終了時残存データは次回起動時に削除対象とする。

## 14. ログ
記録可能:
- 日時
- アプリバージョン
- 処理段階
- rule_id
- 元行番号
- 例外種別

記録禁止:
- 摘要全文
- 取引先名
- 個別仕訳金額
- 口座情報
- 会計本文

## 15. セキュリティ
- ローカル完結
- 通常処理中の外部通信なし
- Web API不要
- 生成AI API不要
- テレメトリ不要
- クラウド保存不要

## 16. 将来拡張

### 16.1 MoneyForward/freee追加
追加対象:
- MoneyForwardInputAdapter / FreeeInputAdapter
- 対応FormatProfile
- ソフト固有Mapping定義

原則変更なし:
- Common Journal Model
- Validation
- JDLOutputAdapter
- VerificationReport
- 主要UIフロー

### 16.2 バージョン追加
Adapter内へifを増殖させず、Profile追加を第一候補とする。
構造差が大きい場合のみ専用Adapterを追加する。

### 16.3 税区分
TaxInfoで意味を保持し、単純なsource_tax_category -> target_tax_category文字列変換だけへ依存しない。

## 17. 論理ディレクトリ

```text
src/accounting_converter/
├─ adapters/
│  ├─ input/base.py
│  └─ output/base.py
├─ application/
│  ├─ conversion.py
│  ├─ mapping_engine.py
│  ├─ output_validation.py
│  ├─ validation_pipeline.py
│  └─ verification_report.py
├─ diagnostics/
│  └─ jdl_csv/
├─ domain/
│  ├─ journal.py
│  ├─ mapping.py
│  ├─ profile.py
│  └─ validation.py
├─ profiles/
│  └─ yayoi_official.py
└─ infrastructure/

tests/
├─ fixtures/
│  ├─ jdl/
│  └─ yayoi/
├─ support/
├─ test_conversion_service_e2e.py
├─ test_jdl_csv_diagnostics.py
├─ test_jdl_csv_diagnostics_integration.py
├─ test_yayoi_official_spec.py
├─ test_journal.py
└─ test_validation.py
```

## 18. テスト方針

### Unit
- CSV
- FormatProfile
- 弥生公式仕様モデル
- JournalBuilder
- Mapping
- Structural Validation
- Business Validation
- TaxInfo
- JDL Adapter
- Report Generator

### Integration
- 弥生CSV→共通モデル
- 共通モデル→Mapping→Validation
- 共通モデル→JDL CSV
- VerificationReport内容検証
- JDL CSV Diagnostic Analyzer
- Demo CSV→ConversionService→Demo Output

### E2E
実データ取得前は完全架空デモデータでConversionServiceのE2Eを検証する。

実データ取得後に、匿名化弥生CSV → アプリ → JDL取込を追加する。

### CI

GitHub Actionsでpush / pull_request時に以下を実行する。

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Git管理対象CSVは `tests/fixtures/` 配下のみ許可する。実顧客CSV、実JDL CSV、実弥生CSV、`data/private/` 配下はGit管理対象にしない。

## 19. 技術方針
- Windowsデスクトップを第一候補
- ローカル処理
- 外部サーバーなし
- CSV中心
- 実装言語/GUIライブラリの最終バージョンは実装環境確認時に固定する

初期実装はドメイン/変換コアをUIから独立して構築する。

## 20. 設計上の禁止事項
1. 弥生→JDLの巨大if直変換
2. バージョンifのAdapter内乱立
3. CSV処理と会計ロジックの密結合
4. 不明科目/税区分の自動確定
5. Errorの無視
6. 部分出力
7. 元CSV変更
8. 自動切り捨て
9. 複合仕訳の無断分解
10. 同内容仕訳の自動重複削除
11. 外部AIへの会計データ送信

## 21. 詳細設計前の未確定事項
- 弥生製品/バージョン/CSV
- JDL製品/バージョン/取込仕様
- JDL正常取込サンプル
- 税区分の多重度
- 明細税額保持の要否
- 複合仕訳採否
- 重複仕訳ID検出可否
- 日付形式
- 文字コード
- 最大文字数
- 実務最大レコード数
- 検証レポート正式形式

## 22. 実装着手範囲
実CSV仕様確認前でも実装可能な以下から着手する。
1. Common Journal Model
2. TaxInfo
3. SourceReference
4. MappingStatus/Mapping構造
5. ValidationResult/Severity
6. InputAdapter/OutputAdapter境界
7. FormatProfile
8. Structural/Business Validation基盤
9. テスト骨格

弥生/JDL固有の列マッピングは実CSV確認後に実装する。

---

## 23. 現在の実装状態

2026年8月27日時点:

- 自動テスト: 80件成功
- ConversionService E2E: 完全架空デモデータで確認済み
- JDL診断: デモデータとJDL IBEX出納帳35.5実データでObserved Behavior確認済み
- 弥生仕様: 公式ドキュメント25項目仕様を仕様モデルとして保持、正式Adapter未有効化
- CI: Python 3.12、unittest、CSV漏洩防止チェック

未確定:

- 使用中の弥生製品・バージョン
- 弥生実出力CSV
- JDL正式取込仕様
- JDL正常取込サンプル
- 税区分・補助科目・部門の実マッピング
- 複合仕訳採否

これらの確定後、正式YayoiInputAdapter、正式JDLOutputAdapter、正式FormatProfileを実装する。

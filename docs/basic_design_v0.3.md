# 会計ソフト間仕訳データ変換システム 基本設計書

- 文書バージョン: 0.3
- 対象リリース: MVP
- 上位文書: 要求仕様書 v0.6 / 要件定義書 v0.6
- 対象変換: 弥生会計 -> JDL
- ステータス: 実装進行・実データ検証待ち
- 最終更新日: 2026年9月2日
- 変更元: basic_design_v0.2.md

## 1. 設計目的

本設計は、他社会計ソフトに存在する日々の全仕訳を、税理士事務所が普段使用するJDLへ安全に取り込むためのローカル変換アプリケーションを定義する。

MVPの対応経路は弥生会計 -> JDLに限定する。一方、製品アーキテクチャは弥生専用に固定せず、Input Adapter、Common Journal Model、Mapping / Validation、Output Adapterを分離したvendor-neutralな構造を維持する。

重要方針:

1. 弥生固有仕様とJDL固有仕様をAdapterへ隔離する。
2. Common Journal Modelを変換の中心に置く。
3. Silent Failureを禁止する。
4. 保存済みConversion Profileまたは明示確認済みRuleのみ自動適用する。
5. 未知Mappingは推測補完せず、変換停止・ユーザー確認・Profile更新・再実行とする。
6. 会計データを外部送信しない。
7. 仕訳本文・金額・摘要本文・実会計ファイルをProfileへ保存しない。
8. 公式ドキュメント仕様、Observed Behavior、正式FormatProfileを分離する。
9. Application層はオーケストレーションに徹し、CSV列変換や会計ソフト固有仕様を持たない。
10. 部分出力とSilent Failureを禁止する。
11. FormatIdentityとEvidenceLevelにより、製品・バージョン・方向・根拠を区別する。
12. Compatibility ReportとTransformation Planは変換要否を示すが、未知Mapping値を推測しない。
13. Presentation層はApplication層を呼び出すだけとし、CSV parsing、Mapping、Validation、Format判定を重複実装しない。
14. 変換前準備はCompatibility、Mapping確認、Adapter可用性、Lossinessを統合したReadinessで判定する。

## 2. アーキテクチャ

```text
仕訳データファイル(.csv/.txt等)
  |
  v
File / Encoding / Structural Validation
  |
  v
Input Adapter + FormatProfile
  |
  v
Common Journal Model
  |
  v
Conversion Profile
  |
  v
Mapping Engine
  |
  v
Business Validation Engine
  |
  v
Output Adapter + FormatProfile
  |
  v
Temporary Output File
  |
  v
Output Validation
  |
  +--> Atomic Save -> JDL取込ファイル
  |
  +--> Verification Report
```

入力は「対応する仕訳データファイル」として扱う。`.csv` や `.txt` などの拡張子だけでフォーマットを断定せず、FormatProfileに基づいて判定する。

現在の実装では、正式YayoiInputAdapterと正式JDLOutputAdapterは未実装である。ConversionServiceはDemo AdapterによりE2Eテスト済みであり、正式Adapterは実データ取得後に接続する。

### 2.1 Presentation層

`accounting_converter.ui` はWindows向けデスクトップアプリの薄いGUIプロトタイプである。標準ライブラリの `tkinter` を使用し、Electron、Web server、Cloud serviceは使用しない。

責務:

- Conversion Profile一覧表示
- 入力ファイル選択
- 弥生/JDL CSV診断の呼び出し
- Preflight結果表示
- 正式Adapter未登録時の変換ボタン無効化

GUIに実装しないもの:

- CSV列変換
- 会計ソフト固有のFormat判定
- Mapping推測
- Validation本体
- 正式変換のダミー成功処理

Controller/ViewModelはheadless test可能な構造とし、GUI widget依存をApplication判断から分離する。

## 3. 対応形式・バージョン方針

### 3.1 MVP

MVPでは以下を1形式ずつ正式対応する。

- 弥生: 1製品/1出力形式
- JDL: 1製品/1取込形式

対象製品・バージョンは実データ確認後にFormatProfileとして確定する。

弥生については公式サポート文書「弥生取り込み（インポート）形式（弥生会計05以降）」の25項目仕様を `OFFICIAL_DOCUMENTED` / `REAL_DATA_VERIFICATION_PENDING` として保持している。これは正式FormatProfileではない。

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
- file_extensions
- columns
- required_fields
- date_format
- journal_structure
- max_lengths
```

FormatProfileは拡張子を参考情報として持てるが、拡張子だけで形式を正式判定しない。

## 4. Conversion Profile

Conversion Profileは、同じ顧問先や同じ変換条件を翌月以降再利用するためのローカル保存設定である。旧v0.2の「Session-only Mapping」方針を見直し、MVPでは安全に確定したMappingを保存可能にする。

保存可能:

- profile_id
- profile_name
- input_format_profile_id
- output_format_profile_id
- account mappings
- sub account mappings
- department mappings
- tax category mappings
- user confirmed conversion rules
- created_at / updated_at

保存禁止:

- 仕訳本文
- 個別仕訳金額
- 摘要本文
- 取引先名
- 実会計ファイルそのもの
- JDL取込エラーログ本文

Profileはローカルのみで保存する。クラウド同期、外部送信、外部AI送信は行わない。

WindowsではProfileStoreの既定保存先として `%LOCALAPPDATA%/AccountingConverter/profiles` を優先する。Windows以外、CI、開発環境ではテスト用一時ディレクトリを注入可能とし、実ホームディレクトリを汚さない。

## 5. Format Identity / Capability / Schema

FormatIdentity:

- vendor
- product
- edition
- major_version
- minor_version
- version_range
- format_name
- format_version
- direction
- evidence_level
- source_reference
- verified_at
- notes

EvidenceLevel:

- OFFICIAL_DOCUMENTED
- OBSERVED
- VERIFIED_BY_REAL_IMPORT
- INFERRED
- UNKNOWN

FormatCapabilitiesは `UNKNOWN`、`SUPPORTED`、`UNSUPPORTED`、`CONDITIONAL` を区別する。未確認をFalseとして扱わない。

SchemaDefinitionは会計上のsemantic fieldとCSV上の物理列を分離する。例として、semantic field `DEBIT_ACCOUNT` と、Yayoi column 5 / JDL observed column X は別のFieldDefinitionで表現する。

## 6. Format Registry

FormatRegistryはSchemaDefinitionを一元登録し、vendor/product/direction/evidence_levelで検索できる。

`find_candidates(file_observation)` は候補とconfidenceを返すだけで、CSVだけを見て製品/versionを自動確定しない。

## 7. Compatibility / Transformation Plan

FormatCompatibilityAnalyzerはSource SchemaとTarget Schemaをvendor-neutralに比較する。

分類:

- DIRECT
- NORMALIZATION_REQUIRED
- MAPPING_REQUIRED
- DEFAULT_REQUIRED
- STRUCTURAL_TRANSFORMATION_REQUIRED
- UNSUPPORTED
- UNKNOWN
- HUMAN_CONFIRMATION_REQUIRED

Lossiness:

- LOSSLESS
- LOSSY
- UNKNOWN

TransformationPlanは `COPY`、`REORDER`、`NORMALIZE_TEXT`、`DATE_FORMAT`、`NUMERIC_FORMAT`、`MASTER_MAPPING`、`TAX_MAPPING`、`DEFAULT_VALUE`、`GROUPING_TRANSFORMATION`、`DROP_WITH_CONFIRMATION`、`UNSUPPORTED`、`UNKNOWN` などのStep候補を保持する。

ACCOUNTやTAXの実Mapping値は推測しない。

## 8. Normalization Rule

NormalizationRuleは以下を区別する。

- SAFE_TEXT_NORMALIZATION
- ACCOUNTING_SEMANTIC_MAPPING

SAFE_TEXT_NORMALIZATIONは、Unicode normalization、明示設定された全角/半角変換、line ending、encodingなどを対象とする。

ACCOUNTING_SEMANTIC_MAPPINGは、勘定科目、補助科目、税区分、部門などを対象とし、原則としてMapping/Profileによる明示確認を必要とする。

## 9. Mapping

### MappingStatus

- RESOLVED
- UNRESOLVED
- USER_CONFIRMED
- OBSOLETE

保存済みProfile内の `RESOLVED` / `USER_CONFIRMED` Mappingは自動適用できる。未登録の入力値が出現した場合は `UNRESOLVED` とし、ConversionServiceは正式出力を停止する。

名称類似、全角/半角、コード類似、AI推定だけで未知Mappingを自動確定しない。

### Context-aware Subaccount Mapping

補助科目は、同じ「本店」「カード」「その他」等の名称でも親勘定科目により意味やコードが異なる可能性がある。このため、補助科目Mappingは必要に応じて以下のcontext-aware keyで扱う。

```text
MappingKey
- mapping_type = SUBACCOUNT
- source_value
- parent_account
```

side（DEBIT/CREDIT）は出現位置の観測情報としてMappingRequirement / Reviewへ保持できるが、Mapping identityには含めない。同じ親勘定科目・同じ補助科目であれば、借方/貸方に出現してもユーザーへ二重確認させない。

勘定科目、部門、税区分は現時点では単純なsource_value keyを維持する。補助科目identityの意味変更を旧Profileへ黙って適用しないため、Conversion Profile schema_versionは `3` とし、旧 `1` / `2` はunsupportedとして扱う。

## 9.1 Mapping Review / Confirmation

`MappingRequirementExtractor` はCommon Journal Modelから、今回のファイルでMappingが必要になり得る値を抽出する。

抽出対象:

- accounts
- subaccounts
- departments
- tax_categories

各Requirementはmapping_type、source_value、occurrence_count、current_mapping_status、current_target_value、requires_confirmationを持つ。補助科目はparent_account、observed side、source row reference countを保持できる。

`MappingConfirmationService` はユーザーが明示的にsource -> targetを確認した場合だけ、MappingValueを `USER_CONFIRMED` としてConversionProfileStore経由で保存する。Profile JSONを直接書き換えない。

Mapping Review / Readiness / Compatibility Reportには摘要全文、金額、個別仕訳本文を保存しない。

## 9.2 Conversion Preparation / Readiness

`ConversionPreparationService` はConversionService実行前に以下を行う。

1. Compatibility analyze
2. TransformationPlan生成
3. Mapping requirements抽出
4. Profile preflight
5. Transformation support評価
6. Adapter availability確認
7. Lossiness確認
8. Readiness判定

Readiness status:

- READY
- REQUIRES_MAPPING
- REQUIRES_CONFIRMATION
- FORMAT_MISMATCH
- PROFILE_INVALID
- ADAPTER_UNAVAILABLE
- UNSUPPORTED_TRANSFORMATION
- LOSSY_CONFIRMATION_REQUIRED
- VALIDATION_FAILED
- UNKNOWN

`TransformationPlan` のStepは、差分や必要処理を示す候補であり、現在実装可能であることを意味しない。`TransformationSupportStatus` により `SUPPORTED`、`SUPPORTED_WITH_PROFILE`、`REQUIRES_CONFIRMATION`、`ADAPTER_RESPONSIBILITY`、`UNSUPPORTED`、`UNKNOWN` を区別する。

CompatibilityReport.overall_lossiness が `LOSSY` の場合、通常のREADYにはせず `LOSSY_CONFIRMATION_REQUIRED` として停止する。

PreparationがREADYでも、ConversionService内のStructural Validation、Mapping block、Business Validation、Output Validation、Atomic Output、Overwrite safety、Verification Reportは削除しない。Defense-in-depthを維持する。

## 9.3 Adapter Registry

`AdapterRegistry` は正式Adapter追加後にvendor/productのif分岐を増やさないための登録・解決基盤である。

最低限以下を提供する。

- register_input
- register_output
- get_exact_input
- get_exact_output
- find_input_candidates
- find_output_candidates
- has_conversion_pair

AdapterはFormatIdentityに紐づくfactoryとして登録する。statefulなAdapter instanceを永続保持しない。exact、candidate、unavailableを区別し、candidateを自動採用しない。

Output Adapterは本番実行では `VERIFIED_BY_REAL_IMPORT` を基本条件とする。`OBSERVED` / `INFERRED` だけのOutput Adapterはproduction conversion可能として扱わない。Input Adapterについては公式ドキュメント仕様で登録できる余地を残すが、実CSV観測やAdapter契約テストで確認する。

## 10. Validation

### Pre-Mapping Structural Validation

- ファイル存在
- CSV/TXT等の構文
- 文字コード
- 必須列
- 日付解析可能性
- 仕訳識別構造
- 複合仕訳らしき構造の検出

### Post-Mapping Business Validation

- 未解決Mapping
- 勘定科目
- 補助科目
- 税区分
- 貸借一致
- 金額完全性
- JDL表現可否
- 文字数制約

MappingとBusiness Validationを並列実行しない。

## 11. 処理シーケンス

```text
User
 |
 v
Select Journal Data File
 |
 v
Select Conversion Profile
 |
 v
File / Structural Validation
 |
 v
Input Adapter
 |
 v
Common Journal Model
 |
 v
Mapping Engine
 |
 +--> Unknown Mapping -> Stop -> User confirmation -> Profile update -> Re-run
 |
 v
Business Validation
 |
 +--> Error -> Stop
 |
 v
Output Adapter
 |
 v
Temporary Output File
 |
 v
Output Validation
 |
 +--> Error -> Delete temporary file -> Stop
 |
 v
Atomic Save
 |
 v
Verification Report
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

## 12. 想定UX

### 初回変換

```text
弥生仕訳ファイル
↓
解析
↓
JDLとの差異検出
↓
Mapping確認
↓
Conversion Profile保存
↓
変換
↓
検証
↓
JDL取込ファイル生成
```

### 翌月以降

```text
弥生仕訳ファイル
↓
保存済みConversion Profile選択
↓
自動検証
↓
問題なし
↓
1回の変換操作
↓
JDL取込ファイル生成
```

「ワンクリック」は初回設定を不要にする意味ではない。初回や未知Mapping出現時は人間の確認を要求する。一度安全に設定した対応関係を翌月以降再利用し、通常月の操作を減らすことを目標とする。

## 13. 主要コンポーネント

### CMP-01 FileController

- 入力選択
- 出力保存
- 元ファイル保護
- 拡張子だけで形式を断定しない

### CMP-02 EncodingDetector

- 文字コード判定
- 情報損失検出

### CMP-03 Parser

- CSV/TXT等の構文を担当
- 会計ロジックを持たない

### CMP-04 InputAdapter

- Profile判定
- 入力列 -> 共通モデル変換
- 仕訳識別情報取得
- 複合構造候補検出

正式YayoiInputAdapterは未有効化。実データ取得後に正式実装する。

### CMP-05 JournalBuilder

- 入力レコード群からJournalEntryを構築
- record countとjournal countを混同しない

### CMP-06 ConversionProfileRepository

- Conversion Profileの作成、保存、選択、更新、削除
- ローカル保存のみ
- 会計本文を保存しない
- JSON形式で保存
- temp file -> validation -> atomic replaceで保存
- unsupported schema_versionを拒否
- import時に同一IDを黙って上書きしない

### CMP-07 MappingEngine

- Profile内Mappingの適用
- 未知Mappingの検出
- 推測確定禁止

### CMP-08 StructuralValidationEngine

- Mapping前の構造検証

### CMP-09 BusinessValidationEngine

- Mapping後の会計検証

### CMP-10 OutputAdapter

- 共通モデル -> 出力形式

正式JDLOutputAdapterは未有効化。JDL正常取込サンプル確認後に正式実装する。

### CMP-11 OutputValidator

- 生成ファイルの自己再検証

### CMP-12 VerificationReportGenerator

- 変換検証レポート生成
- 会計本文を原則含めない

### CMP-13 ConversionService

- InputAdapter、Validation、Mapping、OutputAdapter、OutputValidator、VerificationReportGeneratorを統括
- CSV列変換や会計ソフト固有仕様を持たない
- Error/Fatal/未解決Mapping/Output Validation失敗時は正式出力しない
- 一時ファイルへ出力後、成功時のみatomic replace
- 既存出力ファイルはデフォルトで上書きしない
- input path == output pathを拒否

### CMP-14 Diagnostics

- JDL CSV Diagnostic Analyzer
- Yayoi CSV Observation / Diagnostics

診断機能は正式Adapterや変換コアと密結合させない。Observed Behaviorを正式FormatProfileへ自動昇格しない。

### CMP-15 FormatRegistry

- FormatIdentity付きSchemaDefinitionの登録
- 候補検索
- 自動確定ではなく人間確認用confidenceを返す

### CMP-16 FormatCompatibilityAnalyzer

- Source SchemaとTarget Schemaの差分比較
- CompatibilityReport生成
- LOSSLESS / LOSSY / UNKNOWN判定
- TransformationPlan生成

### CMP-17 Adapter Contract Tests

- InputAdapter / OutputAdapterが守るべき安全条件を共通テストとして提供
- 新Adapter追加時に再利用する

### CMP-18 ConversionPreflightService

- source/target FormatIdentity照合
- Profile schema_version確認
- 保存済みMappingで解決できない未知Mappingの検出
- READY / REQUIRES_MAPPING / FORMAT_MISMATCH / PROFILE_INVALID / UNSUPPORTED / UNKNOWNを返す
- 実際の弥生/JDL変換は行わない

## 14. 画面構成

### SCR-01 ファイル選択

- 入力仕訳データファイル
- Conversion Profile選択
- 読込

### SCR-02 読込結果

- レコード数
- 仕訳数
- 貸借合計
- 複合構造の有無
- Profile一致状況

### SCR-03 Mapping / Error

- 元行
- 項目
- 入力値
- 未解決Mapping
- ユーザー確認
- Profile更新

### SCR-04 変換確認

- 入力仕訳数
- 出力予定数
- 借方/貸方総額
- Error
- Warning
- 未解決Mapping

Error=0かつ未解決Mapping=0の場合のみ生成可能。

### SCR-05 完了

- JDL取込ファイル保存
- Verification Report保存
- Profile更新結果表示

## 15. 検証レポート

保存項目:

- 実行日時
- アプリバージョン
- 入力/出力ファイル名
- 対象FormatProfile
- 使用Conversion Profile
- 入力/出力仕訳数
- 入力/出力レコード数
- 借方/貸方総額
- Error/Warning件数
- 未解決Mapping件数
- Output Validation結果
- ConversionStatus

会計本文は原則含めない。

## 16. セキュリティ

- ローカル完結
- 通常処理中の外部通信なし
- Web API不要
- 生成AI API不要
- テレメトリ不要
- クラウド保存不要
- 実顧客CSVのGit管理禁止
- `tests/fixtures/` 配下以外のCSVのGit管理禁止
- Conversion Profileへの会計本文保存禁止

## 17. 将来拡張

### 17.1 入力元追加

- MoneyForwardInputAdapter
- FreeeInputAdapter
- その他会計ソフトInputAdapter

原則変更なし:

- Common Journal Model
- Mapping
- Validation
- OutputAdapter境界
- VerificationReport
- Conversion Profileの概念

### 17.2 出力先追加

市場検証後、必要ならJDL以外の出力先ソフトもOutputAdapterとして追加する。

## 18. 論理ディレクトリ

```text
src/accounting_converter/
├─ adapters/
├─ application/
│  ├─ compatibility.py
│  └─ profile_preflight.py
├─ diagnostics/
│  ├─ jdl_csv/
│  └─ yayoi_csv/
├─ domain/
│  ├─ format_metadata.py
│  └─ normalization.py
├─ profiles/
│  ├─ known_formats.py
│  └─ registry.py
├─ infrastructure/
│  └─ conversion_profile_store.py

tests/
├─ fixtures/
│  └─ canonical/
├─ support/
│  ├─ adapter_contracts.py
│  └─ canonical_dataset.py
└─ test_*.py
```

## 19. 現在の未確定事項

- 実際に使用する弥生製品/バージョン
- 実際の弥生エクスポート形式
- 正式YayoiInputAdapter
- 正式YayoiFormatProfile
- 正式JDLOutputAdapter
- 正式JDLFormatProfile
- 税区分Mapping
- JDLへの正常取込条件
- Conversion Profileの正式保存形式
- Conversion Profileの保存場所
- Profile管理UI

Observed Dataや公式文書から推測して正式仕様へ昇格しない。

## 20. 現在の実装状態

2026年9月2日時点:

- ConversionService E2Eは完全架空デモデータで確認済み
- JDL診断はデモデータとJDL IBEX出納帳35.5実データでObserved Behavior確認済み
- 弥生仕様は公式ドキュメント25項目仕様を仕様モデルとして保持、正式Adapter未有効化
- Yayoi CSV Observation / Diagnosticsを追加済み
- FormatIdentity / FormatCapabilities / SchemaDefinitionの拡張基盤を追加済み
- FormatRegistry / CompatibilityReport / TransformationPlanの基盤を追加済み
- Adapter Contract Test helperとCanonical Synthetic Datasetを追加済み
- Conversion Profileローカル永続化基盤を追加済み
- ConversionPreflightServiceを追加済み
- CIはPython 3.12、unittest、CSV漏洩防止チェック

正式YayoiInputAdapter、正式JDLOutputAdapter、正式FormatProfile、Conversion Profile管理GUIは、実CSV・JDL正常取込サンプル・保存方式確認後に実装する。

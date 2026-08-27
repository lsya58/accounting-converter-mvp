# Accounting Converter MVP

弥生会計の仕訳データを共通仕訳モデルへ正規化し、JDL取込形式へ安全に変換するためのMVP実装です。

## 現在の実装範囲

実CSV仕様未確定でも実装できるコアから着手しています。

- Common Journal Model
- TaxInfo
- SourceReference
- FormatProfile
- InputAdapter / OutputAdapter境界
- ValidationResult / Severity
- BalanceRule
- 未対応複合仕訳の安全側Error化
- Application ConversionService
- MappingEngine基盤
- OutputValidation基盤
- VerificationReportGenerator
- Atomic Output
- 既存出力ファイルの上書き禁止
- input path == output path拒否
- JDL CSV Diagnostic Analyzer
- JDL IBEX出納帳35.5のObserved Behavior診断
- 弥生公式ドキュメント上のインポート形式仕様モデル
- 弥生CSV Observation / Diagnostics
- Demo AdapterによるConversionService E2E
- GitHub Actions

## 弥生仕様の現在位置

`accounting_converter.profiles.yayoi_official` には、弥生株式会社公式サポートで公開されている「弥生取り込み（インポート）形式（弥生会計05以降）」の25項目仕様を `OFFICIAL_DOCUMENTED` / `REAL_DATA_VERIFICATION_PENDING` として保持しています。

これは実データ検証済みの正式 `YayoiInputAdapter` や正式 `FormatProfile` ではありません。現在、使用中の弥生製品、バージョン、実際の出力CSVは未確認です。実データ取得後に、公式ドキュメントとの差分を確認したうえで正式FormatProfileを確定します。

`accounting_converter.diagnostics.yayoi_csv` には、任意の弥生CSV候補を観測し、公式25項目仕様との構造差分を確認する診断機能があります。これは正式変換ではなく、`MATCH_CANDIDATE` / `STRUCTURAL_DIFFERENCE` / `INSUFFICIENT_EVIDENCE` のような人間レビュー前提の判定だけを行います。摘要本文、取引先名、生CSV行全文は既定のテキストレポート/JSONへ出力しません。

## JDL診断機能の現在位置

`accounting_converter.diagnostics.jdl_csv` には、JDLへ取り込めないCSVの構造・診断メッセージ・マスター不一致候補・Observed Schema・Observed Journal Group Candidateを分析する診断機能があります。

JDL IBEX出納帳 35.5の実データでObserved Behaviorは再現できていますが、正式JDL FormatProfileや正式JDLOutputAdapterへは昇格していません。

## Application層の現在位置

`ConversionService` は、InputAdapter、Structural Validation、Mapping、Business Validation、OutputAdapter、OutputValidation、VerificationReportを統括します。

ConversionService自身には、弥生/JDL固有のCSV列変換や識別フラグ生成を実装しません。

正式出力は一時ファイルへ生成し、OutputValidation成功後のみatomic replaceします。既存出力ファイルは `overwrite=True` が明示されない限り上書きしません。

## まだ実装していないもの

- 実データ検証済みの弥生CSV列定義
- 正式YayoiInputAdapter
- 実際のJDL取込CSV列定義
- 正式JDLOutputAdapter
- 正式JDL FormatProfile
- 勘定科目/補助科目/税区分の実マッピング
- GUI
- JDL実機E2E

これらは実CSVとJDL取込仕様確認後に実装します。

## テスト

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

弥生CSV候補の観測CLI:

```bash
PYTHONPATH=src python3 -m accounting_converter.cli diagnose-yayoi <csv-path>
PYTHONPATH=src python3 -m accounting_converter.cli diagnose-yayoi <csv-path> --format json
```

現在のテスト数は85件以上です。

GitHub ActionsではPython 3.12で同じテストを実行し、`tests/fixtures/` 配下以外のCSVがGit管理対象に含まれていないことを確認します。

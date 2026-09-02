# Accounting Converter MVP

会計ソフト間の仕訳データ変換・取込支援システムのMVP実装です。

製品全体は弥生専用ではなく、Input Adapter、Common Journal Model、Mapping / Validation、Output Adapterを分離したvendor-neutralな構造で拡張できるようにします。現在のMVP対象は、弥生会計の仕訳データを共通仕訳モデルへ正規化し、JDL取込形式へ安全に変換することです。

最終的な利用価値は、他社会計ソフトに存在する日々の全仕訳を、税理士事務所が普段使用しているJDLへ取り込み、JDL上で仕訳・元帳・補助元帳等を確認できるようにすることです。

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
- Conversion Profile要件
- Conversion Profileローカル永続化基盤
- Format Identity / Capability / Schema基盤
- Format Registry
- Compatibility Diff / Transformation Plan基盤
- Adapter Contract Test helper
- Canonical Synthetic Dataset
- Demo AdapterによるConversionService E2E
- Windows向け薄いGUIプロトタイプ
- PyInstaller Packaging Proof of Concept
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

## Conversion Profileの方針

同じ顧問先や同じ変換条件を翌月以降再利用できるよう、安全に確定した勘定科目・補助科目・部門・税区分等のMappingをローカルのConversion Profileとして保存可能にする基盤があります。

Profileには仕訳本文、金額データ、摘要本文、実会計ファイルそのものを保存しません。クラウド同期や外部送信も行いません。

保存済みProfileの既知Mappingは自動適用できますが、未知Mappingが出現した場合は推測補完せず、変換停止、ユーザー確認、Profile更新、再実行の流れで扱います。

開発者向けProfile CLI:

```bash
PYTHONPATH=src python3 -m accounting_converter.cli profile --store-dir <profile-dir> list
PYTHONPATH=src python3 -m accounting_converter.cli profile --store-dir <profile-dir> inspect <profile-id>
PYTHONPATH=src python3 -m accounting_converter.cli profile validate <profile-json>
```

## GUIプロトタイプ

`accounting_converter.ui` には、Windows向けローカルデスクトップアプリを想定した薄いGUIプロトタイプがあります。GUI frameworkは標準ライブラリの `tkinter` を使用し、Web server、Electron、Cloud serviceは使用しません。

起動:

```bash
PYTHONPATH=src python3 -m accounting_converter.ui.app
```

現在GUIから確認できること:

- Conversion Profile一覧
- Profile選択
- `.csv` / `.txt` 入力ファイル選択
- 弥生CSV候補の診断
- JDL CSV候補の診断
- ConversionPreflightServiceによる事前確認
- 状態、件数、Error/Warning件数の表示

正式YayoiInputAdapterと正式JDLOutputAdapterは未登録のため、GUIの「変換する」ボタンは有効化しません。ダミーCSVを生成して成功したように見せる処理もありません。

GUIは生CSV全文、摘要全文、個別仕訳全文、個別金額を既定表示しません。表示するのはファイル名、形式候補、件数、構造状態、Error/Warning件数、Preflight状態などに限定します。

## 拡張可能なFormat基盤

`accounting_converter.domain.format_metadata` では、`OFFICIAL_DOCUMENTED`、`OBSERVED`、`VERIFIED_BY_REAL_IMPORT`、`INFERRED`、`UNKNOWN` を区別します。弥生Desktop 25項目、弥生Next 25/27項目候補、JDL IBEX出納帳35.5 Observed Schemaを同一視しないための土台です。

`FormatRegistry` は候補とconfidenceを返しますが、CSVだけを見て製品やバージョンを自動確定しません。`FormatCompatibilityAnalyzer` はSource/Target Schemaの差分からTransformation Planを作りますが、科目・税区分などのMapping値は推測しません。

## まだ実装していないもの

- 実データ検証済みの弥生CSV列定義
- 正式YayoiInputAdapter
- 実際のJDL取込CSV列定義
- 正式JDLOutputAdapter
- 正式JDL FormatProfile
- 勘定科目/補助科目/税区分の実マッピング
- Conversion Profile管理GUI
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

現在のテスト数は150件です。

## Windows Packaging PoC

Windows上で将来 `.exe` 化できることを確認するため、PyInstaller用のPoCスクリプトを用意しています。PyInstallerは通常実行時依存ではなく、任意のbuild dependencyです。

Windowsでの想定手順:

```powershell
.\scripts\build_windows.ps1
```

スクリプト内部では概ね以下を行います。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[build]"
python -m PyInstaller --windowed --name "AccountingConverter" --paths "src" --collect-submodules "accounting_converter" "src\accounting_converter\ui\app.py"
```

`dist/`、`build/`、`*.spec` はGit管理対象外です。Linux/WSL上でWindows `.exe` が生成できるとは仮定しません。現開発環境ではWindows実機ビルドは未検証です。

GitHub ActionsではPython 3.12で同じテストを実行し、`tests/fixtures/` 配下以外のCSVがGit管理対象に含まれていないことを確認します。

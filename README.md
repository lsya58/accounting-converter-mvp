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
- Unit Test骨格

## まだ実装していないもの

- 実際の弥生CSV列定義
- 実際のJDL取込CSV列定義
- 勘定科目/補助科目/税区分の実マッピング
- GUI
- 検証レポートファイル生成
- JDL実機E2E

これらは実CSVとJDL取込仕様確認後に実装します。

## テスト

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

# 弥生ダミーエクスポート実験計画

**作成日:** 2026年8月27日
**対象:** 弥生CSV実データ取得前の低リスク検証
**ステータス:** 実データ検証待ち

## 目的

弥生株式会社公式サポートで公開されている「弥生取り込み（インポート）形式（弥生会計05以降）」の25項目仕様と、今後取得する実CSVの差分を安全に観測する。

本計画は正式なYayoiInputAdapterや正式FormatProfileを確定するものではない。使用中の弥生製品、バージョン、実際の出力CSVは未確認であり、実CSV取得後に正式判断を行う。

## 前提

- 実顧客データは使用しない。
- 会社名、科目、補助科目、部門、摘要は完全架空の値だけを使う。
- 公式25項目仕様は `OFFICIAL_DOCUMENTED` / `REAL_DATA_VERIFICATION_PENDING` として扱う。
- 診断CLIは本文を既定レポートへ出力しない。
- 診断結果から自動マッピング、自動補正、正式FormatProfile昇格を行わない。

## ダミー実験ケース

| ID | 目的 | 主な確認事項 | 期待する観測 |
| --- | --- | --- | --- |
| YAYOI-01 | 単純仕訳 | 現金 1,000 / 売上高 1,000 など完全架空科目 | 25列候補、貸借一致候補 |
| YAYOI-02 | 摘要あり | 摘要欄に短い架空文言 | 摘要本文を診断レポートへ出さずに観測 |
| YAYOI-03 | 補助科目あり | 完全架空の補助科目 | 補助欄を含む25列候補として観測 |
| YAYOI-04 | 税区分・税額あり | 可能なら税区分・税金額を設定 | 金額をDecimalで解析、税区分変換はしない |
| YAYOI-05 | 部門あり | 可能なら完全架空の部門を設定 | 部門欄を含む25列候補として観測 |
| YAYOI-06 | 複数行仕訳 | 可能なら複数行伝票を作成 | 2110/2100/2101候補として観測 |
| YAYOI-07 | 借方複数行 | 可能なら借方が複数行の仕訳 | グループ候補として観測、正式JournalEntry化しない |
| YAYOI-08 | 貸方複数行 | 可能なら貸方が複数行の仕訳 | グループ候補として観測、正式JournalEntry化しない |
| YAYOI-09 | CSV特殊文字 | 摘要にカンマ・ダブルクォート等を含める | CSV quote処理を確認、本文はレポートへ出さない |
| YAYOI-10 | 空欄項目あり | 任意欄を空欄にする | Silent Failureなし、空欄を勝手に補完しない |

## CLI確認

```bash
PYTHONPATH=src python3 -m accounting_converter.cli diagnose-yayoi tests/fixtures/yayoi/official_import_demo.csv
PYTHONPATH=src python3 -m accounting_converter.cli diagnose-yayoi tests/fixtures/yayoi/official_import_demo.csv --format json
```

## 実CSV取得後に確認する差分

- 実CSVが公式25項目形式か。
- ヘッダー行の有無と列名。
- encoding、BOM、改行コード、delimiter。
- 識別フラグの出現値と順序。
- 2110/2100/2101のグルーピング規則。
- 金額欄の桁区切り、空欄、税額欄の扱い。
- 日付形式。
- 公式ドキュメントにない追加列や製品グレード差。
- 実データ上のJournalEntry数とrecord数の関係。

## 注意

この計画と診断実装は、弥生CSVを正式に変換できることを保証しない。正式YayoiInputAdapterは、実CSV取得後に差分を確認し、利用者確認済みのFormatProfileとして別途実装する。

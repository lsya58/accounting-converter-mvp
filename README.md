# Accounting Converter

会計ソフトから出力した仕訳CSVを、会社ごとのJDL設定に合わせて安全に変換するWindowsアプリです。現在はMoney Forward→JDLとJDL→JDLを中心に開発・検証しています。

## 方針

- 科目、補助科目、税区分を推測で確定しない
- 一度確認した対応は、同じ会社設定の範囲で再利用する
- JDL科目一覧や税設定の変更は、影響する項目だけ再評価する
- 未確認・未検証・情報損失の可能性があれば出力前に停止する
- 一部だけの出力、入力ファイルの変更、既存出力の上書きを行わない

## 現在地

| ルート | 確認済み範囲 |
|---|---|
| JDL→JDL | 実案件1,158仕訳・1,271物理行のformal出力と実JDL Importに成功。再Export strict comparisonと会計判断の確認は未完了 |
| Money Forward→JDL | 実案件13仕訳・14物理行で実JDL Import、同期間再Export、strict comparisonに成功。予期しない差分0、silent loss 0 |
| 弥生→JDL | AE19 direct export由来の限定入力経路を回帰維持。対応拡大は後順位 |

482仕訳の実データでは、現在のformal scope見込みは480件（99.59%）です。これは482件一括の実機往復検証を意味しません。未検証の1D2Cと10D9Cが各1件あり、atomic設計により全体出力は停止します。

詳細は[ドキュメント案内](docs/README.md)、現在のEvidence境界は[Current Evidence Status](docs/development/current_evidence_status.md)、LP原稿は[LP Content](docs/marketing/lp_content.md)を参照してください。

## 開発

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
git diff --check
```

Windowsのclean buildは[Windows Release Checklist](docs/operator/windows_release_checklist.md)に従います。配布物の`BUILD_INFO.txt`とサポート診断に表示されるcommitが、build対象のHEADと一致することを確認してください。

## 注意

本製品は「どのCSVでも完全自動変換する」ものではありません。対応は実機Evidenceのexact scopeに限定し、未知の形式や会社設定はBLOCKします。JDL Import前には必ずbackupを取得してください。

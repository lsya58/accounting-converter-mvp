# Accounting Converter

会計ソフトから出力した仕訳CSVを、会社ごとのJDL設定に合わせて安全に変換するWindowsアプリです。現在はMoney Forward→JDLとJDL→JDLを中心に開発・検証しています。

## 方針

- 科目、補助科目、税区分を推測で確定しない
- 一度確認した対応は、同じ会社設定の範囲で再利用する
- JDL科目一覧や税設定の変更は、影響する項目だけ再評価する
- 未確認・未検証・情報損失の可能性があれば出力前に停止する
- 一部だけの出力、入力ファイルの変更、既存出力の上書きを行わない

## Current validation status

MF→JDL の実データ482仕訳（2025-11-01〜2026-10-30）について:

- MF→JDL formal readiness: 482/482
- FY2026（2026年5月期）full real JDL round-trip: VERIFIED（378仕訳・479行、unexpected diff 0、silent loss 0）
- FY2027（2027年5月期）formal output: READY
- FY2027 real JDL round-trip: PENDING
- Remaining real acceptance: 104 journals / 160 rows

482件全体の full real E2E はまだ完了していません。現在地の正本は [Current Evidence Status](docs/development/current_evidence_status.md) です。

| ルート | 確認済み範囲 |
|---|---|
| JDL→JDL | 実案件1,158仕訳・1,271物理行のformal出力と実JDL Importに成功。再Export strict comparisonと会計判断の確認は未完了 |
| Money Forward→JDL | 上記のとおり。ほかに13仕訳の実E2Eなど（[実機検証履歴](docs/development/jdl_real_evidence_log.md)） |
| 弥生→JDL | AE19 direct export由来の限定入力経路を回帰維持。対応拡大は後順位 |

開発の進め方は[Evidence-driven 開発ワークフロー](docs/development/mf_jdl_evidence_driven_workflow.md)（AI agentは[AGENTS.md](AGENTS.md)）。詳細は[ドキュメント案内](docs/README.md)、LP原稿は[LP Content](docs/marketing/lp_content.md)を参照してください。

## 開発

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall -q src tests
git diff --check
```

Windowsのclean buildは[Windows Release Checklist](docs/operator/windows_release_checklist.md)に従います。配布物の`BUILD_INFO.txt`とサポート診断に表示されるcommitが、build対象のHEADと一致することを確認してください。

## 注意

本製品は「どのCSVでも完全自動変換する」ものではありません。対応は実機Evidenceのexact scopeに限定し、未知の形式や会社設定はBLOCKします。JDL Import前には必ずbackupを取得してください。

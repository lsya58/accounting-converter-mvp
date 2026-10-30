# LP・営業資料たたき台

> 履歴資料（2026-10-24時点）。公開コピーには [現行LP Content](../marketing/lp_content.md) を使用してください。以下のcoverage値は現在値ではありません。

## 課題

顧問先の会計ソフトと事務所のJDLが異なると、仕訳の再入力、Excel加工、科目・補助・税区分の確認に時間がかかります。変換できたように見えても、情報欠落や会社設定違いは見つけにくい問題です。

## 提供すること

Accounting Converterは、会社ごとのJDL科目一覧と税設定を基準に、仕訳CSVをJDL Import用CSVへ変換します。一度確認した対応は再利用し、未確認項目があれば出力前に停止します。

## 3つの強み

1. **会社ごとの設定**: 実際のJDL科目・補助だけを候補にします。
2. **推測しない安全性**: 未確認・未検証・情報損失の可能性があればBLOCKします。
3. **実機重視**: 仕様書だけでなく、限定scopeでJDL Import / re-exportを確認します。

## privacy-safeな実績

- JDL→JDL: 実案件1,158仕訳、1,271物理行をformal出力し、実JDL Import成功
- 同batchの予期しない変更0、silent loss 0
- MF→JDL: 父親事務所482仕訳baselineの458件、95.02%がEvidence-backed scope

JDL→JDLの会計的妥当性はHuman review中で、batch再Export strict comparisonは未取得です。対応外条件は事前に明示します。

## 導入イメージ

会社追加 → JDL科目一覧 → 税設定 → CSV選択 → 必要項目だけ確認 → JDL用CSV生成 → backup後にImport → 件数・貸借確認

## Pilot案内

最初は対象ソフト、version、会社設定、CSVを事前診断する伴走型pilotです。READYになったデータだけを扱い、未知形式を推測変換しません。

## CTA候補

- 対応可能か相談する
- pilot利用について問い合わせる
- 現在のCSVをprivacy-safeに事前診断する

「完全自動」「すべてのCSVに対応」「100%成功」など、未証明の表現は使用しません。

# ドキュメント案内

Accounting Converterの資料を、読む目的ごとに案内します。製品の現在地は、古い設計書ではなく、まず「一般・導入向け」の資料で確認してください。

## 一般・導入向け

- [製品概要](product/製品概要.md): 製品が行うこと、安全設計、会社設定の考え方
- [対応状況](product/対応状況.md): JDL→JDL、MF→JDL、弥生→JDLの現在地
- [実績と検証結果](product/実績と検証結果.md): privacy-safeな実機検証実績
- [操作ガイド](product/操作ガイド.md): 初回設定からJDL Import後確認まで
- [よくある質問](product/よくある質問.md): 実際の運用で迷いやすい点
- [制限事項と対応外条件](product/制限事項と対応外条件.md): BLOCKになる条件と非対応範囲

## Pilot・サポート

- [パイロット導入ガイド](product/パイロット導入ガイド.md): backup、test Import、Go/No-Go
- [サポートと障害対応](product/サポートと障害対応.md): 診断情報、log、retry、復元

## LP・営業

- [LP・営業資料たたき台](product/LP・営業資料たたき台.md): 課題、価値、安全性、実績、CTA候補
- [Product / LP Brief](product/lp_product_brief.md): 詳細な企画・収益化検討用brief

## 開発者向け

- `design/`: 現行設計と実装境界
- `research/`: 形式調査、互換性、観測Evidence
- `development/`: probe、private監査、開発手順
- `experiments/`: 実機実験の計画と記録
- `operator/`: build・初回セットアップの技術運用
- `security/`: Windows配布時の安全性
- `tests/evidence/`: machine-readable manifestを含むEvidence原本

## 棚卸し結果

| 分類 | 対象 | 扱い |
|---|---|---|
| A. 開発者向け | `design/`, `research/`, `development/`, `experiments/`, `security/`, Evidence README | 参照pathを維持。Human向け資料から必要箇所だけ要約 |
| B. Human・営業向け | `product/`の日本語資料、本index | 現在の製品説明と運用判断の一次資料 |
| C. 重複 | `lp_product_brief.md`と各Human向け資料の一部 | Briefは企画詳細、各資料は用途別に分離し相互リンク |
| D. 履歴資料 | `basic_design_v0.2.md`, `basic_design_v0.3.md`, `要件定義書.md`, `要求仕様書.md` | 当時の設計・要求の記録。現在の対応状況には使用しない |
| E. 更新対象 | Product Brief、一般向け対応状況、操作・pilot・support資料 | 2026-10-24時点へ更新 |

既存の技術文書はコードやEvidenceから参照される可能性があるため、今回rename・削除していません。

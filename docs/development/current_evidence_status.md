# Current Evidence Status

最終更新: 2026-10-31

現在のroute、Evidence、blockerの正本です。過去のresearch文書と矛盾する場合は、この文書とEvidence原本を優先します。

## Evidence policy

- 最高水準は、実JDL Importと同期間re-exportのstrict semantic comparison
- Evidenceはroute、shape、科目・補助、税Context等のexact scopeに限定
- 確認済みcanonical normalizationだけを許容し、raw diffも残す
- unexpected diffとsilent lossを許容しない
- source、master、Contextの意味ある変更は影響範囲を再評価
- unknown、stale、Evidence不足はfail-closed

## Route status

| Route | Status | Boundary |
|---|---|---|
| JDL→JDL | `VERIFIED_BY_REAL_IMPORT`, frozen | 1,158 journals / 1,271 rows。実Import PASS。会計判断reviewとbatch re-export strict comparisonは未完了 |
| MF→JDL READY batch | `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` | 13 journals / 14 rows、P01-P07、unexpected diff 0、silent loss 0 |
| MF→JDL 482 dataset | Expansion in progress | capability compositionで416/482がEvidence上通過（保存済み設定では税4項目のHuman確認待ち）。摘要置換が済んだ371件は実設定コピーでformal出力SUCCESS。full batch atomic outputはBLOCK |
| 弥生→JDL | Limited regression route | AE19 direct export由来の限定scope。拡張は後順位 |

## Key Evidence IDs

| ID | Status / scope |
|---|---|
| `EVID-JDL-TO-JDL-REAL-BATCH-1158-IMPORT-001` | 実JDL Import。再Export strict比較は未取得 |
| `EVID-MF-JDL-REAL-READY-BATCH-13J-ROUNDTRIP-001` | MF 13-journal real round-trip |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001` | 税抜・原則課税・一括比例配分方式の限定P01-P07 batch |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-SUB0001-001` | P05 exact subaccount variant |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-SUB0001-001` | P07 exact subaccount variant |
| `EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001` | exact 1D2C / 2-row real Import and re-export; output preflight/serializer connected |
| `EVID-MF-JDL-35-5-OUTPUR-8471-1111-ROUNDTRIP-001` | 対象外仕入target blank/0の1D1C限定実機往復 |
| `EVID-MF-JDL-35-5-OUTPUR-COMPOUND-TAX-001` | 対象外仕入11 compoundのtax interaction、exact scope |
| `EVID-MF-JDL-35-5-OUTPUR-4D6C-ROUNDTRIP-001` / `...5D7C...` / `...5D8C...` | 3形状のgrouping・行順を各exact scopeで検証 |
| `EVID-MF-JDL-35-5-OUTPUR-ROW-DESC-ROUNDTRIP-001` | 同じ11件の127行別摘要保持 |
| `EVID-MF-JDL-35-5-NONPUR-8571-1311-SUB0002-001` | 非課税仕入 8571→1311/0002 の1D1C実機往復（0876）。3181/0001と合わせ実482件の非課税仕入10/10 |

## 482-journal dataset

- Logical journals: 482 / physical rows: 639 / period 2025-11-01 through 2026-10-30
- 判定方式: 完全一致Evidenceを優先し、ない場合は [capability composition](../design/mf_tax_capability_composition.md)（shape × 行ごとの税 × 科目・補助 × 摘要）
- 2026-10-31 再計算（保存済みCompanySettingのコピー、本番設定は未変更）:

| 状態 | 仕訳 |
|---|---:|
| 保存済み設定のまま | BLOCKED。税Human 4項目未確認、税Evidence 143、摘要置換 68 |
| 税4項目をHumanが確認した場合 | route通過 416（完全一致277・組み合わせ139）、BLOCK 66 |
| うち摘要置換が不要な分 | 371。実設定コピーで formal output SUCCESS、出力strict reparse 371/507、税額pattern違反0 |

### Current action owners（税4項目確認後のシミュレーション）

| Owner | Item | Journals |
|---|---|---:|
| `HUMAN` | 税区分4項目（対象外仕入・非課税仕入・非課税売上・課税売上10%）。Evidenceのある候補を確認するだけ | 保存済み設定では全税関連 |
| `HUMAN` | 普通預金1311 / MF補助なし → JDLまとめ先補助。親科目のみは実機拒否済み | 43 |
| `HUMAN` | 売掛金1551 / MF補助なし → JDLまとめ先補助（10D9C） | 1 |
| `HUMAN` | 32文字超・改行入り摘要の置換文（約55種類） | 68 |
| `SYSTEM_EVIDENCE` | 2D1C（対象外 + 課税仕入10% / 普通預金） | 10 |
| `SYSTEM_EVIDENCE` | 課税売上10%で切捨てと四捨五入が分かれる金額 | 9 |
| `SYSTEM_EVIDENCE` | 課税売上10% on 9251 | 2 |
| `SYSTEM_EVIDENCE` | 2D3C（課税仕入10%が2行） | 1 |
| `SYSTEM_EVIDENCE` | 10D9C（売掛金1551のHuman補助が先） | 1 |

- 取引先optional 47件は、旧形式（context hash）の取引先方針が税設定・master更新のたびに失効していたbug。capability境界（製品・版・出力形式）で判定するよう修正し、0件になった。Human再確認は不要。
- 1D2C exact route は journal id（ファイル名を含む）の hash で照合している。MF CSV を別名で再出力すると1件BLOCKされる。SYSTEM_IMPLEMENTATION として要改善。
- 課税売上10%の`売一種`は現会社のImportで失敗済み。現会社のliteralは`売　上`/10%/外税。

Humanが解決できるmappingと、開発側のEvidence取得待ちをUI・supportで混同しないこと。Tax Evidence待ちを追加Human確認で解決させてはならない。

2026-10-30に追加されたJDL科目一覧の補助候補監査とTax probe計画は [MF subaccount candidates and pending tax Evidence](mf_subaccount_candidate_and_tax_evidence.md) を参照。

## Known target constraint

JDL IBEX 出納帳35.5の30列仕様モデルでは借方・貸方補助名称が10文字です。別製品/versionへ一般化しません。長いMF補助名称はそのまま保持できない場合があり、target short-name mappingとHuman確認が必要です。fuzzy auto-confirmは禁止です。

## Core implementation concepts

- **CompanySetting**: source/target形式とcurrent profileを束ねる会社単位設定
- **JDL master**: 使用可能な科目・親子関係の観測情報
- **Human confirmation**: 会計判断を伴うmapping/policyの明示確認
- **Tax Context**: JDL version、課税区分、税込/税抜、課税方式等
- **Evidence registry**: 実機確認済みexact scope
- **Formal preflight**: mapping、Evidence、保持、shape、staleを出力前に判定
- **READY/BLOCKED**: 全条件が揃った場合だけformal outputを許可
- **Atomic output**: blockerがあればpartial outputを作らない
- **Master diff / impact-based stale**: 無関係な変更で全mappingを失効させない
- **Action owner**: `HUMAN`、`SYSTEM_EVIDENCE`、`SYSTEM_IMPLEMENTATION`を分離

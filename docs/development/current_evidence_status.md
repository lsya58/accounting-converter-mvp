# Current Evidence Status

最終更新: 2026-10-29

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
| MF→JDL 482 dataset | Expansion in progress | 480/482はformal scope projection。full batch round-trip未検証、atomic outputはBLOCK |
| 弥生→JDL | Limited regression route | AE19 direct export由来の限定scope。拡張は後順位 |

## Key Evidence IDs

| ID | Status / scope |
|---|---|
| `EVID-JDL-TO-JDL-REAL-BATCH-1158-IMPORT-001` | 実JDL Import。再Export strict比較は未取得 |
| `EVID-MF-JDL-REAL-READY-BATCH-13J-ROUNDTRIP-001` | MF 13-journal real round-trip |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001` | 税抜・原則課税・一括比例配分方式の限定P01-P07 batch |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-SUB0001-001` | P05 exact subaccount variant |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-SUB0001-001` | P07 exact subaccount variant |

## 482-journal dataset

- Logical journals: 482
- Physical rows: 639
- Period: 2025-11-01 through 2026-10-30
- Current formal scope projection: 480 / 482 = 99.59%
- Projection is not a full-batch real JDL verification

### Current action owners

| Owner | Item |
|---|---|
| `HUMAN` | 補助科目設定13件。JDL 35.5の補助名称上限10文字に合わせ、必要ならHumanが短縮先を選ぶ |
| `SYSTEM_EVIDENCE` | 対象外仕入11 source rows、課税売上10% 65、非課税仕入10、非課税売上2。code: `MF-JDL-TAX-EVIDENCE-MISSING-EXACT` |
| `SYSTEM_EVIDENCE` | 1D2C 1 journal、10D9C 1 journalのexact実機Evidence |

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

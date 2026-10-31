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
| MF→JDL 482 dataset | Expansion in progress | 1D2C exact real Import/re-export PASS。structural Evidence projection 481/482、formal routeは未実装。full batch atomic outputはBLOCK |
| 弥生→JDL | Limited regression route | AE19 direct export由来の限定scope。拡張は後順位 |

## Key Evidence IDs

| ID | Status / scope |
|---|---|
| `EVID-JDL-TO-JDL-REAL-BATCH-1158-IMPORT-001` | 実JDL Import。再Export strict比較は未取得 |
| `EVID-MF-JDL-REAL-READY-BATCH-13J-ROUNDTRIP-001` | MF 13-journal real round-trip |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001` | 税抜・原則課税・一括比例配分方式の限定P01-P07 batch |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-SUB0001-001` | P05 exact subaccount variant |
| `EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-SUB0001-001` | P07 exact subaccount variant |
| `EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001` | exact 1D2C / 2-row real Import and re-export; output serializer activation pending |

## 482-journal dataset

- Logical journals: 482
- Physical rows: 639
- Period: 2025-11-01 through 2026-10-30
- Structural Evidence projection: 481 / 482 = 99.79%; this includes one newly verified exact 1D2C shape
- Formal READY count and full-batch output are unchanged. The exact 1D2C output preflight/serializer route is connected with source-journal ID, physical-row, account/subaccount, and tax guards; the 482-journal batch remains BLOCKED for independent reasons.
- Projection is not a full-batch real JDL verification

### Current action owners

| Owner | Item |
|---|---|
| `HUMAN` | MF補助なしの売掛金1551・普通預金1311に対するまとめ先JDL補助2設定。親科目のみでは実機Import不可 |
| `SYSTEM_EVIDENCE` | 対象外仕入11 source rows、課税売上10% 65、非課税仕入10、非課税売上2。code: `MF-JDL-TAX-EVIDENCE-MISSING-EXACT` |
| `SYSTEM_IMPLEMENTATION` | 実機確認済みexact 1D2Cのformal preflight/serializer接続は完了。production-pathでの同一仕訳確認と他blockerの解消が残る |
| `SYSTEM_EVIDENCE` | 10D9C 1 journalのexact実機Evidence。売掛金1551のHumanまとめ先補助が先行依存 |

非課税仕入・非課税売上の各1件について、2026-05-21/22のJDL実機Import・再Exportが独立strict PASS。Exact account/subaccount/side/shape/context限定のEvidence IDと比較結果は `tests/evidence/e2e/mf_non_taxable_exact_20260521_22/README.md` を参照。これは上記10件・2件全体のcoverage確定でもproduction tax mappingのactivationでもない。残る署名は実データと照合し、未確認はBLOCKを維持する。

2026-10-31時点の保存済みMF→JDL CompanySettingと実482件を照合すると、上記非課税仕入Evidenceと同じ1D1C・tax side・account/subaccount署名は9/10件、非課税売上は2/2件。署名の異なる非課税仕入1件はBLOCK。これらは署名照合数であり、Human tax mapping・formal output・実機batchのREADY数ではない。課税売上10%の`売一種`は現会社のImportで失敗済み。

課税売上10%の現会社自己Export由来`売　上` / `10%` / `外税` candidateは、別日の実JDL Import・再Exportでstrict PASS。独立Evidence `EVID-MF-JDL-35-5-SALES10-1111-6121-ROUNDTRIP-001` を登録した。実482件の課税売上10% 65件中、このexact 1111/補助なし→6121/補助なし/取引先なし署名に一致するものは0件。8種類の別署名は追加Evidence待ちで、65件のformal READY率は上がらない。詳細は `tests/evidence/e2e/mf_tax_sales10_excluded_proportional_cash/README.md`。

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

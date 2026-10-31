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
| MF→JDL 482 dataset | FY2026-05 `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` / FY2027-05 READY | 482/482 formal READY。当期378件はclean targetへの実Import・期間全体再Exportでstrict PASS（0878）。翌期104件は翌期データ待ち |
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
- 判定: 完全一致Evidence優先、なければ [capability composition](../design/mf_tax_capability_composition.md)
- 再計算: `tools/mf_formal_readiness.py`、期別出力: `tools/mf_formal_output_by_period.py`（どちらも保存済み設定を変更しない）

### 2026-10-31 再計算（0877 Evidence接続後、保存済みCompanySetting）

| Owner | Journals |
|---|---:|
| READY | 482（639 rows） |
| HUMAN | 0 |
| SYSTEM_EVIDENCE | 0 |
| SYSTEM_IMPLEMENTATION | 0 |

Human設定は保存済み設定を直接確認: 税6項目すべて `USER_CONFIRMED`（Evidence ID付き）、普通預金・売掛金の補助なし→まとめ先補助 `DEFAULT_TARGET_SUBACCOUNT`、摘要置換66件（必要63グループ+過去の髙置換、未解決0）、取引先方針確認済み。Optional検出83仕訳はすべてHuman確認済みの摘要置換で解消済み（未解決0）。

### Formal output（private、未Import）

| File | Period | Journals | Rows | Debit = Credit |
|---|---|---:|---:|---:|
| `data/private/mf_482_formal_output/mf_formal_jdl_FY2026-05.csv` | 2025-11-01〜2026-05-31 | 378 | 479 | 24,740,332 |
| `data/private/mf_482_formal_output/mf_formal_jdl_FY2027-05.csv` | 2026-06-01〜2026-10-30 | 104 | 160 | 4,053,397 |

いずれも READY → SUCCESS、CP932・BOMなし・CRLF・30列・strict reparse PASS。

### Full 482 E2E

- 2026-10-31: FY2026-05 の378件は [full round-trip](../../tests/evidence/e2e/mf_482_full_roundtrip/README.md) PASS（0878、unexpected 0、silent loss 0）。

### 残り（翌期）

- JDL 0514 は令和8年5月期。FY2027-05 の104件は翌期データが必要。翌期の科目・補助masterが現CompanySettingと同じことを、翌期の科目一覧で確認してからImportする（違えば master diff で影響項目だけ再確認）。
- 0514 には13件の実E2E（482件と同じ仕訳）と probe（2026-05-18〜29）がある。full Import は probe 前の状態または専用の検証用会社に対して行う。

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

# Current Evidence Status

最終更新: 2026-10-31

**現在地の唯一の正本（single source of truth）です。** README・製品文書・AGENTS.md はここへリンクし、件数を独自に持ちません。過去の実機操作は [JDL実機検証履歴](jdl_real_evidence_log.md)、調査時点の資料は `docs/research/` と各文書の履歴節に残します。矛盾する場合はこの文書とEvidence原本を優先します。

## Canonical current state（MF→JDL 実データ482件）

| 段階 | 状態 | 範囲 |
|---|---|---|
| Converter formal readiness | **482/482 READY**（HUMAN 0 / SYSTEM_EVIDENCE 0 / SYSTEM_IMPLEMENTATION 0） | 482 journals / 639 rows、保存済みCompanySetting |
| FY2026-05 formal output | 生成・静的検証済み | 378 journals / 479 rows、2025-11-01〜2026-05-31 |
| FY2026-05 real JDL round-trip | **VERIFIED**（`EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001`、0878） | 378/378、479/479、missing 0、extra 0、unexpected 0、silent loss 0、順序不一致 0、借方=貸方=24,740,332 |
| FY2027-05 formal output | 生成・静的検証済み | 104 journals / 160 rows、2026-06-01〜2026-10-30、借方=貸方=4,053,397 |
| FY2027-05 real JDL round-trip | **PENDING**（JDL翌期環境で未実施） | 104 journals / 160 rows |
| Full 482 real E2E | **未完了**。FY2027-05 が PASS した時点で `FULL 482 REAL E2E COMPLETE` | 482 journals / 639 rows |

Evidence取得フェーズは終了しています。新しいprobeは作りません（HUMAN・SYSTEM_EVIDENCE・SYSTEM_IMPLEMENTATIONがすべて0で、FY2026-05は実機full batchでPASS済み）。

## Remaining critical path（これだけ）

FY2027-05 の real round-trip。formal CSV は `data/private/mf_482_formal_output/mf_formal_jdl_FY2027-05.csv`（private、生成済み）。

1. JDL の翌期環境（令和9年5月期）を用意する。2026-06-01〜2026-10-30 に他の仕訳がない状態にする
2. 翌期の科目・補助masterが現CompanySettingと同じことを確認する（翌期の科目一覧を読み込み、master diffで差分0。差分があれば影響項目だけHuman再確認）
3. 104件をImport
4. 2026-06-01〜2026-10-30 を再Export
5. `tools/mf_full_e2e_compare.py` でstrict比較

PASS条件: 104/104 journals、160/160 rows、missing 0、extra 0、unexpected 0、silent loss 0。PASSしたら上表の Full 482 を `FULL 482 REAL E2E COMPLETE`（482 journals / 639 rows、FY2026-05 + FY2027-05）へ更新し、Evidence logへ追記する。

会計期間はconverterのcapabilityとは別のtarget条件です。期外の日付をJDLが拒否しても、converterの失敗ではありません。

## 弥生 → JDL（2026-11-03 時点）

顧問先2社の実データとJDL科目一覧PDFを取得。顧客の値はここに書かない。

- **会社B（弥生インポート形式）**: 80仕訳の実機全件往復 PASS（`EVID-YAYOI-JDL-35-5-COMPANYB-202603-FULL-ROUNDTRIP-001`）
- **会社A（仕訳日記帳 汎用形式）**: 正式変換は未完了（FORMAL READY 0）
- **弥生対応全体は完了ではない**: Windows 画面は未対応で、操作は CLI と private の確認シートで行う

| 段階 | 会社A（仕訳日記帳 汎用形式） | 会社B（弥生インポート形式） |
|---|---|---|
| 仕訳 / 行 | 2,514 / 7,232（12か月） | 80 / 86（1か月） |
| 厳密な読み込み・共通の行の意味 | 2,514 / 2,514 | 80 / 80 |
| JDL科目一覧の読込 | 読込済み（科目99・補助289。同名2組・同名補助2組は選択不可として除外） | 読込済み（科目91・補助0） |
| 会社設定（Tax Context） | 確定済み（2026-11-03）。JDL補助名9件は取込欄（全角10字）を超えるため「選択不可の補助」として記録（使える補助は280件。親科目は補助必須のまま） | 確定済み（private store、税抜・原則・一括比例・端数 売上/仕入とも切捨て） |
| 端数処理（Human転記） | 売上 切上げ / 仕入 四捨五入 | 売上 切捨て / 仕入 切捨て |
| 現在のブロッカー | HUMAN 2,514（科目・補助・税区分・摘要の確認）。SYSTEM_EVIDENCE 8（決算7・形2。他の形の不足は確認後に表に出る） | 0（確認シート35行を反映済み） |
| JDLに入らない情報 | 付箋 2 | 部門 34・生成元 35・付箋1 35（同じ35仕訳）。JDLへは出さず監査記録に残す扱い（Human確認が必要）。完全保持は宣言しない |
| SYSTEM_EVIDENCE（素直な候補・各社の端数を仮定） | 951仕訳 | 0（2026-11-03 実機で 6122売上 と 対象外2D2C を確認） |
| 正式READY | 0 | **80/80**（HUMAN 0・SYSTEM_EVIDENCE 0・SYSTEM_IMPLEMENTATION 0） |
| 正式CSV・実機往復 | 未実施 | **PASS**（2026-11-03。80/80仕訳・86/86行、既知正規化454セルのみ、監査記録104値 PASS）。部門・生成元・付箋1は監査記録で保全するため、完全保持ではない |

明示税額は「JDLがそのまま保持する」と「JDLが会社の端数設定で計算し直す」のどちらでも同じ値になる場合だけ通す（明示税額 = 切捨て値 = 対象会社の端数処理の値）。端数処理が未設定なら HUMAN。0877 の実機では切捨て値が保持されたが、その会社の端数設定が記録されていないため、保持か再計算かは未確定（[仕様](../design/yayoi_journal_report_source.md#端数処理と明示税額2社)）。

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
| MF→JDL 482 dataset | 上の Canonical current state を参照 | FY2026-05 real round-trip VERIFIED、FY2027-05 PENDING |
| 弥生→JDL | 会社B（インポート形式）は `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`。会社A（仕訳日記帳 汎用形式）は未検証 | 会社B 80仕訳の全件往復 PASS。会社Aは会社設定保留中。上の弥生の節を参照 |

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
| `EVID-MF-JDL-35-5-2D1C-PURCHASE10-ROUNDTRIP-001` / `...2D3C...` / `...10D9C...` / `...SALES10-ROUNDING-6121...` / `...SALES10-9251...` | 0877 final batch、5 case別strict PASS |
| `EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001` | 実データFY2026-05の378件 full real round-trip（0878） |

## 482-journal dataset（判定の根拠）

- 判定: 完全一致Evidence優先、なければ [capability composition](../design/mf_tax_capability_composition.md)
- 再計算: `tools/mf_formal_readiness.py`、期別出力: `tools/mf_formal_output_by_period.py`、実機比較: `tools/mf_full_e2e_compare.py`（いずれも保存済み設定を変更しない）
- Human設定（保存済み設定を直接確認、2026-10-31）: 税6項目 `USER_CONFIRMED`（Evidence ID付き）、普通預金・売掛金の補助なし→まとめ先補助、摘要置換66件（未解決0）、取引先方針確認済み。Optional検出83仕訳はすべて確認済みの摘要置換で解消。
- Human が解決する mapping と、開発側の Evidence 待ちを UI・support で混同しない。Evidence 待ちを Human の追加確認で解決させない。

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

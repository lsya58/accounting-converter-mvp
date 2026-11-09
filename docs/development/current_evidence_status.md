# Current Evidence Status

最終更新: 2026-11-08

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

## 弥生 → JDL（2026-11-04 時点）

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
| SYSTEM_EVIDENCE（素直な候補・登録済みEvidenceを反映、2026-11-05） | 147仕訳（Humanが各税の自然な候補を確認し、振替伝票入力行数16を入力した仮定。レイアウト未観測76・税の配置未観測60・80%経過措置の税額11）。ほかに16行制約30・未解決（控除不可2・決算7）9 | 0（2026-11-03 実機で 6122売上 と 対象外2D2C を確認） |
| 正式READY | 0 | **80/80**（HUMAN 0・SYSTEM_EVIDENCE 0・SYSTEM_IMPLEMENTATION 0） |
| 正式CSV・実機往復 | 未実施 | **PASS**（2026-11-03。80/80仕訳・86/86行、既知正規化454セルのみ、監査記録104値 PASS）。部門・生成元・付箋1は監査記録で保全するため、完全保持ではない |

明示税額は「JDLがそのまま保持する」と「JDLが会社の端数設定で計算し直す」のどちらでも同じ値になる場合だけ通す（明示税額 = 切捨て値 = 対象会社の端数処理の値）。端数処理が未設定なら HUMAN。0877 の実機では切捨て値が保持されたが、その会社の端数設定が記録されていないため、保持か再計算かは未確定（[仕様](../design/yayoi_journal_report_source.md#端数処理と明示税額2社)）。

会社Aの合成JDL target probeは、[3D3C](../../tests/evidence/e2e/yayoi_buddies_3d3c_sales10/README.md) と [4D4C](../../tests/evidence/e2e/yayoi_buddies_4d4c_sales10/README.md) の課税売上10%について、実Import・同期間再Export・既存strict比較を各ケースPASSした（計2仕訳・7行、unexpected 0）。**弥生source→formal outputのEvidenceではない**。元データに同じ借貸行数・税側/税identityの構造候補は計154仕訳（3D3C 96、4D4C 58）。うち96仕訳は現在の仮評価でshapeのみが表示されるが、shapeを認めた後に複数課税行のgapが顕在化し得る。Human対応、target科目/補助、exact tax signatureも未確定。端数依存などが表示される残り58仕訳を含め、154仕訳をREADYへ加算しない。現在の正式READYは0、production Evidence registryも未変更。

会社Aの [Evidenceキャンペーン](yayoi_buddies_evidence_campaign.md) 第1回（2026-11-05、検証用複製）: 合成probe A1〜A3 の58ケースがケース別 strict PASS、重複0（[記録](../../tests/evidence/e2e/yayoi_buddies_campaign_session1/README.md)）。**振替伝票入力行数16行以内の会社Aでは、16行の伝票はCSV取込できるが、17行以上は取込で拒否される**（`EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001`、この会社・この設定に限る）。元データの16行超30仕訳は、この設定のままでは1伝票として取り込めない（自動分割・設定変更はしない）。CSV取込の明示税額は会社の端数設定と異なる値でも保持された。輸出売上・軽減8%・80%経過措置はJDL画面で表現を観測（第2回で取込往復）、控除不可と決算仕訳は表現未確認で保留。production registry・READYは未変更。

第2回（2026-11-05）: 輸出売上（課区「輸出売」）・軽減8%（仕　入／軽減8%／内税）・80%経過措置（仕　入／10%免80／内税）の合成probe 6ケースが strict PASS（[記録](../../tests/evidence/e2e/yayoi_buddies_campaign_session2/README.md)）。キャンペーン全体の再計算（Humanが自然な候補を確認した仮定、件数のみ）: 2,514仕訳のうち、既存Evidenceで技術条件なし992、**実機Evidenceはそろい本体実装待ち1,432**、Evidenceのないまれな形51（35種類・16行以内）、控除不可・決算 未解決9、16行制約30。課税売上10%の1,040仕訳と非課税売上の16仕訳は、Humanが検証済みの科目（売上 6121・6131・6181・9251、非課税売上 9111）へ対応付けた場合に限る。全仕訳で科目・補助・税区分などのHuman確認は残る。正式READYは0のまま。

**本体への反映（2026-11-05）**: 上の実機Evidence 66ケース（既存の3D3C・4D4C＋キャンペーン64）を、会社設定の範囲を限って本体に登録した（[設計と結果](yayoi_buddies_evidence_campaign.md#7-本体への反映実装済み2026-11-05)）。範囲 = JDL IBEX 出納帳35.5・税抜・原則課税・一括比例配分・端数処理 売上=切上げ／仕入=四捨五入・**振替伝票入力行数16（Humanが会社設定から入力した値）**。範囲外（別の端数処理・別の行数・行数未入力）には適用しない。既存のMF/ACTのEvidenceは先に判定され、通れば従来どおり（MF 482 READY・出力SHA 2本、ACT 80/80・往復は不変）。新しい税の書き方（輸出売上・軽減8%・80%経過措置）は完全一致した弥生の識別名だけが候補で、Humanの確認が必須。控除不可・決算仕訳は未確認のまま。明示税額は観測した（側・税・関係・科目）の組だけ許可。振替伝票入力行数は会社設定に保存（確認済みのときだけ書く）し、超過する仕訳は正式変換前にHumanの判断として止める（自動分割しない）。会社Aの現在の保存設定は変更していないため、行数上限は未入力で、本物の診断は変わらずHUMAN 2,506・HUMAN+SYSTEM_EVIDENCE 8・READY 0。

**第3回（2026-11-06、実機取得・反映済み）**: 合成Probe 7ファイル（93仕訳・471行）を実機で取込・再Export。構造70・端数税額5ケースが strict PASS し、registryは141ケースになった。Humanが自然な候補を確認した仮定での JDL Evidence不足は **147 → 0**（16行制約30・控除不可/決算9は残る）。摘要は CP932 64バイトまで（確認した文字種）JDLが保持し、64バイト超は**黙って切り詰める**ことを確認。摘要の確認待ちは 248件（205仕訳）→ 0。正式READYは0のまま（Human確認が残る）（[詳細](yayoi_buddies_evidence_campaign.md#96-実機結果と反映2026-11-06)）。

**新規JDL科目（2026-11-07、実機取得・反映済み）**: 2026-11-06に追加した売上・仕入科目7コードの12ケースが strict PASS。registry 141→153ケース。新コード由来の技術的Evidence不足 1,108→0（Human確認の仮定での試算。正式READYは0のまま）。3科目規則は印字された税の既定設定が同じ科目に限定した（[詳細](yayoi_buddies_evidence_campaign.md#11-新規jdl科目の実機evidence2026-11-07)）。

**2026-11-07（補助・形・科目別税額）**: 確認画面の「形が未検証」をMF専用の数え方から正式判定と同じ構造ルールへ修正（会社Aは602→行数16入力時2）。Probe 6ファイル・35仕訳を実機にImportし、同日再Exportを取得。補助省略は引き続き不可。過去のローカル診断ではREADY 157仕訳だったが、現在のWindows設定の正式READYではない（[詳細](yayoi_buddies_evidence_campaign.md#12-補助のある親科目形の表示残る科目別evidence2026-11-07)）。

**2026-11-07 補助・税額・構造の実機往復結果**: TAX15の15ケースとSTRUCT6の6ケースがstrict PASSし、scope限定registryは153→174ケース。補助保持は2 PASS・1 CHANGED、補助名称のみは2 CHANGED、3141補助空欄と1551/3141補助0000はImport拒否。補助名称のみを安全な変換法として有効化していない。ケース別の[記録](../../tests/evidence/e2e/yayoi_buddies_subtax_20260719/README.md)を参照。保存済みローカルCompanySettingと新masterの再構成が重複identity検証で停止した件は、アプリ外の再構成で科目を略名称で識別したのが原因（1311と1314の略名称が同じ）。アプリの経路では停止しない。

**2026-11-07 再診断（Windows設定のコピー、`tools/yayoi_formal_rediagnosis.py`）**: 正式READY **157**（保存設定のまま。最新PDFの再読込でも変化なし・context検証PASS）。行数16入力で493、22親科目を親科目のみで1,419、残り補助30種類を決めれば2,473（試算。正式READYではない）。174ケース化で科目別税額のEvidence不足 35→2仕訳、構造 22→2仕訳（STRUCT6の対象20仕訳はすべて解消）。残る2仕訳は控除不可を含む仕訳で、Humanの税区分判断待ち。技術的Evidence不足だけで止まる仕訳は0。残りは16行超30・決算7・控除不可2・付箋の方針2と補助30種類の登録判断（[詳細](yayoi_buddies_evidence_campaign.md#13-重複identityの原因最新evidenceでの再診断補助30種類2026-11-07)）。

**2026-11-07 控除不可の消費税集計（最新のWindows設定のコピー）**: 正式READY **2,475** / 2,514（16行超30・決算7・控除不可を含む2）。控除不可は技術確認済み（非仕入・税区空欄で往復一致、消費税集計で課税仕入・税額に入らない）だが、申告上の同等性は税理士確認待ちで BLOCK のまま。会社単位のSIGNOFF記録後の試算は 2,476（残る1仕訳は配置Evidence不足、1仕訳は16行超）。[詳細](yayoi_buddies_evidence_campaign.md#162-消費税集計表の前後比較と税理士確認を条件にした実装2026-11-07)

**2026-11-07 残り39仕訳**: 正式READY 2,475（変化なし）。16行超は Human承認制の伝票分割（20件が対象）を実装、第4回Probe（分割の形・非仕入B1D4）・新規補助E2E・決算仕訳の手入力比較を準備（JDL実機待ち）。試算: Probe PASS＋分割承認 2,494、＋控除不可SIGNOFF 2,497（[詳細](yayoi_buddies_evidence_campaign.md#17-残り39仕訳の技術課題2026-11-07税理士確認と並行)）

**2026-11-07 第4回実機**: SPLIT 7/7・NP 3/3 PASS（registry 184）、補助E2E PASS、決算整理仕訳はJDL出力で日付13月（取込は未確認）。正式READY 2,475（変化なし）。分割承認後 2,494、＋控除不可SIGNOFF後 2,497（試算）。残る技術課題は決算仕訳の取込確認のみ（[詳細](yayoi_buddies_evidence_campaign.md#18-第4回の実機結果と反映2026-11-07)）

**2026-11-07 決算整理（13月）**: 取込で決算整理区分が保たれることを実機確認（CLOSING_IMPORT_PRESERVED）。本決5件を日付YYYY13DDで出力するよう実装し、**正式READY 2,480**。分割承認後 2,499、＋控除不可SIGNOFF後 2,502（試算）。7531（3行）は追加Probe待ち、中決3605はBLOCK（[詳細](yayoi_buddies_evidence_campaign.md#19-決算整理仕訳13月の取込と実装2026-11-07)）

**2026-11-07 決算 B1C2（7531）**: 実機PASS（CLOSING_IMPORT_PRESERVED）。本決6件すべて対応し **正式READY 2,481**。分割承認後 2,500、＋控除不可SIGNOFF後 2,503（試算）。残る決算は中決3605のみ

**2026-11-08 振替伝票入力行数64・中間決算**: 64行設定は実機未確認のため、会社を64にすると全仕訳BLOCK（`VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED`）。**正式READY 2,481（変化なし）**。16行超30仕訳のうち物理行64以内は27、Probe全PASSで26仕訳が解消見込み（試算 2,507〜2,508、＋分割承認 2,509。控除不可は64では止めたまま）。第5回Probe（13ファイル＋fallback、上限は物理行と片側明細を区別）実機待ち。控除不可は64に引き継がない。中決3605はJDL実機でしか確認できず、画面調査の手順とProbeを用意（[詳細](yayoi_buddies_evidence_campaign.md#20-振替伝票入力行数64行以内2026-11-08実機待ち)）

**2026-11-09 控除不可の承認は仕訳単位**: 従来の承認は税区分identity単位で、同じidentityの別取引（565と3558）や将来の仕訳にも及ぶ設計だった（承認は未取得のため実害なし）。仕訳の内容identityに紐づける形に修正し、内容変更で失効、従来形式は無効。正式READY 2,481・64行試算 2,508 不変、MF・ACT出力バイト一致（[詳細](yayoi_buddies_evidence_campaign.md#28-控除不可の承認スコープ仕訳単位と税理士の海外購入方針2026-11-09)）。

**2026-11-09 控除不可3仕訳のBLOCK依存関係（シミュレーション、保存なし）**: 3仕訳の SYSTEM_EVIDENCE 4種（形・複数課税行・会社端数の税額・税区分の組合せ）は、控除不可の明細が未確定であることから派生したもので、メモリ上の試算SIGNOFFでは消える。16行: SIGNOFF後は 565・3558 にBLOCKが残らず、425 は伝票分割の承認だけが残る（分割後の形は検証済み）。以前の「565はB1D4でBLOCK」は第4回NP PASSで解消済み。64行: 控除不可の技術Evidenceが範囲外のため、税理士判断だけでは3仕訳とも変換できない。新しいJDL Probeは不要（16行運用の場合）。正式READY 2,481／64行試算 2,508 は不変（[詳細](yayoi_buddies_evidence_campaign.md#27-控除不可3仕訳のblock依存関係と税区分確認uiの品質確認2026-11-09)）。

**2026-11-07 READY 157→0 調査**: 現在のWindows設定ではCLI・GUI経路とも正式READY 157/2,514のまま。0は、科目承認0件の古い設定（repo内 `data/private/yayoi_store`）を読んだ場合に再現（[詳細](yayoi_buddies_evidence_campaign.md#14-正式ready-1570-の調査2026-11-07)）。診断に設定の識別情報と理由別の対処を追加。判定は緩和していない。

**2026-11-07 Windows 税設定保存失敗（build aa7945e）**: 原因は、下書き状態の確認画面が「名称が取込欄に入らない補助」を選択肢に出し、その承認が税設定の確定時に使用不可へ分けられて整合チェックに失敗したこと。確認画面と確定処理を同じ集合にし、使用不可を指す承認だけを未確認に戻して保存できるようにした。診断は、税設定が下書きの間は仕訳構造・税を「未評価」と表示（602は旧フォールバックの数字）。修正後の設定コピーでは正式READY 998（行数16入力で2,472の試算）。実環境AppDataは未変更。[詳細](yayoi_buddies_evidence_campaign.md#15-windowsで税設定を保存できなかった問題2026-11-07build-aa7945e)

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
| 弥生→JDL | 会社B（インポート形式）は `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`。会社A（仕訳日記帳 汎用形式）のformal routeは未検証 | 会社B 80仕訳の全件往復 PASS。会社Aは合成target 3D3C/4D4Cのみ実機往復PASS、Human mappingとsource→formal E2Eは未完了。上の弥生の節を参照 |

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

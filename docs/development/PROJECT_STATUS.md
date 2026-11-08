# PROJECT STATUS — 弥生（会社A）→ JDL IBEX 出納帳35.5

**この文書は進捗の索引です。** 数字・判断の正本は [current_evidence_status.md](current_evidence_status.md)、実機操作の履歴は [jdl_real_evidence_log.md](jdl_real_evidence_log.md)、経緯は [yayoi_buddies_evidence_campaign.md](yayoi_buddies_evidence_campaign.md)。顧客の値は書かない。

最終更新: 2026-11-08（第5回 64行Probe の解析後・比較診断UI追加）

### 16行・64行の比較診断UI
- 弥生の確認画面の行数設定欄から「16行・64行を比較…」。保存済みProfileによる正式判定と、別設定の条件付き試算を並べる。未保存の入力は含めない。
- CompanySettingを保存せず、production `YayoiJdlWorkflow.assess` を両設定で実行する。行数変更時のProfile revision処理だけを保存サービスと共有し、別設定の分割承認を流用しない。
- 仕訳ID・借方明細数・貸方明細数・両設定のBLOCK理由・変化を表示。「全仕訳」「設定でREADYが変わる」「両設定でBLOCK」で絞り込み可能。正式出力・承認・設定変更のボタンは設けない。
- **数え方の限界**: 64行には片側明細数の実機Evidenceがあり、`max(借方明細数, 貸方明細数)`で判定。16行側は既存の保守的な物理行判定を維持する。64行の数え方を未検証の16行へ一般化しない。画面には両側の明細数と判定根拠を明示する。
- **表示の整理（2026-11-08、Windows実画面の指摘後）**: 比較ダイアログは判定・データを変えず、BLOCK理由の重複表示を除去（全コードはデータとツールチップに保持）、長い仕訳IDは中間省略＋ツールチップ、長い日本語は折り返し、列幅をStretchにして水平スクロールを抑え、ボタンを「閉じる」に。確認画面「その他」タブはスクロール領域に入れ、「件数の内訳と数え方」の展開本文は高さ上限（200px）＋内部スクロールにして、警告欄・ボタンが欠けないようにした。
- 既存AppDataコピーの再計算（保存設定16、2,514仕訳）:

| 比較指標 | 16行（保存設定） | 64行（条件付き） |
|---|---:|---:|
| READY | 2,481 | 2,502 |
| BLOCK（仕訳単位・重複なし） | 33 | 12 |
| 上限超過 | 30 | 2 |
| 分割案を構成できる候補 | 20 | 1 |
| 分割承認待ち（他条件も評価済み） | 19 | 1 |

- 64行のみREADY 27件、16行のみREADY 6件、両設定BLOCK 6件。理由別件数・分割関連件数は重複するため合算しない。分割候補でも分割後のEvidenceが不足すれば承認待ちには進めない。
- 64行の決算整理・控除不可・未観測形状、中間決算は引き続きBLOCK。registry（16行184・64行30）はこのUI対応では変更しない。
- MF 482件（2期分）・ACT 80件を保存設定で再評価し、一時出力と既存正式CSVのバイト一致を確認。一時ファイルはprivate内で生成・削除し、既存設定・正式CSVは変更しない。

## 更新のしかた（新しいEvidenceを得たとき）
1. 「完了済みEvidence」と「再実施不要」を先に読み、**すでに ✅ の項目は取り直さない**。
2. 結果を `jdl_real_evidence_log.md` に1行追記し、ここでは該当行（状態・Evidence ID・参照ファイル）だけを更新する。
3. READYは `PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_formal_rediagnosis --source data/private/yayoi_buddies/source.txt --company-store <AppDataのコピー> --company-id company-f92affc1f3ed43c8aee36380ab612f9d --l0-only` で再計算し、下の表を書き換える（保存設定は変更しない）。
4. 件数の表と最新テスト結果を更新。`git ls-files data/private | wc -l` が 0 であることを確認。

## 1. READY（会社A 2,514仕訳）
| 区分 | 件数 | 条件 |
|---|---:|---|
| **正式READY（保存済み設定＝16行）** | **2,481** | AppDataのコピーで再計算（2026-11-08） |
| 条件付き: 16行・伝票分割の承認後 | 2,500 | 試算。税理士の承認記録が必要 |
| 条件付き: 16行・＋控除不可SIGNOFF | 2,503 | 試算 |
| 条件付き: アプリの行数を64にした場合 | 2,502 | 試算。保存設定の変更が必要（Human判断）。決算7・控除不可2・425・4012・1739は止まる |
| 条件付き: 64行・＋分割承認（1739） | 2,503 | 試算 |
| 他社 | MF 482/482（出力SHA不変）、ACT 80/80（出力SHA不変） | 回帰: 2026-11-08 バイト一致 |

## 2. 使用しているJDLバージョン・会社設定
- JDL IBEX 出納帳 **35.5**、税抜・原則課税・一括比例配分、端数処理 売上=切上げ／仕入=四捨五入。
- 振替伝票入力行数: 選択肢は「16行以内」「64行以内」。本番の会社Aの保存設定は **16**（`voucher_row_limit`）。64は複製会社でのみ実機確認。
- Evidenceの適用範囲は上の設定に限る（`adapters/output/jdl/scoped_evidence.py`）。範囲外（別の端数・未確認の行数）は適用しない。
- 登録済みの行数設定: 16（既存184ケース）と64（30ケース）。それ以外は `VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED` でBLOCK。

## 3. 完了済みEvidence（再実施不要）
| 項目 | 状態 | Evidence ID | 参照 |
|---|---|---|---|
| 16行設定: 構造・税・端数・科目別（registry 184ケース） | ✅ | `EVID-YAYOI-JDL-35-5-BUDDIES-*`（`scoped_evidence_registry.py` の `row_limit_scope=16`） | campaign 第6〜18章 |
| 16行設定: 限界（16行取込・17/25/50/73拒否） | ✅ | `...-VOUCHER-ROW-LIMIT-16-001` | campaign 第3a章 |
| 摘要 CP932 64バイトまで保持 | ✅ | campaign 第9.4章 | private `evidence_gap_20261106` |
| 新規JDL科目12ケース | ✅ | `...-GAP-NA-*` | campaign 第11章 |
| 補助コード+名称の保持・補助E2E（1551-0169・3141-0137） | ✅ | `...-SUBKEEP-1551-001` / `-3141-001` | `scoped_subaccount_evidence.py`、campaign 第12・17.4・18章 |
| 非仕入の配置・伝票分割後の形（SP 7・NP 3） | ✅ | `...-GAP-SP-*` / `-NP-*` | campaign 第17〜18章 |
| 決算整理（本決6件、13月日付・B1C2含む）16行設定 | ✅ | `...-CLOSING-MONTH13-IMPORT-001` / `-B1C2-001` / `-SELF-EXPORT-001` | `closing_entries.py`、campaign 第19章 |
| 控除不可の消費税集計の技術確認 | ✅（承認は未取得） | `...-NONCREDIT-NONPUR-*` | campaign 第16章 |
| **64行設定: 限界・数え方** | ✅ 2026-11-08 | `...-VOUCHER-ROW-LIMIT-64-001` | private `row64_probe_20261108`、campaign 第20.5章 |
| **64行設定: 17〜64行の形25種類＋ROWS64＋INV＋REL** | ✅ 30ケース | `...-GAP-L64-*-SYNTHETIC-ROUNDTRIP-001` | 同上 |
| **64行設定: 補助コード+名称（4件）** | ✅ | `...-64-CARRY-SUBACCOUNT-001` | 同上 |
| MF 482件 FY2026-05 全件往復 | ✅（FY2027-05は未） | `EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001` | current_evidence_status.md |
| 弥生ACT 80件全件往復 | ✅ | `EVID-YAYOI-JDL-35-5-COMPANYB-202603-FULL-ROUNDTRIP-001` | 同上 |

### 64行設定の実機結果（2026-11-08、Probe日 2026-06-14）
- 再Export 43仕訳・1,108行がstrict PASS、重複0、説明できない仕訳0。Import件数は**未記録**（推測しない）。
- 借方65明細（R64OVERD）・貸方65明細（R64OVERC）は「伝票内の仕訳数が多すぎます」で拒否（利用者報告、エラーログ原本は共有待ち）。
- 物理65行（借方64＋貸方1／借方1＋貸方64）は取込・一致 → **数え方は片側の明細数**（CSVの物理行ではない）。
- 登録: `ROW_LIMIT_SCOPES[64]` = LINES_PER_SIDE、引き継ぎ = LAYOUT・TAX_RELATION・SUBACCOUNT。

## 4. 未検証の条件（BLOCKのまま）
| 条件 | 現状 | 必要なもの |
|---|---|---|
| **64行設定での決算整理（13月）取込** | 未実施。64では本決6件をBLOCK（`carries(64,"CLOSING")`=False） | `row64_probe_20261108/closing/` の2ファイルを64複製で取込→「含む／含まない」で再Export→`yayoi_row64_probe check --closing-with/--closing-without`（既存の16行Evidenceは取り直さない） |
| 64行設定での控除不可 | 引き継がない（承認も記録不可） | 64行設定で消費税集計の確認が必要（実施は事務所判断） |
| 64行設定の17〜64行で未観測の形 | BLOCK（観測した形だけ通す） | 新しい形が出たときだけ追加Probe |
| 中間決算（仕訳3605） | JDL実機でしか確認できない | `interim_closing_probe_20261108/` の画面調査 |
| 仕訳425の複数課税行・端数（15行超の形） | SYSTEM_EVIDENCE 4種 | 控除不可と併せて判断 |
| FY2027-05のMF実機往復（MF 104仕訳） | 未実施 | current_evidence_status.md の手順 |
| Import件数（第5回） | 未記録 | 記録があれば `import_results_20260614.json` に追記 |

## 5. 未承認の条件（Human／税理士）
- 伝票分割の承認（16行: 19件が対象 / 64行: 1739の1件）。承認は行数ごと。**未取得**。
- 控除不可（10%・軽減8%）のSIGNOFF。**未取得**（16行設定のみ）。
- 補助30種類の登録判断、付箋の扱い、科目・税区分の確認 — current_evidence_status.md 参照。
- 保存設定の振替伝票入力行数を16→64に変えるか（変えると分割・控除不可の承認は無効になり記録し直し）。

## 6. 現在のBLOCK理由（16行・保存設定、正式READY 2,481 に対する残り33）
- `HUMAN:VOUCHER_SPLIT_APPROVAL` 19（分割承認待ち）／`HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED` 11（分割規則の対象外の16行超）
- 税区分（控除不可）3、構造Evidence不足3（425ほか）、決算（中決3605）1
- 64行にした場合: 425（控除不可）、4012（マイナス明細で分割不可）、1739（分割承認）、決算7、控除不可2

## 7. 次に必要な最小限のJDL操作
1. **（任意・64行を使う場合）** 64行設定の複製に `closing/` の2ファイルを「決算整理を含む」で取込 → 2026-07-31 を「含む」「含まない」で再Export（2回）。
2. （任意）中間決算の画面調査（手順書: `interim_closing_probe_20261108/JDL操作手順_中間決算_20260131.md`）。
3. 16行のまま運用する場合、新たなJDL操作は不要（分割・控除不可は税理士承認の記録のみ）。

## 8. すでに検証したため再実施不要
- 16行設定のすべて（上表）、特に本決6件の決算整理（13月・B1C2）と補助E2E。
- 64行設定の限界・数え方・17〜64行の形30ケース・補助4件・INV・REL（第5回）。
- 17/25/50/73行の拒否（16行）、65明細の拒否（64行）。
- MF 482件FY2026-05、ACT 80件の全件往復。

## 9. 最新のテスト結果（2026-11-08）
- `PYTHONPATH=src python3 -m unittest discover -s tests`: **1,370件 OK（skip 42）**、compileall・`git diff --check` 問題なし。
- 回帰: MF 期別出力 `ec2bcc3b…`（FY2026-05）/ `090f3633…`（FY2027-05）、ACT `97426c9a…` — 変更前コードとバイト一致。registry 16行184ケース不変。
- 実環境AppData未変更、`git ls-files data/private` = 0。

## テスト記録
| 日付 | 結果 | 備考 |
|---|---|---|
| 2026-11-08 | 1,370件 OK（skip 42） | 第5回64行Evidence登録後。ベースライン（第5回前）は1,351件 |
| 2026-11-08 | Linux: 1,377件 OK（skip 43、終了0）。Windows Python 3.12.10＋PySide6 6.12.0（offscreen）: 1,377件、skipなし、failures 2＋errors 9、終了1 | Windows失敗11件はテスト側のOS依存（CSV改行、パス区切り、PyInstaller成果物順）で、未変更ファイルかつ今回の機能と無関係 |
| 2026-11-08 | Qt終了時Abort: 原因＝`test_qt_parent_policy_dialog`が親なしダイアログを破棄せずGCに任せていた。テストにcleanup（close/deleteLater）を追加し解消。全体で`Fatal Python error`なし | 本体コードは変更なし |
| 2026-11-08 | 表示修正後: Linux全体OK、Windows Qt関連（比較・レイアウト）OK | Windows実画面での確認項目は報告参照。Windows固有の失敗11件は未解決のまま別管理 |

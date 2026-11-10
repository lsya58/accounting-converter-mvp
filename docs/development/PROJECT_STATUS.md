# PROJECT STATUS — 弥生（会社A）→ JDL IBEX 出納帳35.5

**この文書は進捗の索引です。** 数字・判断の正本は [current_evidence_status.md](current_evidence_status.md)、実機操作の履歴は [jdl_real_evidence_log.md](jdl_real_evidence_log.md)、経緯は [yayoi_buddies_evidence_campaign.md](yayoi_buddies_evidence_campaign.md)。顧客の値は書かない。

最終更新: 2026-11-10（Pilot-1・Pilot-2 実機往復の照合。どちらも正式判定は `NORMALIZATION_ACCEPTANCE_PENDING`）

### Pilot-1 実機往復と Pilot-2 準備（2026-11-10、計画: [pilot_e2e_plan.md](pilot_e2e_plan.md)、campaign 第29章）
- **Pilot-1（2025-12-01〜12-30、207仕訳・465明細）**: Windows EXE変換 → JDL実機Import → 再Export まで完了。欠落・重複・余分0、金額・借貸・日付・科目・補助・税区分・税額・伝票構造・決算区分は一致（既知の正規化2,199セル）、説明できない差分0。非保持171項目（親科目のみの補助・54組）は利用者確認済みで監査記録PASS。
- **正式判定: `NORMALIZATION_ACCEPTANCE_PENDING`**。JDLが摘要の末尾の空白を削除した45行（44伝票）は実機Evidenceとして登録した（`EVID-YAYOI-JDL-35-5-BUDDIES-PILOT1-DESCRIPTION-TRAILING-SPACE-REMOVED-001`）が、**情報欠落の許容判断は未記録（税理士に確認中）**。記録するまで正式PASSにしない。許容判断を代行しない。
- 修正（未commit）: 摘要末尾空白の正規化検出（Evidenceの範囲内のみ）、80%経過措置の税額比較（書き出し側と同じ `ev.target_tax_amount`）、監査JSONを出力SHA-256で対応付け（改名OK、0件・複数はFAIL）、許容判断の記録ツール。テスト 1,446件 OK（skip 61）。
- **Pilot-2（2026-05-01〜05-29、174仕訳・434明細、全件READY）**: Windows EXE変換・JDL実機Import・再Export完了。会計データの不一致0、監査137項目PASS。摘要末尾空白48行（44伝票）のうち1行（伝票1939）が半角3個で、Pilot-1のEvidenceの範囲外のため一度FAIL。実機の再Exportを根拠に追加Evidence `EVID-YAYOI-JDL-35-5-BUDDIES-PILOT2-DESCRIPTION-TRAILING-SPACE-REMOVED-001`（半角3個だけ）を別エントリで登録し、再照合して **`NORMALIZATION_ACCEPTANCE_PENDING`**（説明できない差分0）。**Pilot-1の許容判断はPilot-2に適用しない**（それぞれ別の記録）。

### 控除不可の承認スコープを仕訳単位に修正（2026-11-09、設計: [yayoi_tax_review_design.md](yayoi_tax_review_design.md) 第7・8章）
- **不具合（修正済み）**: 控除不可の承認は弥生の税区分identity単位で、10%を1件承認すると取引内容の異なる 565・3558 の両方と将来の同じidentityの仕訳まで変換対象になった（再現テストで確認）。承認記録は実AppDataに0件で、実害はない。
- **修正**: 承認は仕訳を明示し（`--source`＋`--journal`）、仕訳の内容identity（ファイル名・行番号を含まない既存の `source_journal_content_sha256`）に紐づける。仕訳ごとに承認者・税理士・参照・日付を記録し監査記録に出力。内容が変われば失効、未変更の再出力は一致、同一内容の重複は拒否・BLOCK、従来形式（identity単位）の承認は無効。正式診断は承認のない控除不可の仕訳に `HUMAN:TAX_MAPPING` を明示的に付ける。通常の税区分mappingは従来どおり会社全体で再利用。
- 準備状況画面: 仕訳ごとに「税理士の承認記録（この仕訳）」を表示（他の仕訳の承認は表示しない）。税区分確認画面: 承認があっても identity を「確認済み」として隠さず、承認が仕訳ごとであることを表示。
- 実データ試算（メモリ上）: 565だけ承認→565のみREADY（3558はBLOCK）、3558だけ→3558のみ、両方→2,483。正式READY 2,481・64行試算 2,508 不変。
- 回帰: ACT 正式CSV `97426c9a…` とバイト一致（監査記録はHEADのコードと同一）、MF 期別 `ec2bcc3b…`・`090f3633…` とバイト一致。
- 税理士の追加回答「海外からの購入は全て非課税仕入でよい」を運用方針として記録（個別承認ではない）。3558 は (a) 控除不可のまま非仕入で取込（仕訳単位の承認）／(b) 弥生で非課仕入に修正して再出力（既存の確認済み対応で JDL 非仕入）／(c) 対象外 のどれかを確認する。汎用の「海外購入」ルールは追加しない。

### 控除不可3仕訳のBLOCK依存関係・税区分確認UI（2026-11-09、campaign 第27章）
- シミュレーション（AppDataコピー、試算SIGNOFFはメモリ上のみ。ストアは試算マーカー付きの承認を保存拒否）:

| 仕訳 | 控除不可に直接起因 | 税区分未確定で派生（試算で消える） | 税区分と無関係 | 税理士判断・承認記録の後に残る（16行） | 64行 |
|---|---|---|---|---|---|
| 425 | TAX_MAPPING | SHAPE・MULTIPLE_TAXED_LINES・EXPLICIT_TAX_COMPANY_ROUNDING・TAX_IDENTITY_NOT_COMPOSABLE | 16行超（VOUCHER_ROW_LIMIT_EXCEEDED） | 伝票分割の承認のみ（分割後の形は検証済み） | 控除不可Evidenceが範囲外→変換不可 |
| 565 | TAX_MAPPING | SHAPE・MULTIPLE_TAXED_LINES・EXPLICIT_TAX_COMPANY_ROUNDING | なし | なし | 同上 |
| 3558 | TAX_MAPPING | 同上 | なし | なし | 同上 |

- 以前の「565はB1D4配置でBLOCK」は第4回NP（B1D4）PASS後は成立しない。16行の試算: SIGNOFFのみ 2,483、＋分割承認 2,503（従来どおり）。64行では元の税区分が別区分（対象外・非課仕入）なら既存Evidenceで3仕訳とも通る（感度分析。修正の提案ではない）。
- 「非仕入として扱う」承認の場合、新しいJDL Probeは不要。元の税区分を修正する場合は弥生で修正→再出力→再診断（アプリ内修正は未実装）。
- UI: 準備状況画面の「税区分の確認が必要」を仕訳ごとの要点（元の税区分・税率・確認が必要な理由・税理士が判断すること・技術的に残っている問題・判断後の見通し）＋開閉式の詳細（元の明細・その他の税区分・BLOCKの内訳）に再構成。「未検証の仕訳形状」項目は件数を変えずに「税区分の確定待ち（試算）」と注記。見通しは controller が試算プロファイルで計算（READY・保存は変えない）。
- 修正した不具合: 狭い画面で長いBLOCKコードが折り返せず、詳細欄の右側が切れていた（636px＞288px）→ 利用者向け名称で表示し、コードは既存の詳細欄に全件残す。
- テスト: Linux 1,416件 OK（skip 60＝PySide6なし59・pypdfなし1。GUIのPASSとしては数えない）。Windows Python 3.12.10＋PySide6 6.12.0 offscreen: `test_resolution_report` 27件 OK（QT_SCALE_FACTOR 1／1.25／1.5、skip 0）。正式READY 2,481・64行試算 2,508 不変、registry・変換出力・実AppData未変更。

### 控除不可3仕訳の税理士回答と「税区分の確認」表示（2026-11-09、設計: [yayoi_tax_review_design.md](yayoi_tax_review_design.md)）
- 税理士回答（暫定見解）: ①②は理由不明で入力ミスの可能性、③は海外商品購入で元の税区分が誤りとの見解。正式な税区分変更の承認ではない。①②③と425・565・3558の対応は記録がなく、③が3558と整合するのみ（摘要）。
- 原データ: 425=軽減8%・区分記載・控除不可・税額0（33行の伝票、16行超も）／565=10%・区分記載・控除不可×2明細・税額0／3558=10%・区分記載・控除不可×1明細・税額0。3仕訳とも他の明細は適格・100%。
- BLOCK: 3仕訳とも HUMAN:TAX_MAPPING＋SYSTEM_EVIDENCE（SHAPE_UNVERIFIED／MULTIPLE_TAXED_LINES／EXPLICIT_TAX_COMPANY_ROUNDING）。425は+VOUCHER_ROW_LIMIT_EXCEEDED・TAX_IDENTITY_NOT_COMPOSABLE。税区分を解決しても構造Evidenceが残れば READY にならない。
- UI/モデル: `application/tax_review_facts.py`（元の弥生値の読み取り専用抽出）を解決項目モデルに接続。「変換の準備状況」の項目名を「税区分の確認が必要」に変更し、元の行・摘要・元の税区分・税額・JDLでの扱い・残らない情報・確認ポイントを表で表示。誤りと断定する表現なし、承認ボタンなし。
- 判定不変: 正式READY 2,481／2,514（コード再計算）、registry・変換出力・AppData未変更。テスト Linux 1,407件 OK（skip 56。PySide6が無いQtテストはskip、Windows実画面未確認）。

### 変換の準備状況UI（2026-11-09、campaign 第25章）
- 読み取り専用の解決項目モデル（`resolution_report`）＋「変換の準備状況」ダイアログ＋分割承認ダイアログ（利用者の明示操作のみ・現在の行数に紐づく）を追加。メイン画面の実行前チェックと確認画面から開く。READY判定・registry・変換出力は変更なし（16行 2,481／64行試算 2,508）。控除不可・負の金額・中間決算・実機Evidence不足には承認ボタンを置かない。Windows実画面での確認は未実施（offscreenテストのみ）。
- **操作画面の整理（同日）**: 上段は入力元・JDL会社設定・正式READY/BLOCK・64行試算と比較ボタンを表示。次の操作では設定比較を先に提示し、対応項目は短い名称・件数・担当・操作で一覧化。選択後は「次にすること」「担当」「ほかに残る条件」を先に示し、確認済み事項・全BLOCKコード・仕訳IDは展開して確認できる。対象件数は仕訳単位で数え、項目別件数を合計しない。
- 分割承認画面は対象仕訳一覧から各仕訳の分割前後・金額合計・税額・再構成検査を確認する。承認欄は開閉式にして表の高さを確保。対象全件が取得でき、各仕訳を表示して確認し、担当者・税理士・承認参照・日付・明示チェックがそろうまで記録不可。記録の実際の範囲は会社・行数・分割規則であり、後続の該当仕訳にも適用されることを明示。保存後は正式診断で再判定する。既存の承認ルール・Evidence条件は変更しない。

### 第6回b: 4012の負の明細Probe（2026-11-09、campaign 第24章）
- JDL取込は全件拒否。借方金額・借方消費税の「-」を「数値以外」として拒否（確認した範囲に限る）。分割1(37行・負なし)は「仕訳数が多すぎます」で、取込時の行数設定が64でなかった疑い（未確定）。registry不変、4012はBLOCK維持、追加のJDL操作は不要（先に税理士判断）。

### 4012・1739（2026-11-09、campaign 第23章）
- 4012: 規則V1の「全明細が正」条件＋負の金額のJDL Evidence皆無＋分割後C1D36の配置未確認で、BLOCK維持。安全な分割形は設計済み（負の明細を動かさず36+36）だが、最小Probe（`negative_probe_20261109`、1ファイル）の実機結果と別規則の税理士承認が必要。
- 1739: 分割承認のみ残り（配置Evidence済み）。承認用の説明は private `split_approval_brief_1739_64.json`。承認は未実施。READY 2,481（16行）／2,508（64行）不変。

### 第6回 64行・決算整理（2026-11-09、campaign 第22章）
- 64行の決算整理再Exportが CLOSING_IMPORT_PRESERVED。`ROW_LIMIT_SCOPES[64]` に CLOSING を追加（`...-64-CARRY-CLOSING-001`）。64行条件付き READY **2,502 → 2,508**（コード再計算）、正式READY（16行）2,481不変。64行の残りBLOCK 6: 425・565・3558・1739・3605・4012。

### 消費税区分の調査（2026-11-09、詳細は campaign 第21章）
- 控除不可は会社Aで3仕訳（425・565・3558、いずれも区分記載・税額0）。理由は取引内容から断定できず税理士確認待ち。BLOCK変更なし。
- 80%→70%（2026-10-01〜）: `application/yayoi_credit_period.py` を追加。取引日と控除割合が食い違う行はBLOCK（`HUMAN:TRANSITIONAL_CREDIT_PERIOD`）。70%の識別名は候補なし。JDLの70%税区は未確認。READY 2,481不変。
- 10%・軽減8%の実装変更なし。テスト Linux 1,384件 OK（skip 46）。

### 16行・64行の比較診断UI
- 弥生の確認画面の行数設定欄から「16行・64行を比較…」。保存済みProfileによる正式判定と、別設定の条件付き試算を並べる。未保存の入力は含めない。
- CompanySettingを保存せず、production `YayoiJdlWorkflow.assess` を両設定で実行する。行数変更時のProfile revision処理だけを保存サービスと共有し、別設定の分割承認を流用しない。
- 仕訳ID・借方明細数・貸方明細数・両設定のBLOCK理由・変化を表示。「全仕訳」「設定でREADYが変わる」「両設定でBLOCK」で絞り込み可能。正式出力・承認・設定変更のボタンは設けない。
- **数え方の限界**: 64行には片側明細数の実機Evidenceがあり、`max(借方明細数, 貸方明細数)`で判定。16行側は既存の保守的な物理行判定を維持する。64行の数え方を未検証の16行へ一般化しない。画面には両側の明細数と判定根拠を明示する。
- **表示の整理（2026-11-08、Windows実画面の指摘後）**: 比較ダイアログは判定・データを変えず、BLOCK理由の重複表示を除去（全コードはデータとツールチップに保持）、長い仕訳IDは中間省略＋ツールチップ、長い日本語は折り返し、列幅をStretchにして水平スクロールを抑え、ボタンを「閉じる」に。確認画面「その他」タブはスクロール領域に入れ、「件数の内訳と数え方」の展開本文は高さ上限（200px）＋内部スクロールにして、警告欄・ボタンが欠けないようにした。
- 既存AppDataコピーの再計算（保存設定16、2,514仕訳）:

| 比較指標 | 16行（保存設定） | 64行（条件付き） |
|---|---:|---:|
| READY | 2,481 | 2,508 |
| BLOCK（仕訳単位・重複なし） | 33 | 6 |
| 上限超過 | 30 | 2 |
| 分割案を構成できる候補 | 20 | 1 |
| 分割承認待ち（他条件も評価済み） | 19 | 1 |

- 64行のみREADY 27件、16行のみREADY 0件、両設定BLOCK 6件。理由別件数・分割関連件数は重複するため合算しない。分割候補でも分割後のEvidenceが不足すれば承認待ちには進めない。
- 64行の控除不可・未観測形状、中間決算は引き続きBLOCK。64行の本決算6件は第6回の実機Evidenceで解放済み。registry（16行184・64行30）はこのUI対応では変更しない。
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
| 条件付き: アプリの行数を64にした場合 | 2,508 | 試算。保存設定の変更が必要（Human判断）。控除不可3・4012・1739・3605は止まる |
| 条件付き: 64行・＋分割承認（1739） | 2,509 | 試算 |
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
| ~~64行設定での決算整理（13月）取込~~ | ✅ 2026-11-09 解決（第6回）。`carries(64,"CLOSING")`=True。以下は旧手順（実施済み）: | `row64_probe_20261108/closing/` の2ファイルを64複製で取込→「含む／含まない」で再Export→`yayoi_row64_probe check --closing-with/--closing-without`（既存の16行Evidenceは取り直さない） |
| 64行設定での控除不可 | 引き継がない（承認も記録不可） | 64行設定で消費税集計の確認が必要（実施は事務所判断） |
| 64行設定の17〜64行で未観測の形 | BLOCK（観測した形だけ通す） | 新しい形が出たときだけ追加Probe |
| 中間決算（仕訳3605） | JDL実機でしか確認できない | `interim_closing_probe_20261108/` の画面調査 |
| 仕訳425の複数課税行・端数（15行超の形） | SYSTEM_EVIDENCE 4種 | 控除不可と併せて判断 |
| FY2027-05のMF実機往復（MF 104仕訳） | 未実施 | current_evidence_status.md の手順 |
| Import件数（第5回） | 未記録 | 記録があれば `import_results_20260614.json` に追記 |

## 5. 未承認の条件（Human／税理士）
- 伝票分割の承認（16行: 19件が対象 / 64行: 1739の1件）。承認は行数ごと。**未取得**。
- 控除不可（10%・軽減8%）のSIGNOFF。**未取得**（16行設定のみ）。2026-11-09以降は**仕訳ごと**に記録する（identity単位の承認は無効）。
- 補助30種類の登録判断、付箋の扱い、科目・税区分の確認 — current_evidence_status.md 参照。
- 保存設定の振替伝票入力行数を16→64に変えるか（変えると分割・控除不可の承認は無効になり記録し直し）。

## 6. 現在のBLOCK理由（16行・保存設定、正式READY 2,481 に対する残り33）
- 仕訳別一覧・分類（A〜E）・試算・次の実装: [yayoi_buddies_block33_plan.md](yayoi_buddies_block33_plan.md)（2026-11-10 再計算: 16行で分割承認＋SIGNOFFなら2,503、64行＋分割承認なら2,509）
- `HUMAN:VOUCHER_SPLIT_APPROVAL` 19（分割承認待ち）／`HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED` 11（分割規則の対象外の16行超）
- 税区分（控除不可）3、構造Evidence不足3（425ほか）、決算（中決3605）1
- 64行にした場合（残り6）: 425・565・3558（控除不可）、4012（マイナス明細で分割不可）、1739（分割承認）、3605（中決）

## 7. 次に必要な最小限のJDL操作
-1. Pilot-1・Pilot-2とも実機操作は完了。残りは税理士の摘要末尾空白の許容判断（記録のみ、JDL再操作は不要）。
0. 4012: 負の明細はCSVで取り込めないと判明（`negative_probe_20261109` 実施済み）。税理士の方針決定までJDL操作は不要。
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
| 2026-11-09 | 承認スコープ修正後: Linux 1,428件 OK（skip 61: PySide6なし60・pypdfなし1）。Windows offscreen 1,428件 skip 0、failures 2＋errors 15（HEADでも再現する既存のOS依存17件と同一。今回の `test_noncredit_approval`・`test_resolution_report` 53件は倍率1／1.25／1.5でOK）。ACT・MF出力バイト一致 | 控除不可の承認を仕訳単位に |
| 2026-11-09 | Linux 1,416件 OK（skip 60: PySide6なし59・pypdfなし1）。Windows offscreen `test_resolution_report` 27件 OK（倍率1／1.25／1.5）。Windows全体 1,416件: failures 2＋errors 15（すべてHEADのコードでも同じく再現＝既存のOS依存: CSV改行・CP932読込・パス・成果物順。今回の変更と無関係） | 控除不可3仕訳の依存関係・税区分確認UI |
| 2026-11-10 | Linux 1,446件 OK（skip 61）。Pilot-1 実機往復の最終整備: 摘要末尾空白・80%経過措置・監査JSONのSHA-256対応付け・許容判断ツールの回帰18件を追加（変更前は1,428件） | 実機の再操作なし。Pilot-1 実データの回帰（取込CSVのバイト一致）を含む |
| 2026-11-10 | Linux 1,452件 OK（skip 61）。Pilot-2の追加Evidence（半角3個）: エントリ履歴・未観測の並びの拒否・行ごとのEvidence紐づけ・Pilot-2実データ回帰を追加（直前は1,446件） | Pilot-1の45行の結果は不変 |
| 2026-11-08 | 表示修正後: Linux全体OK、Windows Qt関連（比較・レイアウト）OK | Windows実画面での確認項目は報告参照。Windows固有の失敗11件は未解決のまま別管理 |

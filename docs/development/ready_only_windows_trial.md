# READYのみ変換: Windows EXEでの確認とJDL実機検証の準備（2026-11-11）

顧客の値は書かない。READYのみ変換は**全件移行ではない**。会社Aの正式READYは2,480/2,514、BLOCKは34（[計画](yayoi_buddies_block33_plan.md)、[状況](PROJECT_STATUS.md)）。JDL実機へのREADYのみCSVの取込は**未実施**。摘要末尾空白の許容判断は**未取得のまま**（取得しない）。

## 1. Windows側の現状と、既存クローンに触らない理由
既存クローン `C:\Users\leoli\projects\accounting-converter-mvp`（読み取り専用で確認した結果）:
- `git status` が約490件の変更を表示する。内容差は無く、改行コード（作業ツリーがCRLF）だけの違い。未追跡は `src\accounting_converter.egg-info\` のみ。
- `scripts\build_windows.ps1` は、作業ツリーが**完全にクリーン**でないと、また `.venv-build` が**既に存在すると**停止する。このクローンには `.venv-build`・`build`・`dist`（2026-11-09のビルド）がある。
- 上の状態で `git pull` すると、変更表示のファイルと衝突して止まる可能性がある。

そこで、**既存クローンは一切変更せず（旧EXEもそのまま保護）**、別のフォルダに新しくcloneしてビルドする。削除・`git reset`・`git checkout -- .` は不要。

## 2. 新しいEXEを作る（PowerShellにそのまま貼り付け）
前提: Windows に Git と Python 3.12（`py -3.12`）、インターネット接続（pip）。

```powershell
# 1) 既存クローンの状態を確認（変更はしない）
cd C:\Users\leoli\projects\accounting-converter-mvp
git status --short | Measure-Object -Line
git log --oneline -1

# 2) 別フォルダへ新規clone（CRLF変換を無効にして、クリーンな作業ツリーにする）
cd C:\Users\leoli\projects
git clone -c core.autocrlf=false -b develop https://github.com/lsya58/accounting-converter-mvp.git accounting-converter-mvp-ready-only
cd accounting-converter-mvp-ready-only
git config core.autocrlf false

# 3) 取得したコミットとクリーンさを確認
git log --oneline -3
git status --porcelain --untracked-files=all    # 何も表示されなければクリーン

# 4) ビルド（所要数分）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1

# 5) 起動
.\dist\AccountingConverter\AccountingConverter.exe
```

確認:
- 手順3の先頭が、報告したREADY-only commit（`feat(ready-only)…`）であること。
- 手順4が最後に `Build finished.` と表示すること。`dist\AccountingConverter\` にリリースマニフェストができる。
- 新EXEは**実AppDataの会社設定を読む**（旧EXEと同じ）。ビルドは設定を書き換えない。
- うまくいかなければ、エラーの最後の20行を共有する。既存クローンの `dist\` は残るので旧EXEにいつでも戻れる。

## 3. 会社Aの2,514仕訳で確認する
入力ファイル（読み取りのみ。アプリは入力を変更しない）:
`\\wsl.localhost\Ubuntu\home\yusya58\projects\father-tax\accounting-converter-mvp\data\private\yayoi_buddies\source.txt`
出力先は、リポジトリの外に新しいフォルダを作る（例: `C:\Users\leoli\Documents\ReadyOnly_Trial_20261111\`）。

### チェックリスト
操作: メイン画面で会社A（バディーズ）と上のファイルを選ぶ →「変換の準備状況…」。

- [ ] 2,514仕訳を読み込める（読み込みエラーなし）
- [ ] 診断が **READY 2,480 / 2,514**、**BLOCK 34**（2,481/33ではない）
- [ ] 画面下に「READYのみ変換…（全件移行ではありません）」ボタンが表示される
- [ ] 元の表示「この入力全体: 変換できません」が残っている（全件変換が成功したように見えない）
- [ ] ボタンを押すと、先頭に「これは全件移行ではありません」の警告が出る
- [ ] 件数が「入力 2,514仕訳 ＝ 変換対象（READY）2,480仕訳 ＋ 除外（未移行のまま残る）34仕訳」と表示される
- [ ] 除外一覧に34行（元の行・日付・伝票No.・借方金額合計・理由）が出る。元の行は次の34件: 425、462、503、565、1031、1094、1287、1739、1805、2329、2384、2986、3032、3109、3482、3558、3569、3605、4012、4117、4163、4700、4873、5426、5445、5545、6075、6100、6594、6621、7246、7265、7420、7519
- [ ] 7519（2026-07-31・本決・負の金額）が除外に入っている
- [ ] 3つの確認項目（全件移行ではない・二重取込の確認・除外分の扱い）と確認者名がそろうまで、出力ボタンが押せない
- [ ] 1項目でも外す／名前を消すと、出力ボタンが押せなくなる
- [ ] 保存先を選ぶと、最後に「全件移行ではありません。出力する仕訳: 2,480／除外する仕訳（未移行）: 34」の確認が出る。「いいえ」で何も出力されない
- [ ] 「はい」の後、4ファイルができる: `*.csv`、`*.csv.audit.json`、`*.csv.excluded.csv`、`*.csv.ready_only.json`
- [ ] 完了メッセージが「READYのみ変換が完了しました（全件移行ではありません）。変換済み 2,480仕訳（JDL 6,102行）／未移行 34仕訳」
- [ ] 同じ保存先へもう一度出力しようとすると拒否される（上書きしない）
- [ ] 実AppDataの会社設定・元の `source.txt` が変わっていない

### 4ファイルの独立した検証（WSLで実行）
出力フォルダをWSLから読み、AppDataのコピーに対して検証する（設定は変更しない）。

```bash
cd /home/yusya58/projects/father-tax/accounting-converter-mvp
mkdir -p /tmp/ro_trial && rm -rf /tmp/ro_trial/store && cp -r /mnt/c/Users/leoli/AppData/Local/AccountingConverter /tmp/ro_trial/store
export PYTHONPATH=src
OUT=/mnt/c/Users/leoli/Documents/ReadyOnly_Trial_20261111/<出力したCSV名>.csv
python3 -m accounting_converter.tools.yayoi_ready_only_output verify \
  --source data/private/yayoi_buddies/source.txt --company-store /tmp/ro_trial/store \
  --company-id company-f92affc1f3ed43c8aee36380ab612f9d --output "$OUT"
sha256sum data/private/yayoi_buddies/source.txt
```

- [ ] `verdict` が `PASS`、`audit_verdict` が `PASS`、`not_migrated_journals` が 34
- [ ] 隔離試験（このセッション）の出力と、CSV・除外一覧の**SHA-256が一致**する（同じ入力・同じ設定なら同一バイトになる想定。作成日時の入るmanifest/auditのSHAは一致しなくてよい）
- [ ] ファイルを1つ編集または削除すると `FAIL` になる（任意）

## 5. JDL実機へ進む前の注意（取込は今回しない）
**重複を避ける**: Pilot-1・Pilot-2（381仕訳）は、すでに検証用複製に取り込み済み。READYのみCSVは2025-12-01〜12-30と2026-05-01〜05-29の仕訳（Pilotと同じ内容）を含む。したがって:
- **Pilot用に使った複製には取り込まない**。会社Aのバックアップから、別の**空の検証用複製会社**を新しく復元して使う（本番会社には取り込まない）。
- 復元した複製が、取込前に**仕訳0件**であることを確認する（令和8年7月期、2025-08-01〜2026-07-31）。
- 設定は会社Aと同じ（振替伝票入力行数16、税抜・原則・一括比例、売上切上げ/仕入四捨五入、科目・補助マスターも同じ）。違えば止める。

**取込と再Export**（新しいJDL Probeは作らない。既存の確認済みEvidenceの範囲だけを使う）:
1. 複製へ `*.csv` を取り込む。**取込画面の件数とエラーの有無を記録する**（READYのみCSVは2,480仕訳・6,102行のはず）。
2. 期間 2025-08-01〜2026-07-31 を再Exportする。**「決算整理を含む」で出力**する（READYの本決6件は13月付の決算整理仕訳で出力され、確認済みの表現は「含む」でだけ再Exportに出る。決算整理を含まない出力は、対照として別に出してもよい）。
3. 再Exportを `pilot3` 等の新しいprivateフォルダに置く（取込CSV・再Exportは書き換えない）。

**検証**（既存の厳密照合を再利用）:
```bash
python3 -m accounting_converter.tools.yayoi_roundtrip_check \
  --source data/private/yayoi_buddies/source.txt --company-store /tmp/ro_trial/store \
  --company-id company-f92affc1f3ed43c8aee36380ab612f9d \
  --candidate "$OUT" --ready-only --reexport <再Exportのパス> \
  --record-out data/private/yayoi_buddies/<新しいフォルダ>/description_trailing_space_record.json
```
期待と判定:
- [ ] 取込CSVの `--ready-only` 検証が先に `PASS`（4ファイルのSHA-256が結ばれている）。そうでなければ止まる
- [ ] 2,480/2,480仕訳・6,102/6,102行、欠落・重複・余分0
- [ ] 日付・借貸・金額・科目・補助・税区分・税額・伝票構造・決算区分が一致（差分は既知のJDL正規化だけ）
- [ ] 本決6件が、決算整理（日付20261331）のまま「含む」の再Exportに出る（Evidence: `...CLOSING-MONTH13-IMPORT-001`・`...-B1C2-001`）
- [ ] 摘要末尾空白の削除は、登録済みの並び（半角1・半角2・全角1・半角3）だけ。ここでの件数は取込CSV側の末尾空白の件数と一致するはず（元データでは598行）。**それ以外の並びは `UNEXPECTED_CHANGE` のまま**で、勝手にEvidence化しない
- [ ] 非保持情報の監査 `PASS`（1,176仕訳・2,397項目、すべて利用者確認済みの範囲）
- [ ] 説明できない差分 0。1件でもあれば、判定を `FAIL` のままにして原因を調べる（根拠なしに許容しない）
- [ ] 判定は摘要末尾空白の許容判断が無いので `NORMALIZATION_ACCEPTANCE_PENDING` になる（これが期待）。許容判断の代行はしない

## 6. 実運用完了とは扱わない
- 除外34件は未移行。承認・修正の後に再診断して変換するか、JDLで手入力するかを別に決める。
- 二重取込をアプリは検出できない。取込先に同じ期間の仕訳が無いことを、取込前に人が確認する。
- 税務・会計上の整合（除外分を含む会社全体）が確認できるまで、実運用完了と記録しない。

## 7. 実機往復の結果（2026-11-11）
JDL検証用複製へ取込・再Export済み。**取込はやり直さない**。手順・照合の記録は [実機検証履歴](jdl_real_evidence_log.md) の2026-11-11の行。

- 取込: 通常の期間指定では13月の9行が「指定日付範囲外」になり、「決算整理を含む」で取込。
- `yayoi_roundtrip_check --ready-only`（元データは `バディーズCSV.txt` の同一バイトの隔離コピー。監査の journal_scope は元ファイル名を含むため、仕様は緩めない）:
  - 2,480/2,480仕訳・6,102/6,102行、欠落・重複・余分0。原本↔CSVの明細・摘要・構造・合計が一致。監査1,176仕訳・2,397項目PASS。
  - `closing_entries`: 決算整理6仕訳・9行。期待・取込CSV・再Exportとも `20261331` の9行（PASS）。
  - 既知の正規化28,785セル。摘要末尾空白588行（元データの598行のうちREADYの分）は既存の4種の並びだけ。許容判断は未記録。
  - **説明できない差分1**: 貸方「売上・10%・外税」・科目9251の1円の行。取込CSVの消費税0が、再Exportで1。
- 判定: **FAIL**（摘要の許容判断待ちとは別）。

### 7.1 消費税 0→1 の調査（既存データだけ）
- 弥生の元データは「課税売上10%・内税」1円・税額0。アプリは会社Aの表現どおり「売上・10%・外税」・税額0を書いた（取込CSVは0を明示）。同じ伝票の他の行は不変。
- 2,480の取込CSV（Pilot-1・Pilot-2の期間を含む）で、売上・10%・外税の行のうち書いた税額が切捨て値（会社の端数＝切上げと違う値）の行は77行。JDLは今回の1行を除きすべてそのまま保持した（Pilot-1の10行・Pilot-2の3行も同じ）。したがって「JDLが常に売上切上げで再計算する」は否定される。
- 仕入・10%・内税で税額0の1〜3円の行は22行あり、すべて0のまま（会社の端数＝四捨五入でも0なので、保持か再計算かは判別できない）。
- 売上・外税で税額0を書いた行は、`data/private` のどのProbe・取込CSVにも他に無い。既存Evidence `TX-S10-9251-FLOOR` は切捨て値100（1円未満の端数あり）の行で、切捨て値が0の行は未観測。
- 分類（訂正、同日）: **既存の実機観測と整合する、書いた税額0の再計算**。控除不可Probe（2026-11-07、C10/C8）で、課税仕入に書いた税額0をJDLが計算し直した（`OBS-YAYOI-JDL-35-5-BUDDIES-NONCREDIT-{P10,R8}-TAX0-RECOMPUTED-001`、端数なしの金額）。今回の売上の0→1は会社の端数（切上げ）と一致し、仕入の0は四捨五入でも0なので変わらない。ただし売上・外税の0と、端数のある金額での0は登録Evidenceではない（今回の1件だけ）。アプリ側の誤りは、`relation_of` がこの0を `FLOOR` として既存Evidenceの範囲に入れたこと。会計上は弥生0円・JDL1円で仮受消費税が1円違う。許容するかは税理士の判断。
- （当初の提案。7.2のとおり安全性のためには不要になった）切り分けに必要な最小の確認（提案のみ、未実施）: 検証用複製で、売上・10%・外税・科目9251の(a) 1円・税額0、(b) 1円・税額1、(c) 税額が切捨て値0の別金額（例: 5円・0）、(d) 対照として切捨て値100の行を取込・再Export。(a)(c)だけ変われば「書いた0は再計算される」、(a)〜(c)すべて保持ならこの行固有の別要因。JDLの仕訳入力画面で該当伝票の税額欄と「税額手入力」の有無を見るだけでも、取込時の値の扱いの手がかりになる。

### 7.2 Evidence適用範囲の修正（2026-11-11、利用者承認）
- `scoped_evidence.relation_of`: 端数があり丸め方で値が分かれる金額に書いた税額0は、FLOOR／HALF_LOW／FLOOR_HIGH ではなく関係 `ZERO`（`ZERO_RELATION`）。registryに無いので、診断と出力の共通ゲート `relation_covers_account` で常に不可。BLOCK `SYSTEM_EVIDENCE:EXPLICIT_TAX_ZERO_UNVERIFIED`（準備状況画面・除外一覧の理由「税額0円がJDLで保持されるか未確認です」）。registry生成ツールも0を `ZERO` と分類する（FLOORとして登録しない）。
- 変えないもの: 税額0以外の切捨て値（`TX-S10-9251-FLOOR` 等）、どの丸めでも0になる行（関係 ""。仕入1〜5円など。今回の往復で22行が0のまま）、端数のない金額の税額0（従来どおり関係なしで不可）、MF/ACTの判定。税額の値は書き換えない。
- 会社A: 正式READY **2,479**／BLOCK **35**（新たなBLOCKは伝票1240だけ、従来の34件は不変）。隔離環境のREADYのみ変換: 2,479仕訳・6,100行、旧Windows出力から伝票1240の2行を除いたものとバイト一致、検証・監査（1,176・2,397、不変）PASS、決算整理9行。全件変換は拒否のまま。
- 旧2,480の出力は現在の診断と一致しないので `verify_ready_only_output` はFAIL（SHA紐付け・監査はPASS）。**その実機往復の判定はFAILのまま**記録として残す。新しい2,479の出力は実機に取り込んでいない（実機E2Eは未実施）。
- 追加の実機確認の要否: 伝票1240をREADYにする方法は「税額0のままJDLに保持させる」ことだが、既存の観測では0は再計算されるため、CSVで0を保てる見込みは低い。税額1円への書き換えは会計判断なのでアプリは行わない。したがって**安全性のためのProbeは不要**（BLOCKで足りる）。税理士が「JDL側の1円を受け入れる」か「JDLで手入力する」かを決める。仮に「売上・外税でも書いた0は再計算される」をEvidenceとして登録したい場合だけ、最小Probe（売上・10%・外税・科目9251: 1円・税額0、5円・税額0、対照 1,105円・税額100。期待: 0の2行は会社の端数で1になり、対照は100のまま）を提案する。

### 7.3 既存の再Exportによる、現在のREADY 2,479への部分集合照合（2026-11-11）
**新しい2,479仕訳のCSVをJDLに取り込んだ・再Exportしたものではない。** 旧2,480の再Exportから、伝票1240の2行を除いた部分集合（作業コピー、元ファイルは不変）を、現在の診断で隔離生成した2,479仕訳CSV（旧出力から1240を除いたものとバイト一致）と `yayoi_roundtrip_check` で比較した。実機E2EのPASSではなく、「既存実機結果のREADY部分集合照合」の記録である。
- 2,479/2,479仕訳・6,100/6,100行。除外した2行は伝票1240（旧2,766〜2,767行）で、他の行は位置も不変。
- 説明できない差分 **0**。既知の正規化28,775セル。摘要末尾空白 **587行**（545伝票。半角774個・全角8個。旧588行から伝票1240の1行を除いた数）は既存Evidence（Pilot-1・Pilot-2の4種の並び）で説明でき、位置合わせPASS。許容判断は未記録（`NORMALIZATION_ACCEPTANCE_PENDING`）。
- 決算整理 `20261331` 9行: 期待・取込CSV・再Exportとも9行（PASS）。監査1,176仕訳・2,397項目PASS。
- 旧2,480の実機往復の判定はFAILのまま。新2,479の実機Import・再Exportは未実施（E2E未判定）。

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

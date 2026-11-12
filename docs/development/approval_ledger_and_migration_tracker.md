# 承認台帳（D0）と未移行管理（D2）— 仕組みと限界

コード: `application/approval_ledger.py`、`application/migration_tracker.py`、CLI `tools/yayoi_approval_ledger.py` /
`tools/yayoi_migration_tracker.py`、閲覧画面 `ui_qt/migration_status_dialog.py`。顧客データは `data/private/` のみ。

## 承認が会社設定に入る経路（すべて台帳に記録される）
| 経路 | 台帳の記録 |
|---|---|
| 台帳CLI `apply`（record → preview → apply） | DECISION → APPLIED（プレビュー・バックアップ・事後診断一致を確認） |
| 伝票分割の承認画面 / `yayoi_voucher_split approve` | DIRECT_APPLIED（`approve_split_direct`） |
| `yayoi_noncredit_approval approve` | DIRECT_APPLIED（`approve_noncredit_direct`） |

- 台帳の既定の場所は `<会社設定フォルダ>/approval_ledger/<会社ID>.jsonl`。
- 台帳が改変されている場合は、新しい承認を**書く前に**拒否する。台帳に書けなかった場合は設定を元に戻す。
- 低水準の `approve_split_policy` / `approve_noncredit_identity` はテスト・ツール用に残している。これらを直接呼ぶ、
  または設定ファイルを手で編集・取り込みした承認は、`yayoi_approval_ledger audit` が「台帳に説明のない承認」として報告する。
- 承認は常に範囲付き。伝票分割は JOURNALS_V1（指定仕訳のみ）/ PERIOD_V1 / COMPANY_WIDE_V1（将来を含む）を明示して選ぶ。
  範囲のない旧形式の分割承認は無効（`SPLIT_SCOPE_MISSING`）。内容が同一の仕訳が元データに複数ある場合、
  JOURNALS_V1 の承認はどれにも効かない。控除不可の承認は元から仕訳単位。
- 実AppDataにあった旧形式の承認は0件（2026-11-12時点）で、互換性の問題はない。

## 会社ID・プロファイルIDの照合
- 承認は会社設定が参照するプロファイルに保存される。会社を確定する唯一の入口 `CompanySettingStore.resolve` が、既存の
  `company_setting_id` を JDL設定オブジェクトの `company_setting_id` に載せる（jdl-context.json・ハッシュには含めない。
  新しい識別方式ではない）。
- 分割承認は、記録時の会社IDと現在の会社IDが一致するときだけ有効（`COMPANY_DIFFERS_FROM_APPROVAL`）。会社IDを確認できない
  JDL設定（resolveを通らない）では使わない（`COMPANY_UNVERIFIED`）。控除不可の承認も同様。
- 承認の記録・プレビュー・適用・取り消し・既存の画面/CLI経路は、書き込み前に「JDL設定が同じ会社用」「会社設定が同じプロファイルを指す」
  「他の会社設定が同じプロファイルを共有していない」を確認し、違えば何も書かずに拒否する。台帳の会社が違う場合も拒否する。
  `audit` は、別会社の承認がプロファイルに残っていれば報告する。
- 互換性: 記録時に会社IDを保存していた既存の承認は、同じ会社で使う限りそのまま有効。会社IDのない承認だけが
  `APPROVAL_COMPANY_UNRECORDED` で無効になる（実AppDataに該当は0件）。

## apply / revoke の保証と限界
- 設定の書き込み前に、会社・元データSHA・JDL設定・プレビューの指紋を照合する。AppDataは `--production-store` が必須。
- 失敗時の復元は、この会社のプロファイルと company.json の2ファイルだけで、しかも「この操作が書いた状態のまま」の
  ときだけ。途中で別の変更があれば上書きせず `ConflictError` で停止する（バックアップのパスを案内する）。
- revoke は台帳の承認と同一の内容（承認者・参照・日付・対象）のときだけ、その承認だけを外す。他の変更は残る。
- 台帳へ追記するプロセスは `.lock` で排他する（残った場合は人が確認して削除）。
- **ハッシュ連鎖は改変検出のための作業ログであり、電子署名ではない。** ファイルを書ける人は整合した連鎖を作り直せる。
  末尾の行の削除はファイルだけでは検出できない（設定側の承認印と `audit` で補う）。第三者に対する証明が必要なら、
  別途、署名付きの保管（WORM・タイムスタンプ）が要る。

## MIGRATION_COMPLETE の条件（すべて必要）
1. 整合チェックPASS（元の全仕訳が出力か管理表のどちらかに1回だけある・READY-only出力とmanifestの検証PASS・改変なし）
2. READY-only出力のJDL再Export往復照合が合格（`PASS` / `PASS_WITH_ACCEPTED_NORMALIZATION`）で、その結果が
   この管理表の出力CSV・元データ・manifest・会社のSHAと一致する（古いファイルの結果は流用できない）
3. 未移行の仕訳がすべて「照合済み」（手入力の記録＋再Export SHA＋照合者・日時。照合日時は入力日時以降、
   証拠は当該仕訳のSHAに紐づく）または「対応不要」（承認者・日時・理由・根拠）
4. 試算表の一致記録に、確認者・日時・会社・対象期間・根拠資料があり、**現在の管理表の状態**（`tracker_state_sha256`）を
   名指ししている（その後に1件でも変更すれば無効）
どれかが欠ければ `MIGRATION_INCOMPLETE`（理由を列挙）。会社Aは未移行35件・実機往復未実施のため現在も INCOMPLETE。

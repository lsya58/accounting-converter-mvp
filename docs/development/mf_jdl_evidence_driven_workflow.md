# Evidence-driven 開発ワークフロー（MF→JDL）

最終更新: 2026-10-31

この文書は、Money Forward → JDL 変換を実データの full real round-trip まで進めたときの進め方を、今後の開発者と AI coding agent（Claude、Codex など）が同じ判断で続けられるようにまとめたものです。

関連する正本:

- [Current Evidence Status](current_evidence_status.md): いまの READY 数、blocker、Evidence の境界
- [JDL実機検証履歴](jdl_real_evidence_log.md): 実機で何を確認済みか。Human に実機操作を頼む前に必ず読む
- [Capability composition 設計](../design/mf_tax_capability_composition.md): Evidence をどう組み合わせて出力可否を決めるか

## 1. ゴールから逆算する

- 最終ゴールは「実データ全件を formal output → JDL Import → 同期間 re-export → strict comparison」で一致させること（full real round-trip）。個々の TODO を消すことではない。
- 毎回の作業の最初に、現在の READY 数と blocker を計算し直し、ゴールまでの critical path を引き直す。過去の件数をコピーしない。
- 依頼文の TODO 順は参考に留める。repo・保存済み設定・Evidence を見て、「いま何をすると blocker が最も減るか」で順番を決め、理由を短く残す。
- 小さな構造修正のほうが局所 patch より速く安全なら、そちらを選ぶ。ただし大規模 refactor を目的にしない。

## 2. 問題を3つに分類する

すべての blocker を次のどれかに分ける。混ぜて表示しない。

| 分類 | 意味 | 例 |
|---|---|---|
| `HUMAN` | 会計判断なので人にしか決められない | 税区分の対応、補助なし→まとめ先補助、32文字超の摘要の書き換え |
| `SYSTEM_EVIDENCE` | JDL 実機での確認が足りない | 未検証の仕訳の形、未検証の科目での税表現 |
| `SYSTEM_IMPLEMENTATION` | コードで直せる | 経路未接続、状態の引き継ぎ漏れ、診断の集計ずれ |

- Human にしか決められないことだけを Human に戻す。システムで解けることを Human に押し戻さない（例: 取引先方針の保存形式の移行はコードで解決した）。
- 逆に、会計判断をシステムが自動で「確認済み」にしない。Evidence のある候補を1画面で提示し、Human の確認を最小の操作にする。
- 「Human の残り 0」と表示されても、保存済み設定（CompanySetting / profile）を直接読んで確かめる。画面の分類から消えただけ、という誤解が実際に起きた。

## 3. Evidence は組み合わせて使う

- 仕訳全体の完全一致署名だけで判定すると、組み合わせの直積で probe が爆発する（482件で217件が止まっていた）。
- 次の capability に分けて、それぞれに実機 Evidence を結び付ける: 税（side × MF税区分 × JDL表現）、科目・補助、仕訳の形（行の並び・grouping）、摘要、optional（取引先など）。Formal READY はすべての capability が揃ったときだけ。
- ただし、実機で依存が観測された dimension は分けない。例: blank 補助は科目によって通ったり拒否されたりしたので、科目ごとに扱う。
- 「科目に依存しない」とみなす判断は Evidence で決める。現在の閾値（同じ表現が3科目以上でPASS）は保守的な経験則であり、反例が出たら該当 capability を確認済み科目だけに縮める。
- Evidence に結び付ける仕訳 identity は内容 hash（`domain/journal_identity.py`）。ファイル名・行番号・取引No を含めない。

## 4. Probe は production ではない

- 実機確認用の probe は `NOT_FOR_PRODUCTION` / `production_allowed=false` / `PENDING` で生成する。formal output は検証済み capability だけを使う。
- 「Evidence がないから probe を作れない」という循環を作らない。probe は本番と同じ mapping・税 literal・preflight・serializer を通して作り、未検証の形だけを probe 専用の引数で許可する。これで probe の PASS がそのまま本番の serializer の証明になる。
- probe は private（`data/private/`）に置き、Git で追跡しない。

## 5. Human の実機操作を最小にする

- 複数の確認ケースは、ケースごとに識別できる（摘要マーカー、日付、grouping）なら1つの batch にまとめる。目標は 1 Import + 1 re-export。
- 1ケースが FAIL しても他のケースの判定が曖昧にならないよう、比較はケース別に行う（`generate_mf_final_evidence_batch compare`）。
- 失敗時に原因を切り分けられるよう、必要なら同じ batch 内でケースを分ける（Import 回数は増えない）。
- 新しい実機操作を頼む前に [JDL実機検証履歴](jdl_real_evidence_log.md) を検索する。同じ製品・版・Tax Context・税区分・形・科目依存で `repeat_required: NO` なら再依頼しない。新しく頼む場合は、既存 scope と何が違うかを書く。

## 6. Strict comparison

- PASS 条件: missing 0、extra 0、unexpected diff 0、silent loss 0。件数・貸借・科目・補助・税・税額・flag・順番・摘要が一致すること。
- 許容するのは既知の canonical normalization だけ（伝番・部門コード・税額の blank→0、名称が同じ数値補助コードの先頭0省略など）。新しい差分を都合よく許容しない。
- raw 差分と semantic 判定を両方残す。

## 7. Human Review の見せ方

Human には実装の内部状態ではなく、次を見せる。

- 判断すべきこと（例: 「普通預金の補助なしをどの補助にまとめるか」）
- 影響（何仕訳に効くか）
- 根拠（実機 Evidence ID、実機での拒否例）
- 次の操作

同じ判断は1回で済むようにする（例: 同じ元摘要の置換は1回の確認で全仕訳へ適用）。候補は出してよいが自動保存しない。意味が欠けうる候補（先頭32文字で切った摘要など）は一括確認の対象にしない。診断では「0（判定済みで問題なし）」と「未評価（まだ判定していない、いつ判定されるか）」を必ず区別する。

## 8. 速度と安全

- 安全は「何でも止める」ことではなく、Evidence scope・fail-closed な production・strict comparison・Human の会計判断で担保する。
- 安全に独立して進められる作業は、全体の blocker を待たずに進める（例: 翌期の確認待ちでも当期 378件の formal output は作る）。
- 1つの会社・1つの実データで完走することを、汎用化より優先する。

## For AI coding agents

作業開始時に必ず行うこと:

1. [JDL実機検証履歴](jdl_real_evidence_log.md) と [Current Evidence Status](current_evidence_status.md) を読む。
2. 最新の readiness を計算し直す: `PYTHONPATH=src python3 -m accounting_converter.tools.mf_formal_readiness --source <MF CSV> --company-store <保存先のコピー> --company-id <ID>`。保存済み設定はコピーに対して扱い、本番の AppData を書き換えない。
3. `repeat_required: NO` の実機確認を再依頼しない。
4. 依頼文の順番ではなく、critical path を自分で評価し直す。
5. 可能なら「調査 → 実装 → テスト → probe 生成（必要なら）」まで同じ turn で進める。
6. 安全に独立して進められる case を、全体の blocker で止めない。
7. 最終報告では、Human の次の操作を最大1〜2個に絞る。Human にしかできないものだけを書く。

守ること:

- 会計判断（税区分対応、まとめ先補助、摘要の書き換え）を自動で確認済みにしない。
- 実顧客データ（`data/private/`）を Git に入れない。報告に科目名・摘要・金額を不要に載せない。
- `commit` / `push` は依頼されたときだけ。
- 検証: `PYTHONPATH=src python3 -m unittest discover -s tests`、`python3 -m compileall -q src tests`、`git diff --check`、`git ls-files data/private | wc -l` が 0。

主なツール:

| ツール | 用途 |
|---|---|
| `tools/mf_formal_readiness.py` | 482件などの段階別 READY 数と blocker の持ち主 |
| `tools/mf_formal_output_by_period.py` | 会計年度ごとの formal CSV 生成と検証 |
| `tools/generate_mf_final_evidence_batch.py` | 本番経路を通した probe batch 生成とケース別比較 |
| `tools/mf_full_e2e_compare.py` | full E2E の strict 比較（同日内の並び順だけの違いを切り分け） |

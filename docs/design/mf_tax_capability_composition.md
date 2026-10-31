# MF→JDL 税抜・一括比例配分 capability composition

最終更新: 2026-10-31

対象: JDL IBEX 出納帳 35.5 / 課税・税抜・原則課税・一括比例配分方式（Tax Context identity `a300dc87…`）。コードは `application/moneyforward_tax_excluded_evidence.py`。

## なぜ変えたか

これまでは仕訳全体の署名（全行の side・target科目・補助・MF税区分）が、実機Evidenceの署名と完全一致した場合だけ出力できた。実482件では、行単位の組合せが44種類しかないのに、仕訳単位の組合せが合わないため217件がBLOCKされていた。すでに実機で確認済みの税表現でも、相手科目が違うだけで新しいprobeが必要になる設計だった。

## 3つの状態を分ける

| 状態 | 意味 | 誰が解決するか |
|---|---|---|
| Human tax mapping | MF税区分をどのJDL税表現に対応させるか。会計判断なので自動確定しない | HUMAN（Evidenceのある候補だけ1クリックで確認） |
| Evidence | そのJDL税表現が実機Import・再Exportで保持されたか | SYSTEM_EVIDENCE |
| Production capability | 仕訳1件に必要な capability がすべて揃ったか | 自動判定 |

旧画面の「税Human残り0」は、Evidenceのない税区分を `SYSTEM_EVIDENCE` に分類して数えていなかっただけで、確認済みという意味ではなかった。今回、非課税仕入・非課税売上・課税売上10%はEvidenceのある候補として `HUMAN` 確認項目に戻した。

## Formal READY の条件

完全一致Evidenceがあればそれを優先する。ない場合は、次のすべてを満たすときだけ組み合わせで通す（`compose_capabilities`）。

1. **Shape**: この Tax Context で実機確認済みの形だけ。1D1C（P01〜P07 batch）と、課税仕入10%の借方1行を持つ2D2C（P01）。
2. **Tax line**: 各行の (side, MF税区分) にEvidenceがあること。
   - 同じsideで3つ以上の異なるtarget科目でPASSしている場合だけ、科目に依存しないとみなす（`ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS`）。
   - それ未満の場合は、確認済み科目だけに限定する。
3. **Account / subaccount**: Human確認済みの科目・補助が現在のJDL masterに一意に存在すること。補助を持つ科目で補助が空の行は通さない（1311・1551で実機拒否済み）。
4. **Description**: 32文字以内・CP932・改行なし。満たさない摘要はHumanが確認した置換文だけ使う。取引先は1D1C（P04）と2D2C（取引先2D2C Evidence）の摘要追記だけ。
5. **Tax amount**: 課税売上10%は、切捨てと四捨五入で結果が同じ金額だけ通す（実機確認は1100→100のみ）。

ファイル全体は、この Tax Context の MF 系 profile だけで構成されていれば、group の並びを問わず許可する。根拠は、混在した13 group・11 groupの2つの batch がどちらも strict re-export PASS したこと。

## 2026-10-31 時点の Evidence から導いた範囲

| (side, MF税区分) | Evidenceのある target 科目 | 判定 |
|---|---|---|
| 借方 課税仕入 10% | 8681, 8691, 8471, 8481, 7121 | 科目非依存 |
| 借方 / 貸方 対象外 | 借方 1311, 1111, 3231, 3241, 8441 ほか / 貸方 1311, 3141, 3161, 3181, 3221, 3271 ほか | 科目非依存 |
| 貸方 課税売上 10% | 6121 | 6121 のみ |
| 借方 非課税仕入 | 8571（相手科目は 3181/0001 と 1311/0002） | 8571 のみ |
| 貸方 非課税売上 | 9111 | 9111 のみ |
| 対象外仕入 | — | 組み合わせ対象外。完全一致のみ |

## 対象外

2D1C・2D3C・10D9C、課税売上10%の9251、端数が曖昧な課税売上10%は、Evidenceを取るまで `SYSTEM_EVIDENCE` として BLOCK を維持する。必要な probe は直積ではなく、足りない capability ごとに1件ずつにする。

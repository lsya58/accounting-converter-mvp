# MF→JDL 税抜・一括比例配分 capability composition

最終更新: 2026-10-31（final phase監査を追記）

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

2026-10-31 の 0877 で、2D1C・2D3C・10D9C・課税売上10%の9251・6121の端数ケースは実機検証済み。課税売上10%は 6121・9251 に限定（科目非依存とはみなさない）、端数が分かれる金額は 6121 のみ。これ以外の新しい組合せは、足りない capability ごとに1件ずつ probe を作る（直積にしない）。

## 「3科目以上で科目非依存」ルールの監査（2026-10-31）

- **性質**: 製品の恒久ルールではなく、保守的な経験則（heuristic）。3という値に実機上の特別な意味はない。
- **何を前提にしているか**: JDL IBEX 出納帳 35.5 のCSV Importは、行に明示した課区・税区・税入力方法・消費税額をそのまま保持し、科目masterの既定税区分で上書きしない、という観測。課区blankの行（対象外）も、BS科目だけでなくPL科目（8441、8311）でblankのまま再Exportされた。
- **Evidence上の根拠**: 借方 課税仕入10%は5科目、対象外は貸借それぞれ5科目以上で、反例は0件。逆に、補助blankの扱いは科目依存だった（3181は親科目のみで通り、1311・1551はImport拒否）。そのため補助は capability として独立させ、blank補助は科目に補助があれば常にHumanへ戻す。
- **範囲**: 1つのTax Context（Tax Context identity単位）の中だけで有効。別の会社・税設定・JDL版へは持ち越さない。
- **より良いルールへの変更条件**: 税区分ごとに「科目masterの既定税区分と異なる科目」でのPASSを1件以上含めば、件数3でなく1+1で十分と言える。現状は科目masterの既定税区分を取得していないため、件数による保守的判定を残す。
- **反例が出たら**: そのsideと税区分のcapabilityを確認済み科目だけに即時縮退する（`ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS`を上げるのではなく、該当keyを除外する）。

## 汎用複合仕訳（2026-10-31 追加）

`MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL` は、この Tax Context の複合仕訳を1つの serializer で出力する。各行は blank か、検証済み4 literal（仕　入/10%/内税、売　上/10%/外税、非仕入、非売上）のどれかでなければならない。形ごとの出力可否は `VERIFIED_COMPOUND_SHAPES` で決める。2D1C・2D3C・10D9C は 0877 で実機検証済み。新しい形は `PENDING_COMPOUND_SHAPE_EVIDENCE` に置き、実機Evidenceが出るまで BLOCK を維持する。

## Evidence identity

Evidenceに結び付ける仕訳identityは `domain/journal_identity.py` の内容hash（日付・各行の科目/補助/部門/取引先/税/金額/摘要/タグ/メモ）を使う。ファイル名・path・行番号・MF取引Noは含めない。同じ仕訳をMFから別名で再出力しても同じidentity、内容が1つでも変われば別identityになる。

# JDL Target Context source policy

## Purpose

`JdlTargetContext` is the local, validated target snapshot used by mapping and JDL output preflight. Users should eventually choose a JDL-exported source through `JDLから読み込む`; JSON remains an internal persistence format.

## Source classifications

| Source | Safe evidence | Limitation |
|---|---|---|
| JDL IBEX 出納帳35.5 科目一覧PDF（科目印刷、使用中のみ=No） | Code付き科目のcode/name、略名称、借貸、使用状態、および設定欄の有無を観測できるmaster candidate | `OBSERVED_PRINTED_MASTER`。codeなし行は科目・補助として昇格しない。正式名称と30列CSVの短縮/正式名称の対応、補助、部門、会社税設定は別Evidenceが必要 |
| Explicit JDL master export | Candidate for `FULL_MASTER` after format and runtime verification | 機械可読な正式master exportは未確認 |
| JDL IBEX journal CSV, observed 30-column form | Used account code, name, and formal name; used subaccount parent relation; used department code/name | `OBSERVED_USED_MASTER` only; unused master entries are absent |
| JDL Accounting journal-list CSV, observed 21-column form | Read-only journal verification evidence | Different structure; not an IBEX import/master source |
| Total trial balance CSV | Account-like code/name population is observable | The observed header does not establish all identity fields required by `JdlAccountIdentity` |
| Existing human-confirmed target context | Exact local snapshot for its bound company/profile | Must not be silently substituted or reused across companies |
| UI confirmation | Product/version, tax processing, department processing, and other company settings | Human confirmation remains required |

## Safety boundary

- Journal exports produce only `OBSERVED_USED_MASTER`; they never prove completeness.
- 科目一覧PDFは全5ページと使用中/未使用行を観測しても、製品内部master全件を証明しないため `FULL_MASTER` へ自動昇格しない。
- PDFのcode付き行だけをaccount candidateにする。codeなし行、集計見出し、グループ見出しへcodeを推測しない。
- Exact code/name/formal-name values are preserved. No fuzzy matching, code generation, or normalization is performed.
- Conflicting code/name identities are excluded from candidate generation and reported by count.
- PDFと30列journal CSVは役割を分離する。PDFはmaster candidate、journal CSVはruntime usage evidenceであり、CSV-only identityをmasterへ自動追加しない。code/name競合時はBLOCKする。
- Observed subaccounts and departments remain observations. They are not promoted to confirmed output master identities without the missing runtime evidence.
- Tax processing is never inferred from journal rows.
- An observed context draft is `UNCONFIRMED`, fails production validation by design, and cannot make a conversion route READY.

## Intended product flow

1. User chooses `JDLから読み込む`.
2. The application identifies a supported JDL source format. 科目一覧PDFの場合はtext layer、page連続性、header、row境界を検証する。
3. A privacy-safe summary shows observed account count、使用中/未使用count、codeなし除外count、completeness. 補助・部門は未取得として明示する。
4. Missing company settings and master evidence are confirmed separately.
5. Only a complete, conflict-free, human-confirmed snapshot is persisted as an active company setting.

Development mode may retain direct JSON loading, but ordinary users should not need to understand JSON, fingerprints, or evidence identifiers.
将来の通常GUIは `JDLから読み込む` で科目一覧PDFを選択し、内部で未確認context draftを生成する。JSON直接選択はdevelopment/debug用途に限定し、このPDFだけでproduction-ready contextにはしない。

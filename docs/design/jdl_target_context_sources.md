# JDL Target Context source policy

## Purpose

`JdlTargetContext` is the local, validated target snapshot used by mapping and JDL output preflight. Users should eventually choose a JDL-exported source through `JDLから読み込む`; JSON remains an internal persistence format.

## Source classifications

| Source | Safe evidence | Limitation |
|---|---|---|
| JDL IBEX 出納帳35.5 科目一覧PDF（科目印刷、補助表示ON、使用中のみ=No） | Code付き科目のcode/name、略名称、借貸、使用状態、および明示的な親marker直下の4桁補助code/nameを観測できるmaster candidate | `OBSERVED_PRINTED_MASTER`。通常のcodeなし行は科目・補助として昇格しない。正式名称と30列CSVの短縮/正式名称の対応、部門、会社税設定は別Evidenceが必要 |
| Explicit JDL master export | Candidate for `FULL_MASTER` after format and runtime verification | 機械可読な正式master exportは未確認 |
| JDL IBEX journal CSV, observed 30-column form | Used account code, name, and formal name; used subaccount parent relation; used department code/name | `OBSERVED_USED_MASTER` only; unused master entries are absent |
| JDL IBEX 出納帳35.5 部門情報一覧PDF（部門登録から印刷） | 対象会社の部門code/name/略名称と印刷されたoptional設定欄 | `OBSERVED_PRINTED_MASTER`。1部門・1ページのみ観測。output representation、完全性、略名称生成規則は未確認 |
| JDL Accounting journal-list CSV, observed 21-column form | Read-only journal verification evidence | Different structure; not an IBEX import/master source |
| Total trial balance CSV | Account-like code/name population is observable | The observed header does not establish all identity fields required by `JdlAccountIdentity` |
| Existing human-confirmed target context | Exact local snapshot for its bound company/profile | Must not be silently substituted or reused across companies |
| UI confirmation | Product/version, tax processing, department processing, and other company settings | Human confirmation remains required |

## Safety boundary

- Journal exports produce only `OBSERVED_USED_MASTER`; they never prove completeness.
- 科目一覧PDFは全5ページと使用中/未使用行を観測しても、製品内部master全件を証明しないため `FULL_MASTER` へ自動昇格しない。
- PDFのcode付き行だけをaccount candidateにする。codeなし行、集計見出し、グループ見出しへcodeを推測しない。
- 補助候補は、末尾delimiter付き親科目行に連続し、明示的な4桁補助code、名称、同じ借貸を持つ行だけを採用する。単なるインデント行やcodeなし予備行は補助にしない。
- 複数補助は次の親markerまで同じparent scopeに属する。parent stateはpageを越えて引き継がず、同一4桁codeが別parentに存在することは許容する。同一parent内のcode/name重複・競合はBLOCKする。
- Human入力値 `1` が画面・印刷で `0001` と表示された事実は、この35.5画面/印刷Evidenceに限定する。入力・内部保存・全環境のleading-zero規則へ一般化しない。
- Exact code/name/formal-name values are preserved. No fuzzy matching, code generation, or normalization is performed.
- Conflicting code/name identities are excluded from candidate generation and reported by count.
- PDFと30列journal CSVは役割を分離する。PDFはmaster candidate、journal CSVはruntime usage evidenceであり、CSV-only identityをmasterへ自動追加しない。code/name競合時はBLOCKする。
- Observed subaccounts and departments remain observations. They are not promoted to confirmed output master identities without the missing runtime evidence.
- 科目一覧PDFでは借方属性・貸方属性の親の双方で同じexplicit parent/child構造を観測した。補助identityは親科目を必須contextとし、同一parent内だけでduplicate/conflictを判定する。
- 30列仕訳CSVから得られる部門は使用済み値だけの `OBSERVED_USED_MASTER` であり、未使用部門を含む一覧や `FULL_MASTER` ではない。
- 部門情報一覧PDF由来のdraftは部門identityを保持するが、output codeを未確認として空にし、`production_usable=False`を維持する。
- Tax processing is never inferred from journal rows.
- An observed context draft is `UNCONFIRMED`, fails production validation by design, and cannot make a conversion route READY.

## Intended product flow

1. User chooses `JDLから読み込む`.
2. The application identifies a supported JDL source format. 科目一覧PDFの場合はtext layer、page連続性、header、row境界を検証する。
3. A privacy-safe summary shows observed account count、使用中/未使用count、明示補助count、codeなし除外count、completeness. 部門など未取得情報は明示する。
4. Missing company settings and master evidence are confirmed separately.
5. Only a complete, conflict-free, human-confirmed snapshot is persisted as an active company setting.

Development mode may retain direct JSON loading, but ordinary users should not need to understand JSON, fingerprints, or evidence identifiers.
将来の通常GUIは `JDLから読み込む` で科目一覧PDFを選択し、内部で未確認context draftを生成する。JSON直接選択はdevelopment/debug用途に限定し、このPDFだけでproduction-ready contextにはしない。
補助Mapping UIは `source parent + source subaccount` と `target parent + target subaccount` の組で候補を表示し、親科目Mappingが未確認、またはtarget parentが一致しない候補を提示しない。exact候補でも保存には`USER_CONFIRMED`を要求する。

## Account PDF company-setting draft

通常GUIの会社追加では、利用者は `JDLから読み込む` から科目一覧PDFを選択する。アプリはPDFのtext layerを検証し、ローカル保存領域へ改変検知用hashを持つ内部draftをatomic保存する。利用者にJSON、hash、Evidence分類は表示しない。

- selectorにはPDFでcode付き・使用中として観測された科目だけを表示する。
- source科目名との完全一致は初期候補にできるが、自動確認しない。
- 候補がない科目は空欄から利用者が選択する。類似名候補、fuzzy matching、hidden fallbackは行わない。
- 全科目の選択と明示checkboxが揃った場合だけ、account mappingを`USER_CONFIRMED`として保存する。
- 保存されるtarget metadataはprinted code/name/abbreviationであり、未確認の30列CSV正式名称を推測しない。
- PDF draftを束ねた会社設定は `確認が必要` で保存できるが、正式JDL設定への確認・昇格が済むまで変換には利用できない。
- PDFまたは対応設定が保存後に変わった場合はstaleとしてBLOCKする。

この導線は会社固有の確認作業を再利用可能にするためのものであり、PDFを`FULL_MASTER`、正式`JdlTargetContext`、production READYへ昇格するものではない。subaccount PDFとdepartment PDFは将来同じ観測service boundaryへ追加できるが、今回の通常GUI対象はaccount PDFのみとする。

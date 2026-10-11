# JDL Target Context source policy

## Purpose

`JdlTargetContext` is the local, validated target snapshot used by mapping and JDL output preflight. Users should eventually choose a JDL-exported source through `JDLから読み込む`; JSON remains an internal persistence format.

## Source classifications

| Source | Safe evidence | Limitation |
|---|---|---|
| Explicit JDL master export | Candidate for `FULL_MASTER` after format and runtime verification | No supported export has been confirmed yet |
| JDL IBEX journal CSV, observed 30-column form | Used account code, name, and formal name; used subaccount parent relation; used department code/name | `OBSERVED_USED_MASTER` only; unused master entries are absent |
| JDL Accounting journal-list CSV, observed 21-column form | Read-only journal verification evidence | Different structure; not an IBEX import/master source |
| Total trial balance CSV | Account-like code/name population is observable | The observed header does not establish all identity fields required by `JdlAccountIdentity` |
| Existing human-confirmed target context | Exact local snapshot for its bound company/profile | Must not be silently substituted or reused across companies |
| UI confirmation | Product/version, tax processing, department processing, and other company settings | Human confirmation remains required |

## Safety boundary

- Journal exports produce only `OBSERVED_USED_MASTER`; they never prove completeness.
- Exact code/name/formal-name values are preserved. No fuzzy matching, code generation, or normalization is performed.
- Conflicting code/name identities are excluded from candidate generation and reported by count.
- Observed subaccounts and departments remain observations. They are not promoted to confirmed output master identities without the missing runtime evidence.
- Tax processing is never inferred from journal rows.
- An observed context draft is `UNCONFIRMED`, fails production validation by design, and cannot make a conversion route READY.

## Intended product flow

1. User chooses `JDLから読み込む`.
2. The application identifies a supported JDL source format.
3. A privacy-safe summary shows observed account/subaccount/department counts and completeness.
4. Missing company settings and master evidence are confirmed separately.
5. Only a complete, conflict-free, human-confirmed snapshot is persisted as an active company setting.

Development mode may retain direct JSON loading, but ordinary users should not need to understand JSON, fingerprints, or evidence identifiers.

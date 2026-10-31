# MF source blank subaccount: target import rejection

Human-reported JDL IBEX 出納帳 35.5 Import results. These are **negative**
Evidence, not successful round-trips or permission to convert. The candidate
CSVs and current master PDF remain under `data/private` and are not copied here.

| Evidence ID | Target parent | Observed subaccounts in current master | Candidate SHA-256 | JDL result |
|---|---|---:|---|---|
| EVID-JDL-35-5-BLANK-SUB-REJECT-1551-001 | 1551 売掛金 | 9 | `58adec26049bae4fd5cdd9666faa486db9eadd64273dd1210f7b008acea154d5` | Import FAIL |
| EVID-JDL-35-5-BLANK-SUB-REJECT-1311-001 | 1311 普通預金 | 3 | `364f40412bea1a973dcfd5cdd9666faa486db9eadd64273dd7af2e20593c700deb87a3e1de` | Import FAIL |

Target master PDF SHA-256: `43cb052eb1a37cf2684a39d2646c099e3434e97a5b2a08a0df60a1cd63d04fad`.
Both candidates were one balanced 1D1C journal, credit-side target parent with
blank subaccount code and name, debit-side 8471 purchase 10% internal tax,
amount 1,100, no optional fields. Dates: 2026-05-15 and 2026-05-16.

Human reported the exact JDL rejection for **each** candidate:
`[貸方補助名称]：科目に補助が設定されています`.
No re-export was possible. Scope is the named target account with subaccounts
configured in the observed master, the stated product/version, and this
1D1C credit-side blank-subaccount probe. Neither result is generalized to
other accounts, debit side, other JDL versions, or a master with no subaccounts.
The existing fail-closed production rule remains unchanged. To resolve an MF
source without a subaccount, a Human must select a target subaccount, or create
one in JDL and refresh the master before selecting it. No automatic choice.

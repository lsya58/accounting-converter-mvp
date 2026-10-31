# EVID-MF-JDL-35-5-SALES10-1111-6121-ROUNDTRIP-001

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` for this exact case only.

- Target: JDL IBEX 出納帳 35.5, Human-confirmed 課税 / 税抜 / 原則課税 / 一括比例配分方式.
- Tax Context identity SHA-256: `a300dc8750b7fe6417f2d3c092a6cae2055ccf0256cd539a7036e4b67b0de3e0`.
- Source tax identity under investigation: MF `課税売上 10%`.
- Exact tested JDL signature: 1D1C, flag `1111`, debit 1111 現金 / no subaccount / tax blank; credit 6121 売上高 / no subaccount / `売　上` (full-width space) / `10%` / `外税` / explicit tax 100. Integer amount 1100 on both sides, no trade partner or other optional fields, description `EVID-TAX-SALES10-IMPORT`.
- Candidate: 2026-05-24, 1 journal / 1 physical row, official 30 columns, CP932, no BOM, CRLF. Human real JDL Import PASS; same-day re-export PASS.
- Existing strict comparator: `KNOWN_JDL_CANONICAL_NORMALIZATION`; missing journals/rows 0, extra journals/rows 0, unexpected differences 0, silent loss 0. Four raw differences: voucher blank to 0; debit tax amount blank to 0; debit and credit department code blank to 0. Account/subaccount, amount/balance, both-side tax semantics, flag/order, and description were retained.
- Provenance: current-company JDL self-export `0871` established the target literal, not Import compatibility. Candidate SHA-256 `802d0910eb3ce7d828f313b2c76b74b557f89b8a6016826763014590f27af6b9`; real re-export `0872` SHA-256 `b126ed2039c20424ff9fd82c04c3a06d2aee3ecf51bd8a59e8da3eecabbbb521`. Raw files remain under `data/private/mf_tax_sales10_pending_rev2/` and are not tracked.

The earlier `売一種` Import candidate failed with `[貸方課区]に一致する課区が見つかりません` in this target Context; it is not a fallback. This record does not revoke observations in other companies/contexts.

The real 482-journal MF dataset has 65 occurrences of `課税売上 10%`, but **zero** have this exact 1111/no-sub -> 6121/no-sub/no-trade-partner signature. This Evidence therefore does not release any of the 65 production journals. Source-to-target tax mapping confirmation, other exact signatures, and formal output remain independently gated.

Privacy-safe signature inventory of the 65 still-uncovered 1D1C journals (target debit account/subaccount -> target credit account/subaccount; TP means source trade partner present):

| Signature | TP | Journals |
| --- | --- | ---: |
| 1551/0003 -> 6121/blank | no | 24 |
| 1311/0002 -> 6121/blank | yes | 10 |
| 1551/0001 -> 6121/blank | no | 10 |
| 1551/0004 -> 6121/blank | no | 10 |
| 3161/blank -> 6121/blank | yes | 8 |
| 3181/0001 -> 9251/blank | no | 1 |
| 1311/0002 -> 9251/blank | no | 1 |
| 1551/0009 -> 6121/blank | no | 1 |

These buckets are signature inventory, not a claim that one new Import probe can validate every bucket or that source transaction details may be tracked.

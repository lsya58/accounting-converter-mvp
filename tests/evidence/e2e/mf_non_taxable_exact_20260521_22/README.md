# MF to JDL non-taxable exact cases

Status: VERIFIED_BY_REAL_IMPORT_AND_REEXPORT (two independent cases).
Target: JDL IBEX 出納帳 35.5; 課税 / 税抜 / 原則課税 / 一括比例配分方式.
Source: private synthetic JDL probe, not a production conversion. Human confirmed real import and same-period re-export for 2026-05-21 through 2026-05-22.

| Case | Evidence ID | Exact tested scope |
| --- | --- | --- |
| 非課税仕入 | EVID-MF-JDL-35-5-NONPUR-8571-3181-SUB0001-001 | 1D1C, 1111, debit 8571/no sub/非仕入, credit 3181/0001/tax blank |
| 非課税売上 | EVID-MF-JDL-35-5-NONSALE-1311-SUB0002-9111-001 | 1D1C, 1111, debit 1311/0002/tax blank, credit 9111/no sub/非売上 |

Both cases use blank tax rate and input method, integer 1100 on each side, no optional fields, 30 columns, CP932, no BOM, CRLF. The comparator reports 1 journal/1 row per case, zero missing/extra rows and zero unexpected changes. There is no silent loss. Across both rows, 12 raw changes are existing JDL canonical normalizations: voucher blank to 0 (2), tax amount blank to 0 (4), numeric subaccount zero suppression with unchanged name (2), and department code blank to 0 (4). Flags, account identities, tax semantics, amounts, descriptions, and order are unchanged.

Private files remain under `data/private/mf_tax_nonpur_nonsale_pending_rev2/`. They are not Git fixtures. Candidate SHA-256: `eb74d44618f55a5c88f3ee7d46f01cdc4159c38c3ba843af3b23d62b765c6415`; re-export SHA-256: `eca8250f7dbeb9577944664117c4e365582b54f2c73a25719bde56324b128055`.

This proves only the two target signatures above. It does not activate the other MF tax mappings or prove all occurrences of either source tax identity. Production remains fail-closed until exact signature matching, Human tax mapping confirmation, and formal preflight/output support are wired and verified. 課税売上10% and 対象外仕入 are outside this evidence.

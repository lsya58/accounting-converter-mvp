# JDL-to-JDL Real Batch Import Evidence

- Evidence ID: `EVID-JDL-TO-JDL-REAL-BATCH-1158-IMPORT-001`
- System evidence status: `VERIFIED_BY_REAL_IMPORT`
- Accounting review status: `HUMAN_ACCOUNTING_REVIEW_PENDING`
- Observation date: 2026-10-24
- Target: JDL IBEX Cashbook 35.5

## Confirmed System Result

A real JDL-origin 30-column batch passed the saved CompanySetting gate, formal
preflight, formal GUI output, privacy-safe repository audit, strict reparse,
and Human-observed import into the intended JDL company.

- Logical journals: 1,158
- Physical rows: 1,271
- Date range: 2025-12-01 through 2026-07-08
- Unexpected source/output differences: 0
- Silent loss: 0
- Human-observed JDL import: PASS
- Human screen inspection immediately after import: no system-format problem reported

The raw customer source and generated output are not tracked. Their hashes and
privacy-safe aggregate results are recorded in `manifest.json`.

## Evidence Boundary

This Evidence verifies the converter's format handling and the exact saved
CompanySetting path used by the Human operator: strict JDL input recognition,
account and parent-scoped subaccount mappings, confirmed tax mappings and
Evidence gates, two confirmed description replacements, the scoped
`1000 -> 1111` canonical normalization, formal 30-column serialization,
atomic no-overwrite output, and successful real JDL import.

It does not certify that the Human-selected account or tax treatment is
accountingly correct. That decision remains
`HUMAN_ACCOUNTING_REVIEW_PENDING` until the accounting professional completes
the planned review. It also does not establish a strict re-export round trip;
no customer re-export is tracked or claimed by this Evidence.

## Freeze Policy

The JDL-to-JDL route is now a regression-protected stable path. Further work is
limited to defects observed in use, focused UX improvements, operator/support
documentation, and regression maintenance. This Evidence does not authorize
new vendors, new tax semantics, fuzzy mappings, partial output, or broader
Evidence inference.

# MF-to-JDL Real READY Batch Round-trip Evidence

- Evidence ID: `EVID-MF-JDL-REAL-READY-BATCH-13J-ROUNDTRIP-001`
- Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`
- Target: JDL IBEX Cashbook 35.5
- Context: taxable / tax excluded / standard taxation / proportional allocation
- Period: 2026-01-07 through 2026-01-10

## Verified Result

A real MF READY-only batch passed the saved CompanySetting gate, formal
conversion, real JDL import, same-period JDL re-export, and strict semantic
comparison.

- Logical journals: 13 / 13
- Physical rows: 14 / 14
- Missing or extra journals and rows: 0
- Account, subaccount, tax, description, trade-partner, grouping, and balance
  semantic mismatches: 0
- Raw differences: 75, all classified as existing scoped JDL canonical
  normalizations
- Unexpected differences: 0
- Silent loss: 0

Two journals used one Human-confirmed description replacement. The formal
output value was retained exactly by the JDL round trip. No private source or
replacement text is stored in this Evidence directory.

## Evidence Boundary

This Evidence verifies only this 13-journal READY-only batch under the exact
saved CompanySetting, current target master, tax Context, mappings, Evidence
variants, and Human-confirmed policies used for the run. It covers the P01
through P07 patterns present in that batch, including the exact P05/P07 target
subaccount variants and the two P06 replacement occurrences.

It does not establish support for all 482 source journals, unknown shapes,
unconfirmed mappings, different tax Contexts, or different description text.
Those inputs remain subject to the normal fail-closed review and preflight.

Raw customer CSV files remain under `data/private` and are not tracked.

# MF to JDL tax-excluded subaccount round-trip Evidence

- Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`
- JDL: IBEX Cashbook 35.5
- Context: taxable / tax excluded / standard taxation / proportional allocation
- Human Import: PASS
- Strict semantic comparison: PASS
- Journals: 2
- Physical rows: 2
- Unexpected changes: 0

This Evidence verifies only the P05 and P07 variants whose credit target is
account `3181` and subaccount `0001`. The pre-existing `3181` with blank
subaccount variants remain separate Evidence and are not replaced.

JDL re-exported numeric subaccount code `0001` as `1`. The raw difference is
retained and accepted only for the exact parent code, zero-padded subaccount
code, and subaccount name recorded by this Evidence. It is not a general
leading-zero equivalence rule.

The raw candidate and JDL re-export remain under `data/private`; no customer
data is copied into this Evidence directory.

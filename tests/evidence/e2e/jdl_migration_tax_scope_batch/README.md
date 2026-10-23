# JDL Migration Tax Scope Batch Evidence

- Human JDL import: PASS
- Candidate journals: 6
- Candidate physical rows: 12
- Strict semantic comparison: 6 PASS / 0 FAIL
- Raw candidate and re-export: private, not tracked

## Promoted Evidence

- `EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-COMPOUND-7ROW-DEPARTMENT-ROUNDTRIP-001`
- `EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-DEPARTMENT-ACCOUNT-A-ROUNDTRIP-001`
- `EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-DEPARTMENT-ACCOUNT-B-ROUNDTRIP-001`
- `EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-SUBACCOUNT-DEPARTMENT-ROUNDTRIP-001`
- `EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1111-SUBACCOUNT-DEPARTMENT-ROUNDTRIP-001`
- `EVID-JDL-MIGRATION-NON-TAXABLE-1000-TO-1111-CANONICALIZATION-001`

Each Evidence item is limited to its hashed occurrence signature: route, tax
identity, side, exact flag sequence, tax-side account identity, subaccount
presence structure, department presence, opposite-side tax semantics, and the
confirmed JDL 35.5 tax context.

## Canonical Normalization

The exact non-taxable-sales occurrence re-exported from source flag `1000` as
canonical flag `1111`. The raw mismatch remains recorded, while semantic
comparison classifies it as `KNOWN_JDL_CANONICAL_NORMALIZATION` only when the
route, tax identity and side, account, subaccount structure, department
condition, opposite tax, source shape, and confirmed tax context all match the
recorded occurrence signature. Other flag changes remain strict failures.

Department display names were omitted by re-export while their exact nonblank
department codes were retained and Human confirmed the departments in JDL.
Account display names were normalized to target-master formal names while the
exact account codes were retained. These are the only semantic normalizations
accepted by the batch comparator.

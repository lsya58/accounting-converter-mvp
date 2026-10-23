# JDL Migration Non-Taxable Sales Evidence

- Evidence ID: `EVID-JDL-MIGRATION-TAX-NON-TAXABLE-SALES-ROUNDTRIP-001`
- Result: `VERIFIED_BY_REAL_IMPORT`
- Human JDL import: PASS
- Strict semantic comparison: PASS
- Mismatched fields: 0

## Supported scope

Exact JDL-to-JDL synthetic `1111` 1D1C probe for JDL IBEX Cashbook 35.5,
taxable and tax-inclusive simplified taxation with first business category,
target accounts `111` / `現金` and `612` / `売上高`, blank subaccounts,
credit-side `非売上` with a blank tax-rate field, opposite-side tax blank,
balanced integer yen, exact description, 30 columns, CP932, and BOM-free CRLF.

Activation requires the same relevant account identities, no target subaccount
requirement on either account, the verified tax context, the exact route and
shape, and explicit Human confirmation of the tax mapping.

## Unsupported scope

Other accounts, shapes, tax categories, tax contexts, subaccounts, optional
fields, changes to either relevant account, relevant subaccount requirements,
and stale contexts remain unsupported. This Evidence does not authorize
automatic confirmation or broaden any production route.

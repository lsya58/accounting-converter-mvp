# JDL 2D2C Taxable Round-trip Evidence

- Evidence ID: `EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-ROUNDTRIP-001`
- Result: `VERIFIED_BY_REAL_IMPORT`
- Human JDL import: PASS
- Strict semantic comparison: PASS
- Product: JDL IBEX Cashbook 35.5

## Supported scope

- exactly one two-row `2D2C` compound voucher
- flag sequence `1110 -> 1101`
- exact synthetic account, parent-scoped subaccount, amount, and row order
- first-row debit purchase 10% tax-inclusive representation
- opposite-side and second-row tax fields blank
- exact per-row descriptions
- CP932, no BOM, CRLF, official 30-column rows

## Unsupported scope

This Evidence does not cover other compound shapes, another tax placement or
category, multiple taxable rows, trade partners, invoice, tags, memos,
departments, different account/subaccount identities, or arbitrary batches.
Production Registry and general readiness are unchanged.

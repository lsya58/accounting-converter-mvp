# JDL 2D2C Taxable Without Subaccount Evidence

- Evidence ID: `EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-NO-SUBACCOUNT-ROUNDTRIP-001`
- Result: `VERIFIED_BY_REAL_IMPORT`
- Human JDL import: PASS
- Strict semantic comparison: PASS, zero mismatched semantic fields
- Product: JDL IBEX Cashbook 35.5

## Supported scope

- Money Forward observed 19-column CSV
- exactly one two-row `2D2C` compound voucher
- taxable and tax-included JDL context
- one debit-side purchase 10% taxable line
- no subaccount configured or emitted for the taxable target account
- no trade partner or other optional field
- exact physical-row order, amounts, tax placement, and per-row descriptions
- 30-column CP932 JDL output without BOM and with CRLF line endings
- exact confirmed JDL context

## Unsupported scope

Configured-but-blank subaccounts, trade partners, other compound shapes,
another tax placement, multiple taxable rows, optional-field combinations,
stale contexts, and unconfirmed mappings remain blocked. This Evidence does
not broaden the production Registry or general Money Forward readiness.

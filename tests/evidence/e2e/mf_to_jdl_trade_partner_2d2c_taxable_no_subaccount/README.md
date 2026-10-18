# MF to JDL 2D2C Taxable Trade Partner Without Subaccount Evidence

- Evidence ID: `EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-NO-SUBACCOUNT-DESCRIPTION-ROUNDTRIP-001`
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
- exactly one trade-partner value on one side and one distinct partner value
- explicitly confirmed `APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED` policy
- complete transformed description at most 32 characters and CP932 lossless
- exact row order, account/tax route, amounts, and per-row descriptions
- no invoice, tag, memo, department, or other optional blocker
- exact confirmed JDL context

## Unsupported scope

Configured-but-blank subaccounts, both-side or multiple partners, other
compound shapes, another tax placement, multiple taxable rows, descriptions
over 32 characters, CP932-incompatible text, optional-field combinations,
stale contexts, and unconfirmed policies remain blocked. This Evidence does
not broaden the production Registry or general Money Forward readiness.

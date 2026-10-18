# MF to JDL 2D2C Taxable Trade Partner Evidence

- Evidence ID: `EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-DESCRIPTION-ROUNDTRIP-001`
- Result: `VERIFIED_BY_REAL_IMPORT`
- Human JDL import: PASS
- Strict semantic comparison: PASS, zero mismatched semantic fields
- Product: JDL IBEX Cashbook 35.5

## Supported scope

- Money Forward observed 19-column CSV
- exactly one two-row `2D2C` compound voucher
- one debit-side purchase 10% taxable line with the exact confirmed parent-scoped subaccount
- exactly one trade-partner value on one side
- one distinct partner value
- explicitly confirmed `APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED` policy
- complete transformed description at most 32 characters and CP932 lossless
- exact row order, account/subaccount/tax route, amounts, and descriptions
- no invoice, tag, memo, department, or other optional blocker
- exact confirmed JDL context

## Unsupported scope

Both-side or multiple partners, other compound shapes, another tax placement,
multiple taxable rows, another account/subaccount context, descriptions over
32 characters, CP932-incompatible text, optional-field combinations, stale
contexts, and unconfirmed policies remain blocked. This Evidence does not
broaden the production Registry or general Money Forward readiness.

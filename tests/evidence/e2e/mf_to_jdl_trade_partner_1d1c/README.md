# Money Forward to JDL Trade Partner 1D1C Evidence

- Evidence ID: `EVID-MF-JDL-TRADE-PARTNER-1D1C-DESCRIPTION-ROUNDTRIP-001`
- Date: 2026-10-18
- Result: `VERIFIED_BY_REAL_IMPORT`
- Target: JDL IBEX Cashbook 35.5
- Human verified import: PASS
- Strict semantic comparison: PASS, zero mismatched semantic fields

## Supported scope

- Money Forward observed 19-column journal CSV
- one `1D1C` journal
- exactly one trade-partner value on one side
- explicitly confirmed company policy that appends the partner to description
- resulting description at most 32 characters and strictly CP932 encodable
- account, parent-scoped subaccount, and tax route already supported
- no other optional-field blocker
- exact confirmed JDL context

The synthetic probe uses the already verified formal E2E No. 4 account,
subaccount, tax, and amount structure. The only experimental behavior is the
deterministic trade-partner description transformation.

## Unsupported scope

This evidence does not cover compound journals including `2D2C`, partners on
both sides, multiple distinct partners, descriptions longer than 32
characters, text that cannot be encoded as CP932, invoice/tag/memo
combinations, or stale JDL context. It does not authorize silent dropping or
truncation.

## Files

- `source_moneyforward.csv`: synthetic Money Forward-compatible source.
- `generated_jdl.csv`: application-generated candidate.
- `jdl_reexport.csv`: JDL re-export after successful Human import.
- `SHA256SUMS`: hashes for all three CSV artifacts.

The re-export adds only previously observed JDL-managed representations such
as voucher number, master codes, zero tax amounts, and zero department codes.
Date, account/subaccount semantics, amount, blank tax semantics, description,
balance, encoding, and the official 30-column data row all match strictly.

Production Registry and general Money Forward READY scope are not broadened.
The policy remains company-scoped, context-bound, and `USER_CONFIRMED`.

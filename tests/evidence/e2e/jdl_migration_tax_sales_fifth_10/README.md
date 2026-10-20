# JDL Migration Sales Fifth Category 10% Evidence

- Evidence ID: `EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-ROUNDTRIP-001`
- Result: `VERIFIED_BY_REAL_IMPORT`
- Human JDL import: PASS
- Strict semantic comparison: PASS
- Target master SHA-256: `5c53f4a613b0046913b42a4af41fd89023477ff84d5cdc27abf799d2ef3ca822`

## Supported scope

Exact JDL-to-JDL synthetic `1111` 1D1C probe, target account identities
`111` and `612`, blank subaccounts, credit-side `売五種 / 10%`, opposite-side
tax blank, balanced integer yen, exact description, CP932, BOM-free CRLF, and
the exact observed target master.

## Unsupported scope

Other accounts, shapes, tax categories, tax processing contexts, subaccounts,
optional fields, and stale masters remain unsupported. This Evidence does not
activate migration readiness until the exact target tax context and Human tax
mapping are confirmed.

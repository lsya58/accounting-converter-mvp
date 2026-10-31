# EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` for the exact probe signature
below. This is not a general 1D2C or production READY approval.

- Source: real MF journal, SHA-256 of journal ID
  `6099ad2a91a878298c8fac68226f9cc5b6fd263cd5eb95ffd20daeacbe29e949`.
- Target: JDL IBEX 出納帳 35.5; Human-confirmed 課税 / 税抜 / 原則課税 /
  一括比例配分方式. Context identity SHA-256:
  `a300dc8750b7fe6417f2d3c092a6cae2055ccf0256cd539a7036e4b67b0de3e0`.
- Exact source-side tax/account dependency, in physical-row order:
  debit 7121 / no subaccount / 課税仕入 10%; credit 3141 / no subaccount /
  対象外; credit 3271 / subaccount 0002 / 対象外.
- Output: one grouped 1D2C journal, two physical 30-column rows, flags
  `1110` then `1101`, debit purchase 10% internal-tax fields on row 1,
  opposite tax fields blank, per-row descriptions, CP932, no BOM, CRLF.
- Human real Import: PASS. Same-day re-export: PASS.
- Strict comparison: `KNOWN_JDL_CANONICAL_NORMALIZATION`, 1/1 logical
  journals, 2/2 physical rows, missing/extra 0, unexpected changes 0.
  Account, subaccount, date, amount, explicit tax amount, tax identity,
  row order, flags, grouping, description, and balance were retained.
- Raw differences: ten fields: voucher blank to 0 (2), blank tax amount to
  0 (3), department code blank to 0 (4), exact subaccount code 0002 to 2
  with the same parent/name (1). All ten match existing comparator rules.
- Private candidate SHA-256:
  `73c89dce18dc9bd66d7af9e06bd8c528f8ee0431dfc9d90b9bc0c42ca487e4d5`.
- Private re-export SHA-256:
  `50a0dee743e7a461d2e00caefa8136876b4b76c886948605640b85bfdd6ee718`.

No raw customer CSV is tracked. The previous rev2 candidate had an
unexpected unused-side blank-to-zero amount difference and remains a failed
strict comparison; rev3 was actually re-imported before this promotion.

Exclusions: different account/subaccount signature, tax identity or context,
trade partner or other optional features, another grouping/shape, 10D9C,
and the four unverified MF tax identities. The output preflight/serializer
must be implemented and tested separately before this Evidence can make a
journal formally READY.

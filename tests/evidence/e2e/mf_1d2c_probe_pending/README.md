# MF to JDL 1D2C probe: strict comparison pending

This rev2 result is **not** verified production Evidence. The real JDL Import of the
private rev2 candidate succeeded, and a same-day re-export was obtained, but
the existing strict comparator returned `UNEXPECTED_CHANGE`. Do not activate
the 1D2C route on the basis of rev2.

Rev3 was subsequently imported and strictly verified. See
`../mf_1d2c_tax_excluded_proportional/README.md` for the independent PASS
record and exact scope.

- Source journal SHA-256: `6099ad2a91a878298c8fac68226f9cc5b6fd263cd5eb95ffd20daeacbe29e949`
- Probe date: `2026-05-18`
- Private candidate SHA-256: `452737136ce34c4a53f47a6d76d33926dbc8415306b1709555de99c6ffaf12a0`
- Private re-export SHA-256: `50a0dee743e7a461d2e00caefa8136876b4b76c886948605640b85bfdd6ee718`
- Counts: 1 logical journal and 2 physical rows on each side; missing/extra 0.
- Flag sequence: `1110`, `1101` on each side; row order, date, account,
  subaccount, tax identity/rate/input method/amount, description, and totals
  match under the comparator's existing rules.
- Raw differences: 11 fields. Ten are existing known normalizations (voucher
  2, opposite/blank tax amount 3, department code 4, exact subaccount numeric
  code zero suppression 1). The remaining difference is unused-side row-2
  debit amount: candidate blank, re-export `0`.
- Strict result: `UNEXPECTED_CHANGE` (one field); no Evidence ID issued.

The generator now emits explicit `0` for an absent debit or credit amount.
The private rev3 candidate differs from rev2 in that field only. Comparing
rev3 with the old re-export is a diagnostic check, **not** a round-trip of
the rev3 bytes. A new real Import and same-period re-export of rev3, followed
by the unchanged strict comparator, are required before promotion. This case
does not establish the unrelated tax-four identities or 10D9C shape.

Private candidate and re-export CSVs remain under `data/private/` and are not
tracked here.

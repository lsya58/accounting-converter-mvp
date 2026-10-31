# MF tax discovery probe: case-level Import observation

This record is not production Evidence. The private three-case candidate
contained dates 2026-05-20 through 2026-05-22. The operator later selected
only 2026-05-21 through 2026-05-22 as the JDL Import period, so the first row
was outside the selected range. There is no same-period re-export for this
attempt. Whether JDL imported either in-range row is **unknown**; the absence
of an individual error message does not establish Import PASS.

| Case | Observation | State |
|---|---|---|
| `CASE-TAX-SALES10` | Prior full-period attempt rejected credit tax scope `売一種`: `[貸方課区]に一致する課区が見つかりません`. The selected-period attempt also reports date out of range for this row. | `IMPORT_FAIL` for the `売一種` candidate; no verified tax mapping |
| `CASE-TAX-NONPUR` | No individual error message in the selected-period attempt. | `IMPORT_ACCEPTED_OR_PENDING_REEXPORT`; not verified |
| `CASE-TAX-NONSALE` | No individual error message in the selected-period attempt. | `IMPORT_ACCEPTED_OR_PENDING_REEXPORT`; not verified |

The current target company's printed master indicates a sales tax category
and tax input method for account 6121, but printed formatting is not proof of
the exact CSV Import literal. Existing successful `売一種` re-exports belong to
other company/context Evidence and cannot override the current rejection.
The old `売一種` candidate is invalid for this exact target company and
tax-excluded/standard/proportional context; the legacy three-case generator
now rejects reuse. This does not invalidate observations for other companies
or tax contexts. A 2026-05-23 real JDL self-export from the current company
shows `売　上` (one full-width space), `10%`, `外税`, and explicit tax amount
100 on credit account 6121. The self-export is literal provenance only.
The separate 2026-05-24 rev2 Import probe later passed real Import/re-export;
see `tests/evidence/e2e/mf_tax_sales10_excluded_proportional_cash/` for its
independent exact Evidence. The failed `売一種` candidate remains invalid here.

Rev2 candidate provenance: current-company JDL self-export `0871`, SHA-256
`5a5ad15c6ea4f9a996d7c4f11221fc1fc4a2eb5032a7f495bca19ff13c76bd62`.
Its single 2026-05-23 row had blank description, so selection used the
single-row/date/account/tax checks rather than the planned marker. The
generated rev2 probe SHA-256 is
`802d0910eb3ce7d828f313b2c76b74b557f89b8a6016826763014590f27af6b9`.
It has one 1111 row dated 2026-05-24; debit 1111/no sub/tax blank, credit
6121/no sub with exact `売　上` / `10%` / `外税` / tax amount 100, balanced
at 1100, and description `EVID-TAX-SALES10-IMPORT`. The later Import PASS is
recorded separately; this original self-export itself was never Import Evidence.

The private two-case candidate was imported and both cases passed independent
strict comparison; see `tests/evidence/e2e/mf_non_taxable_exact_20260521_22/`.

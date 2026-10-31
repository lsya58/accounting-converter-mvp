# MF 対象外仕入 compound 11-journal real JDL round-trip

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` **only for the exact tested conditions**. Human imported the private 2026-05-27 candidate into the current JDL IBEX 出納帳 35.5 company and re-exported the same day as `JDL出納帳-0514-0875-仕訳.csv`.

Context: Human-confirmed 課税 / 税抜 / 原則課税 / 一括比例配分方式. Source: 11 selected journals from the private real MF 482-journal Export. The private candidate was an explicit NOT_FOR_PRODUCTION probe, not formal converter output. Source tax identity `対象外仕入` appears once on the debit side of each journal. The other populated source tax lines use `対象外`. Both target tax fields are blank and populated-side tax amount is zero. The current source tax mapping remains `UNRESOLVED`; this record must not silently confirm it.

| Independent dimension | Evidence ID | Verified cases | Exact scope |
| --- | --- | ---: | --- |
| Compound tax interaction | `EVID-MF-JDL-35-5-OUTPUR-COMPOUND-TAX-001` | 11/11 | Debit `対象外仕入`, other source `対象外`; target blank category/rate/input method, populated-side tax amount 0, current Context and the three exact shape/account/subaccount patterns below. |
| 4D6C grouping | `EVID-MF-JDL-35-5-OUTPUR-4D6C-ROUNDTRIP-001` | 5/5 | 10 physical rows, flags 1110/1100.../1101, exact observed account/subaccount and source tax ordering. |
| 5D7C grouping | `EVID-MF-JDL-35-5-OUTPUR-5D7C-ROUNDTRIP-001` | 1/1 | 12 physical rows, same flag convention, exact observed dependencies. |
| 5D8C grouping | `EVID-MF-JDL-35-5-OUTPUR-5D8C-ROUNDTRIP-001` | 5/5 | 13 physical rows, same flag convention, exact observed dependencies. |
| Per-row description | `EVID-MF-JDL-35-5-OUTPUR-ROW-DESC-ROUNDTRIP-001` | 11/11 | All 127 original row descriptions remained at their original physical-row position, unchanged and in order. No generalization to other characters or transformations. |

Existing strict comparator `compare_probe` and `compare_probe_patterns` returned 11/11 case PASS: 11 logical journals and 127 physical rows on each side; missing/extra journals and rows 0; unexpected differences 0; silent loss 0. Journal grouping, flags, date, account/subaccount identity, amount, balance, tax category/rate/input method, per-row description, and optional fields match. Candidate and re-export debit/credit totals match exactly; raw amount values remain private.

Raw differences: 535, all covered by **existing** comparator rules: voucher blank→0 (127), debit department blank→0 (127), credit department blank→0 (127), debit tax amount blank→0 on an absent side (77), credit tax amount blank→0 on an absent side (50), exact named subaccount code `0003`→`3` (27). No new normalization was added. The original target probe had explicit tax amount `0` on every populated side.

- Private candidate SHA-256: `791b8f707e6c4ca3297eab306ea3d465c249eebd6d2dd9224e92e2bd1664d086`.
- Private re-export SHA-256: `7e25d1ab0b8e6c4b827fb0f9f91201b4dc4a95f3b44a069ea8b1386be54d92fb`.
- Source journal hashes and row-specific description hashes are retained only in the private manifest. The customer CSVs remain under `data/private/` and are never Git fixtures.

The earlier 0873 JDL self-export established UI-label versus CSV-literal provenance, and the 0874 1D1C Import/re-export established a different exact scope. Neither is repeated here. Formal READY additionally requires current Human-confirmed source tax mapping, exact current account/subaccount mapping, an Evidence-gated route/preflight/serializer, and full-batch atomic validation. The independent non-taxable and taxable-sales signatures, and 10D9C, are not covered by this Evidence.

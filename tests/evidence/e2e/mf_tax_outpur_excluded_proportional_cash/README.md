# EVID-MF-JDL-35-5-OUTPUR-8471-1111-ROUNDTRIP-001

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` for the exact tested 1D1C case only.

- JDL: IBEX 出納帳 35.5, Human-confirmed 課税 / 税抜 / 原則課税 / 一括比例配分方式.
- Source MF tax identity being tested: `対象外仕入` on the debit side. Human selected UI label `0 対象外` in the target company. This UI observation is not itself a CSV literal or a general MF-to-JDL tax mapping.
- Target representation observed in the 2026-05-25 JDL self-export 0873: debit and credit tax category/rate/input method blank, tax amounts `0`. The self-export establishes candidate provenance, not Import compatibility. Private source SHA-256: `1b7db7d1af4ff19a297eef672e5bc2e5e641cc534fbbe7797addddeee5f8c844`.
- Exact Import probe: 2026-05-26, flag `1111`, debit 8471 旅費交通費 / no subaccount, credit 1111 現金 / no subaccount, 1100 integer yen on both sides, no optional fields, description `EVID-TAX-OUTPUR-IMPORT`; official 30 columns, CP932, no BOM, CRLF. Candidate SHA-256: `0b9cb9f3111ee62d0dcaa1c0ee301b530ab0aec36195646bc6721d0a8cc407c2`.
- Human real JDL Import: PASS. Same-day JDL re-export 0874: PASS. Private re-export SHA-256: `52e4974b07ad336d77dfc4afc7ee5597a5f5389c90d9649ab8ecb919f3831f4c`.
- Existing `compare_probe` strict result: `KNOWN_JDL_CANONICAL_NORMALIZATION`; 1 journal / 1 row each, missing 0, extra 0, unexpected changes 0, silent loss 0. Raw differences are voucher blank→0 and both department codes blank→0. Date, flag, accounts, blank subaccounts, all tax fields and tax amounts, balance, description, and order are unchanged.
- Raw source/probe/re-export and manifest remain under `data/private/` and are not Git-tracked. This README contains only synthetic witness values and hashes.

This **does not** activate the 11 real `対象外仕入` journals. Those are 4D6C, 5D7C, and 5D8C compound shapes with per-row descriptions and different relevant account/subaccount identities. The 2026-05-27 private 11-journal/127-row probe independently tests compound grouping, tax interaction, and row-specific descriptions. Each dimension remains PENDING until real Import and same-day strict comparison. The source tax mapping in the current CompanySetting is still `UNRESOLVED`; the probe must never be treated as formal output.

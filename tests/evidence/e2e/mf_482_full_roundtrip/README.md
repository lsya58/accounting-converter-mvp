# MF 482 full real round-trip

## FY2026-05 (378 journals): `EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001`

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT`.

- Target: JDL IBEX 出納帳 35.5, company 0514 (令和8年5月31日決算), 課税 / 税抜 / 原則課税 / 一括比例配分方式, clean target (re-export contains only the imported journals; no earlier E2E or probe journals).
- Source: real MF 482-journal dataset, FY2026-05 part (2025-11-01〜2026-05-31), converted with the saved CompanySetting (all Human settings persisted), `tools/mf_formal_output_by_period.py`.
- Candidate: `mf_formal_jdl_FY2026-05.csv`, SHA-256 `ec2bcc3bd02aa2e31b818bcfffba3b1b4d02fe25ab87b37ca7ba5e76f4f9b90b`. 378 journals / 479 physical rows.
- Human: real JDL Import PASS; re-export of the whole fiscal year 2025-06-02〜2026-05-31 `0878`, SHA-256 `d8b5014194978970ee2a1d0c7172222baaaed55e43688d73a537f0a57a0c17df`.
- `tools/mf_full_e2e_compare.py`: strict positional PASS. Journals 378/378, rows 479/479, missing 0, extra 0, unexpected 0, silent loss 0. Debit = credit = 24,740,332 on both sides.
- 2,442 raw differences, all existing canonical normalizations: voucher blank→0 (479), debit/credit department code blank→0 (958), tax amount blank→0 (573), numeric subaccount zero suppression with unchanged name (432).
- Independently checked: flag, date, account, 課区/税区/税入力方法, amounts, descriptions, subaccount names and every explicit tax amount identical.
- Raw files under `data/private/mf_482_formal_output/`, not tracked.

## FY2027-05 (104 journals)

Not yet run. Needs the next-fiscal-year JDL data with the same master (`mf_formal_jdl_FY2027-05.csv` is generated and verified).

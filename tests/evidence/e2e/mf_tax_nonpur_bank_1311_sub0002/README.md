# EVID-MF-JDL-35-5-NONPUR-8571-1311-SUB0002-001

Status: `VERIFIED_BY_REAL_IMPORT_AND_REEXPORT` for this exact case only.

- Target: JDL IBEX 出納帳 35.5, Human-confirmed 課税 / 税抜 / 原則課税 / 一括比例配分方式.
- Tax Context identity SHA-256: `a300dc8750b7fe6417f2d3c092a6cae2055ccf0256cd539a7036e4b67b0de3e0`.
- Source tax identity: MF `非課税仕入`.
- Exact tested JDL signature: 1D1C, flag `1111`, debit 8571 保険料 / no subaccount / 課区 `非仕入` / 税区・税入力方法 blank / tax amount blank; credit 1311 普通預金 / subaccount `0002` / tax blank. Integer amount 1100 on both sides, no trade partner or other optional fields, description `MF-TAX-NONPUR-1311-PENDING`, both department codes blank.
- Candidate: 2026-05-28, 1 journal / 1 physical row, official 30 columns, CP932, no BOM, CRLF. Human real JDL Import PASS; same-day re-export `0876` PASS.
- Strict comparison (existing `MoneyForwardJdlRoundTripComparator`): journals 1/1, rows 1/1, missing 0, extra 0, unexpected 0, silent loss 0. Six raw differences, all existing canonical normalizations: voucher blank→0; debit and credit tax amount blank→0; credit subaccount code `0002`→`2` with unchanged name (exact `(CREDIT, 1311, 0002, name)` scope, same rule as P05/P07 and 非課税売上); debit and credit department code blank→0. Flag, date, accounts, subaccount identity, amounts, balance, 課区/税区/税入力方法, description and order are unchanged.
- Candidate SHA-256 `36a792c2247f444d40b0ea0c104a61a72b1bdb99fa83dc11fde9c0bae31dc900`; re-export SHA-256 `ae6ea470145e2530e7057ef5ca97778be2c4ccadaa6dbeb42cc88083c80d8b8f`. Raw files remain under `data/private/mf_tax_nonpur_bank_pending_rev2/` and are not tracked.

This is a separate case from `EVID-MF-JDL-35-5-NONPUR-8571-3181-SUB0001-001` (credit 3181/0001). Together the two cases cover all 10 `非課税仕入` occurrences in the real 482-journal dataset by exact signature (9 × 8571→3181/0001, 1 × 8571→1311/0002).

The JDL `非仕入` representation is now verified with two different credit accounts. The debit account is still only 8571, so the composition rule keeps `非課税仕入` limited to 8571 (see [capability composition](../../../../docs/design/mf_tax_capability_composition.md)).

# Money Forward to JDL Formal E2E No. 4

- Evidence ID: `EVID-MF-JDL-FORMAL-E2E-NO4-001`
- Date: 2026-10-18
- Result: `VERIFIED_BY_REAL_IMPORT`
- Source provenance: Money Forward cloud journal CSV exported from a human-created synthetic test company
- Target: JDL IBEX 出納帳 35.5
- Journal count: 1

## Scope

This evidence verifies one balanced `1111` / `1D1C` journal with:

- an explicitly confirmed account mapping on both sides;
- an explicitly confirmed parent-scoped debit subaccount mapping;
- Money Forward `対象外` semantics explicitly mapped to blank JDL tax fields;
- no department, trade partner, invoice classification, tag, or memo;
- one description preserved without truncation;
- CP932, no BOM, and the official 30-column JDL structure.

The source account/subaccount and target account/subaccount identities in these fixtures are synthetic. The amount and description are also synthetic.

## Files

- `source_moneyforward.csv`: unchanged journal record extracted byte-for-byte from the observed Money Forward export.
- `generated_jdl.csv`: formal converter output.
- `jdl_reexport.csv`: JDL re-export after successful Windows import.
- `SHA256SUMS`: fixture hashes.

## Confirmed Result

JDL recognized and imported one journal without an error. The JDL re-export is byte-identical to the generated candidate, including date, flag, account identities, parent-scoped subaccount identity, amounts, blank tax fields, description, departments, encoding, line endings, and all 30 columns.

## Company Setting Conditions

- JDL product/version explicitly confirmed.
- Tax processing context: taxable and tax-inclusive, with the existing scoped confirmation requirements.
- Account, subaccount, and tax mappings: `USER_CONFIRMED` only.
- Fuzzy matching and automatic replacement: disabled.

## Not Proven

This evidence does not verify other accounts, subaccounts, tax categories, compound shapes, departments, trade partners, invoice classifications, tags, memos, or any general Money Forward to JDL production route. It must not be used to broaden the production Registry or `production_allowed` state.

No screenshot is tracked. The machine screenshot remains private because the CSV re-export provides a stricter machine-comparable artifact.

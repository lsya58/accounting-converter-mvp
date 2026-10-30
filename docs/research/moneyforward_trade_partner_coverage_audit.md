# Money Forward trade partner coverage audit

> Historical snapshot from 2026-10-18. The 458/482 figure below records the state at that audit. For current product status, see `docs/development/current_evidence_status.md`.

## Scope

- Audit date: 2026-10-18
- Source: private Money Forward journal export parsed as 482 logical journals
- Purpose: quantify the trade-partner blocker before defining any conversion policy
- Privacy: this document contains counts only. It contains no customer names, account names, partner names, dates, descriptions, or amounts.
- Production behavior: unchanged. Trade-partner data remains blocked by `MoneyForwardToJdlLossRule`.

## Privacy-safe structure counts

The 482-journal source contains 47 journals with at least one side-specific trade-partner value.

| Classification | Count |
|---|---:|
| 1D1C | 29 |
| 2D2C | 18 |
| Other shapes | 0 |
| Debit side only | 29 |
| Credit side only | 18 |
| Both sides | 0 |
| One distinct partner within the journal | 47 |
| Multiple distinct partners within the journal | 0 |
| Tax fields present | 47 |
| Subaccount present | 38 |
| Department present | 0 |

Tax-field presence is not the same as an unresolved tax blocker. None of these 47 journals uses either of the two currently unknown tax literals. Subaccount presence is also not counted as a structural blocker here; the 410-journal formal ceiling assumes company-specific account and subaccount confirmation is complete.

## Blocker overlap and coverage effect

| Trade-partner journals | Count |
|---|---:|
| Trade partner is the only remaining structural/loss blocker | 29 |
| Also blocked by the current compound-shape route | 18 |
| Also blocked by unknown tax | 0 |
| Also blocked by unverified multiple description | 0 |
| Also blocked by department | 0 |

The current structural ceiling is 410/482 (85.06%). The implemented, explicitly confirmed 1D1C description policy passes privacy-safe prechecks for all 29 otherwise-clear journals: final descriptions are at most 32 characters and strict CP932 encodable. Subject to successful Human JDL import/re-export Evidence, the ceiling becomes 439/482 (91.08%). The other 18 require the 2D2C taxable feature combination/route to be resolved independently.

The remaining 18 one-sided trade-partner journals were checked against the
private source without exposing values. All 18 are `2D2C` cases with one debit
purchase-10 tax line, no tax-side subaccount, one side and one distinct partner,
CP932-safe descriptions within 32 characters, and no invoice, tag, memo, or
department blocker. The exact no-subaccount target variant passed Human JDL
Import and strict re-export comparison as
`EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-NO-SUBACCOUNT-DESCRIPTION-ROUNDTRIP-001`.
All 18 now match the limited Evidence scope, raising Evidence-backed coverage
from 439/482 (91.08%) to 457/482 (94.81%). This does not generalize to another
shape, tax category, partner cardinality, optional-field combination, or stale
context.

Threshold arithmetic after the exact no-subaccount release:

| Target | Minimum passing journals | Additional journals needed from 457 |
|---|---:|---:|
| 90% | 434 | 0 |
| 95% | 458 | 1 |
| 98% | 473 | 16 |

The remaining standalone `2D2C` purchase-10 case with no taxable-side
subaccount and no trade partner passed Human JDL import and strict re-export
comparison under
`EVID-JDL-COMPOUND-2D2C-PURCHASE-10-TAXABLE-NO-SUBACCOUNT-ROUNDTRIP-001`.
It releases exactly one additional private journal. Evidence-backed coverage is
therefore 458/482 (95.02%). The remaining 24 journals have other compound
shapes and are not covered by this Evidence.

| Remaining shape | Journals |
|---|---:|
| 2D1C | 10 |
| 4D6C | 5 |
| 5D8C | 5 |
| 10D9C | 1 |
| 1D2C | 1 |
| 2D3C | 1 |
| 5D7C | 1 |
| Total | 24 |

## Limited-pilot batch gate

The 95.02% figure is Evidence coverage, not an assertion that the complete
482-journal source is READY. The formal runtime is atomic, so the 24 remaining
unsupported journals correctly block a whole-file conversion. A privacy-safe
date analysis found 23 candidate intervals containing no unsupported shape;
the largest contains 38 journals. These are structural candidates only and
must be run through the exact saved CompanySetting before being called READY.

Before a limited pilot, one READY-only candidate batch must complete the formal
pipeline and JDL import/re-export check as a batch. The gate includes source and
output journal counts, physical-row counts, debit and credit totals, grouping
and order, atomic no-partial-output behavior, privacy-safe diagnostics, a JDL
backup, and a documented retry procedure using a new output path. Automated
backup/restore UI and support for the remaining shapes can follow during the
pilot; weakening the atomic gate cannot.

## JDL representation evidence

The official JDL IBEX Cashbook 35.5 import schema used by this repository has exactly 30 columns. It has account, subaccount, tax, amount, description, transaction-account, and department columns, but no dedicated trade-partner column.

Existing repository evidence therefore supports the following conclusions:

- Dedicated field in the formal 30-column CSV: not present.
- Independent JDL UI/master feature that survives CSV import and re-export: not verified.
- Description text round-trip: verified for specific simple/compound scopes, with CP932 encoding and a 32-character limit.
- Trade partner transformed into description: `VERIFIED_BY_REAL_IMPORT` for the narrow 1D1C scope under `EVID-MF-JDL-TRADE-PARTNER-1D1C-DESCRIPTION-ROUNDTRIP-001`.
- Current classification: dedicated field unavailable; explicit, company-confirmed description transformation verified for the documented scope only.

The generic compatibility model includes `DROP_WITH_CONFIRMATION`, `UNSUPPORTED`, and `UNKNOWN` transformation concepts. The new company-scoped profile mapping adds `APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED`; it is not a drop policy and requires `USER_CONFIRMED` plus an exact JDL context hash. The runtime continues to block when the policy is absent, stale, or outside its narrow scope.

## Description transformation assessment

The implementation uses `{description} / 取引先:{partner}` or `取引先:{partner}` and enforces:

- the combined value must fit the JDL 32-character description limit;
- the combined value must encode strictly as CP932;
- existing descriptions must retain exact content and order;
- debit-only, credit-only, and future both-side cases need an unambiguous side marker;
- compound journals require a deterministic physical-row placement rule;
- truncation would lose information and must remain prohibited;
- existing description round-trip evidence does not prove the trade-partner transformation rule.

An explicit company policy is implemented and now requires the verified Evidence ID plus an exact JDL context hash. `DROP_WITH_CONFIRMATION` remains a separate deliberate information-loss policy and was not introduced.

The separate 1,953-journal private dataset contains no trade-partner values, so this policy releases 0 journals there and does not change its 1,577/1,953 (80.75%) structural ceiling.

## Verified Human evidence

The independent-field check is complete: neither the confirmed 30-column CSV nor the reviewed JDL voucher UI exposes a trade-partner field. The minimum transformation probe was imported and re-exported successfully:

1. Generate a synthetic 1D1C candidate using already verified account/tax/subaccount identities.
2. Use a short existing synthetic description plus a short synthetic partner label/value, keeping the final description within 32 characters and CP932.
3. Record the exact delimiter, label, side, and resulting description in a private manifest.
4. Import into JDL IBEX Cashbook 35.5 and re-export.
5. Strictly compare date, flag, accounts, subaccount, tax fields, amounts, complete description text, encoding, and 30-column structure.
6. Treat any truncation, merge, reordering, missing text, duplicate, or extra journal as failure.

Strict semantic comparison passed with the complete transformed description preserved. This Evidence establishes only the tested 1D1C transformation. It must not be generalized to compound or both-side trade-partner cases without separate evidence.

## Priority recommendation

| Priority | Work | Coverage gain | Difficulty | Safety risk |
|---|---|---:|---|---|
| 1 | Import/re-export the generated bounded 1D1C description-preservation probe | up to 29 | Low | Low |
| 2 | Enable the explicit company policy after Human accepts the displayed handling | up to 29 | Low | Medium |
| 3 | Resolve the 2D2C taxable feature combination affecting the remaining 18 partner journals | up to 18 in combination | Medium to high | Medium |
| 4 | Resolve the 13 unknown-tax journals | up to 13 | Medium | Medium |

Production Registry, general MF READY scope, runtime factory, tax mapping, and subaccount handling remain unchanged. The new description policy is opt-in, company-scoped, context-bound, and blocked outside the documented 1D1C scope.

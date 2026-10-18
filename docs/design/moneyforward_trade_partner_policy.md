# Money Forward trade partner description policy

## Purpose and status

Money Forward trade-partner values are preserved on each source journal line, but the confirmed JDL IBEX Cashbook 35.5 30-column import format has no dedicated trade-partner column. This policy provides one company-scoped, explicitly confirmed transformation into JDL description text.

The implementation is evidence-gated and does not change the production Registry or general Money Forward READY scope. Human JDL import and strict re-export comparison passed for `EVID-MF-JDL-TRADE-PARTNER-1D1C-DESCRIPTION-ROUNDTRIP-001`.

## Persisted policy

`ConversionProfile.loss_policy_mappings["trade_partner"]` stores a `MappingValue` with:

- target: `APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED`
- status: `USER_CONFIRMED`
- metadata: exact canonical JDL context SHA-256

Missing, unresolved, unknown, or stale policy values block conversion. The policy is company-specific because each CompanySetting references its own immutable profile revision. It is distinct from `DROP_WITH_CONFIRMATION`: the source value is retained in target description, never discarded.

## Fixed format

- Existing description: `{description} / 取引先:{partner}`
- No existing description: `取引先:{partner}`

Side text is omitted for the supported scope because exactly one side and one distinct partner are required. Original side identity remains in source line metadata. Both-side and multiple-partner journals are blocked.

The description is generated from parsed Money Forward source metadata on each conversion. A transformation marker contains the policy identity, source side, and target-description hash. Reapplying the policy is idempotent only when this marker and hash are consistent; free-form string searching is not used.

## Formal scope

All conditions are mandatory:

- Money Forward observed 19-column input
- 1D1C journal
- trade partner on exactly one side
- exactly one distinct trade-partner value
- existing account, subaccount, and tax Evidence route is valid
- no other optional-field blocker
- final description is at most 32 characters
- final description round-trips through strict CP932
- company policy is explicitly `USER_CONFIRMED`
- saved JDL context hash exactly matches the current context

No truncation, replacement encoding, ellipsis, silent drop, or automatic policy selection is allowed.

The following remain blocked: compound journals including 2D2C, both-side partners, multiple distinct partners, unknown shapes, stale context, invoice/tag/memo combinations, description overflow, and CP932 encoding failure.

## GUI

Company settings exposes `取引先情報の扱い`. The dialog explains that JDL has no dedicated trade-partner CSV field and requires the operator to check `この会社では取引先を摘要へ追加して変換する`. It is never enabled automatically.

## Development probe

Run:

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.generate_trade_partner_probe
```

Private output directory:

`data/private/jdl_trade_partner_probe/`

The generator creates a synthetic MF source, immutable profile/context snapshots, one formal JDL candidate, a hash manifest, and an initially `UNTESTED` result template. It refuses overwrite and marks all artifacts `NOT_FOR_PRODUCTION` where applicable.

Revision 2 was imported into JDL IBEX Cashbook 35.5 and re-exported. Strict comparison passed for date, flag, accounts, parent-scoped subaccount, tax semantics, amounts, complete description, 30-column data structure, CP932, BOM, and CRLF. The resulting Evidence remains limited to the documented one-sided `1D1C` scope.

Place the re-export anywhere under `data/private`, then run:

```bash
PYTHONPATH=src python3 -m accounting_converter.tools.generate_trade_partner_probe \
  --output-dir data/private/jdl_trade_partner_probe \
  --reexport data/private/path/to/jdl_reexport.csv
```

The comparator requires exact 30-field equality and updates only the privacy-safe result JSON. It does not treat truncation, reordered text, or normalized text as equivalent.
## Development probe revision

The first synthetic `1D1C` trade-partner description probe was rejected by
JDL before the description behavior could be evaluated. The selected debit
account had an observed subaccount requirement, while the candidate left the
debit subaccount blank. This result is recorded as `FAILED_PRECONDITION`; it
does not promote mapping or production evidence.

Revision 2 changes only the surrounding journal structure. It reuses the
verified formal E2E No. 4 account, parent-scoped subaccount, tax, and amount
scope, while retaining the synthetic trade-partner description as the sole
experimental variable. Production policy, readiness, and Registry scope are
unchanged.

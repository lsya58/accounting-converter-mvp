# Buddies 3D3C synthetic target probe

Evidence ID: `EVID-YAYOI-JDL-35-5-BUDDIES-3D3C-SALES10-SYNTHETIC-ROUNDTRIP-001`.

Human reported real JDL Import and same-period re-export on 2026-06-15. The existing `yayoi_probe_check` matched this case independently: one journal, three physical rows, `1110/1100/1101`. Whole-batch positional strict comparison also passed (two journals, seven rows). Accounts, blank subaccounts, amounts and balance, credit-side sales-10 external tax and explicit tax amounts, opposite-side blank tax, per-row descriptions, grouping and order were retained. Missing/extra rows and unexpected changes: zero.

Twelve raw differences are covered by existing canonical rules only: voucher filled (3), opposite-side tax amount blank to zero (3), and blank debit/credit department codes to zero (3 each). No comparator rule was added. Private candidate SHA-256: `13835669753fa1b09b7727fdc659d22946627a58eab1e7b7003762a654c5e16d`; private re-export SHA-256: `a1135358b67ecec2e6518c03761f455519c572a710becdd363a0fd6b4dec18b6`.

Scope is the exact synthetic target account/subaccount, tax, amount, shape and serialization signature in the private manifest. This is **not** a Yayoi-source formal conversion. Source tax mapping, different accounts, other layouts and rounding-sensitive amounts are not verified. The target company's tax context was not independently re-confirmed in this run. No production Evidence registry activation or READY change is made. Raw files and detailed result remain under `data/private/yayoi_buddies/evidence_pending_20261104/`.

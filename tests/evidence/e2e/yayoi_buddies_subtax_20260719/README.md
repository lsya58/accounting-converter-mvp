# Buddies JDL 35.5 synthetic probe round-trip, 2026-07-19

Private source: `data/private/yayoi_buddies/subaccount_tax_evidence_20261107/`.
The source and real JDL re-export are not Git fixtures. Strict comparison uses
`accounting_converter.tools.yayoi_gap_probe_check`; raw private values stay local.

| File | Case verdicts, excluding control | Evidence disposition |
|---|---|---|
| TAX15 | 15 PASS | 15 exact tax/amount cases registered |
| STRUCT6 | 6 PASS | 6 exact structure/tax-placement cases registered |
| SUB_KEEP | 2 PASS, 1 CHANGED | Only the two exact coded identities recorded separately |
| SUB_BLANK | 1 MISSING | Account 3141 blank rejected at Import; negative observation only |
| SUB_0000 | 2 MISSING | 1551/3141 code 0000 rejected at Import; negative observations only |
| SUB_NAMEONLY | 2 CHANGED | JDL filled subaccount codes; no success activation |

Five controls were included across the files: three PASS, two MISSING with
their rejected files. The re-export contains 30 logical journals / 46 physical
rows; the six probes contain 35 / 51. No duplicate or unexplained extra case
was detected. Import-screen accepted counts cannot be reconstructed exactly
from the re-export and remain unknown.

For SUB_NAMEONLY the JDL-selected code and name matched one identity in the
local master and other compared fields were retained, but adding a code is a
raw change, not an approved canonical normalization. For the third SUB_KEEP
case, the re-exported subaccount name differed, so leading-zero code
equivalence alone cannot make it PASS.

The 21 positive tax/shape cases extend the scoped registry from 153 to 174.
They do not confirm any Human mapping, remove the need for a coded target
subaccount, or establish formal READY. The exact two SUB_KEEP observations
are held separately because the tax/shape registry cannot encode subaccount
identity. Negative observations must never be used as successful conversion
Evidence.

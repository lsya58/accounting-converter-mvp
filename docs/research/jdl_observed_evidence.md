# JDL Observed Evidence Log

**目的:** JDL CSVに関する実資料の観測結果を、正式仕様と混同しない形で匿名記録する。

この文書は研究ログであり、正式JDL FormatProfileではない。会社名、銀行名、日付、伝番、金額、摘要、個別科目名、個別補助科目名、実CSV行は記録しない。

## Evidence Levels

- `OBSERVED`: 実ファイルまたは帳票から観測したが、正式仕様または実機取込成功では未確認。
- `VERIFIED_BY_REAL_IMPORT`: 生成CSVを対象JDLへ実際に取り込み、件数、貸借、内容確認まで完了。

今回のEvidenceは `OBSERVED` に留める。JDLOutputAdapterのEvidenceLevelは上げない。

## EVID-JDL-001

- source: prior failed-import dataset
- product/version evidence: JDL IBEX出納帳 35.5として確認済みの実データ
- evidence level: `OBSERVED`
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 30-column header family
  - header first cell is `//識別フラグ`
  - pre-header metadata/comment rows and blank row exist
  - identifier flag values observed: `1000`, `1100`, `1101`, `1110`, `1111`
- observed behavior:
  - diagnostic message rows can follow data records
  - padded diagnostic message rows can have the same column count as data records
  - `1110 -> 0..n * 1100 -> 1101` contiguous group candidates were observed
  - multiple group candidates had same voucher/date and debit/credit balance
- limits:
  - not a formal JDL CSV specification
  - not verified as a successful import file
  - identifier flag meanings remain unresolved

## EVID-JDL-002

- source: JDL-origin export sample
- product/version evidence: JDL origin strongly suggested; product version unverified
- evidence level: `OBSERVED`
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 30-column header family
  - pre-header metadata/comment rows and blank row exist
  - data records are 30 columns
  - identifier flag values observed: `1000`, `1100`, `1101`, `1110`, `1111`
- observed behavior:
  - `1110 -> 0..n * 1100 -> 1101` contiguous group candidates were re-observed
  - observed group candidates had same voucher/date and debit/credit balance in aggregate
  - file-level debit and credit totals matched in diagnostic aggregate
- limits:
  - version is `UNVERIFIED`
  - not merged into the 35.5 version-specific evidence as confirmed behavior
  - not called a known-good import file
  - no importability claim is made

## EVID-JDL-MASTER-001

- source: JDL account master report
- scope: customer-specific target master evidence
- evidence level: `OBSERVED_PENDING_TEXT_REVIEW`
- current status:
  - a private PDF report exists as candidate master evidence
  - this development environment has no PDF text extraction utility/library available
  - report contents were not transcribed into tracked files
- review targets:
  - whether account code/name list exists
  - whether subaccounts appear under accounts
  - whether subaccount display-code format differs from CSV field representation
- limits:
  - customer-specific account/subaccount values are not format rules
  - no normalization rule such as display-code to CSV-code conversion is established
  - this supports the need for future master-aware Mapping Review, not automatic mapping

## EVID-JDL-003

- source: JDL会計 仕訳一覧CSV
- product/version evidence: JDL会計由来として実務上確認。versionは未確認。
- evidence level: `OBSERVED`
- purpose: post-import verification candidate / read-only evidence
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 21-column journal list export family
  - pre-header rows exist
  - header names/order differ from JDL IBEX出納帳30-column observed schema
  - data rows are 21 columns in the observed main body
- observed behavior:
  - account, subaccount, amount, description, tax-scope/tax-category-like fields are visible in the journal-list header
  - date values are not yet safely interpreted as calendar dates by the current analyzer
  - footer/summary-like non-21-column rows can appear after the main body
- separation:
  - not a 30-column import candidate format
  - not used for EXP-01 CSV generation
  - not merged into JDL IBEX出納帳35.5 observed import/export evidence
  - not verified as an importable CSV format
- limits:
  - version is `UNKNOWN`
  - field semantics are read-only verification candidates only
  - no claim is made that JDL会計 and JDL IBEX出納帳 share a CSV specification
  - no `VERIFIED_BY_REAL_IMPORT` promotion is made

## Tax / Department Notes

- Tax and department columns are treated as observed fields only.
- Empty or repeated values in one dataset do not establish tax mapping, department mapping, default rules, or code meaning.
- Formal tax/category/department behavior requires additional real data and JDL import verification.

## Next Verification Gate

To move any JDL output capability to `VERIFIED_BY_REAL_IMPORT`, run:

1. Generate fully fictional JDL import experiment CSV.
2. Import it into the target JDL environment.
3. Record `PASS` or `REJECTED` in the private experiment manifest.
4. Compare fingerprints against prior observed files.
5. Confirm record/group counts, debit/credit totals, and journal content inside JDL.

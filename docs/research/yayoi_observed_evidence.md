# Yayoi Observed Evidence Log

**目的:** 弥生CSVに関する実資料・架空テスト資料の観測結果を、公式ドキュメント仕様や正式FormatProfileと混同しない形で記録する。

この文書は研究ログであり、正式YayoiInputAdapter、正式YayoiFormatProfile、万能な弥生CSV仕様ではない。摘要本文、実際の勘定科目名、補助科目名、個別日付、個別金額、raw CSV rowは記録しない。

## Evidence Levels

- `OFFICIAL_DOCUMENTED`: 弥生公式ドキュメント上の仕様。
- `OBSERVED`: raw fileをローカル診断で解析して観測。
- `VERIFIED_BY_REAL_IMPORT`: 生成または変換ファイルを対象ソフトへ実際に取り込み、件数・貸借・内容確認まで完了。

## EVID-YAYOI-OFFICIAL-001

- source: 弥生公式サポート「弥生取り込み（インポート）形式（弥生会計05以降）」
- evidence level: `OFFICIAL_DOCUMENTED`
- documented field count: 25
- documented identifier flags: `2000`, `2111`, `2110`, `2100`, `2101`
- status:
  - official documented model is implemented
  - real data verification remains separate
  - not a formal `YayoiInputAdapter`

## EVID-YAYOI-AE19-001

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 弥生自身のエクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 25 fields
  - identifier flag `2000`
  - 1 data record / 1 single-record candidate
  - no header row observed
  - debit/credit amount fields were parseable
  - debit/credit totals were balanced
  - date representation matched a Japanese-era dot/slash candidate shape
  - tax category and tax amount fields were non-empty
  - trailing empty field count was zero
- synthetic regression:
  - a fully synthetic fixture mirrors the reported shape
  - it does not copy real exported row values
  - it is used only to protect parser behavior
- limits:
  - one sample / one journal is insufficient for formal adapter readiness
  - no claim is made that all Yayoi products or versions use this exact shape
  - detailed semantic mapping of every field remains pending additional samples

## EVID-YAYOI-AE19-002

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- relationship to EVID-YAYOI-AE19-001:
  - same direct export route family
  - adds multiple independent single-record journals
- observed structure:
  - CP932
  - CRLF
  - BOMなし
  - 4 physical lines
  - 4 data records / 4 single-record candidates
  - every record has 25 fields
  - no header row observed
  - identifier flag `2000` observed in all records
  - voucher-like field was populated in all records
  - date representation matched a Japanese-era dot/slash candidate shape
  - debit/credit amount fields were parseable in all records
  - debit/credit totals were balanced in aggregate
  - tax category and tax amount fields were non-empty in all records
  - description field was blank in one record and non-empty in three records
  - one description field required CSV quoting for comma and double quote characters
  - trailing empty field count was zero for all records
- official comparison:
  - official documented column count and observed dominant column count both 25
  - observed identifier flag is in the official documented flag set
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- limits:
  - all observed records are `2000`; no `2111` or `2110/2100/2101` evidence yet
  - subaccount and department populated cases remain unverified in raw AE19 evidence
  - multiple tax strings were observed, but tax semantic mapping is not established
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-003

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- relationship to EVID-YAYOI-AE19-002:
  - the first four records match the previous multi-record evidence
  - adds one independent single-record journal with a populated debit subaccount field
- observed structure:
  - file size: 670 bytes
  - CP932
  - CRLF
  - BOMなし
  - 5 physical lines
  - 5 data records / 5 single-record candidates
  - every record has 25 fields
  - no header row observed
  - identifier flag `2000` observed in all records
  - official documented debit subaccount position was populated in 1 record
  - official documented credit subaccount position was blank in all records
  - department fields remained blank in all records
  - debit/credit amount fields were parseable in all records
  - debit/credit totals were balanced in aggregate
  - tax category and tax amount fields were non-empty in all records
  - trailing empty field count was zero for all records
- official comparison:
  - official documented column count and observed dominant column count both 25
  - official documented debit subaccount field position matches the observed populated field
  - observed identifier flag is in the official documented flag set
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - only debit subaccount population was observed; credit subaccount population remains unverified
  - no subaccount import success into Yayoi has been verified
  - all observed records are still `2000`; no `2111` or `2110/2100/2101` evidence yet
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-004

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- purpose:
  - observe a single-record journal with a populated department field
- observed structure:
  - file size: 286 bytes
  - CP932
  - CRLF
  - BOMなし
  - 2 physical lines
  - 2 data records / 2 single-record candidates
  - every record has 25 fields
  - no header row observed
  - identifier flag `2000` observed in all records
  - official documented debit department position was populated in 1 record
  - official documented credit department position was blank in all records
  - official documented debit subaccount position was populated in 1 record
  - official documented credit subaccount position was blank in all records
  - debit/credit amount fields were parseable in all records
  - debit/credit totals were balanced in aggregate
  - tax category and tax amount fields were non-empty in all records
  - trailing empty field count was zero for all records
- comparison to EVID-YAYOI-AE19-003:
  - both evidence files remain CP932, CRLF, BOMなし, 25 fields, no header, and `2000` single-record candidates
  - EVID-YAYOI-AE19-003 added debit subaccount population
  - EVID-YAYOI-AE19-004 adds debit department population
- official comparison:
  - official documented column count and observed dominant column count both 25
  - official documented debit department field position matches the observed populated field
  - observed identifier flag is in the official documented flag set
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, department names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - only debit department population was observed; credit department population remains unverified
  - no department import success into Yayoi has been verified
  - all observed records are still `2000`; no `2111` or `2110/2100/2101` evidence yet
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-005

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- purpose:
  - observe single-record journals with populated credit-side subaccount and department fields
- observed structure:
  - file size: 578 bytes
  - CP932
  - CRLF
  - BOMなし
  - 4 physical lines
  - 4 data records / 4 single-record candidates
  - every record has 25 fields
  - no header row observed
  - identifier flag `2000` observed in all records
  - official documented debit subaccount position was populated in 1 record
  - official documented debit department position was populated in 1 record
  - official documented credit subaccount position was populated in 1 record
  - official documented credit department position was populated in 1 record
  - debit/credit amount fields were parseable in all records
  - debit/credit totals were balanced in aggregate
  - tax category and tax amount fields were non-empty in all records
  - trailing empty field count was zero for all records
- comparison to EVID-YAYOI-AE19-004:
  - both evidence files remain CP932, CRLF, BOMなし, 25 fields, no header, and `2000` single-record candidates
  - EVID-YAYOI-AE19-004 confirmed debit-side department population
  - EVID-YAYOI-AE19-005 adds credit-side subaccount and credit-side department population
- official comparison:
  - official documented column count and observed dominant column count both 25
  - official documented credit subaccount and credit department field positions match the observed populated fields
  - observed identifier flag is in the official documented flag set
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, department names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - no subaccount or department import success into Yayoi has been verified
  - all observed records are still `2000`; no `2111` or `2110/2100/2101` evidence yet
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-006

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- purpose:
  - observe a one-line voucher-style journal record with identifier flag `2111`
- observed structure:
  - file size: 709 bytes
  - CP932
  - CRLF
  - BOMなし
  - 5 physical lines
  - 5 data records / 5 single-record candidates
  - every record has 25 fields
  - no header row observed
  - identifier flags observed: `2000` in 4 records and `2111` in 1 record
  - the first four records match EVID-YAYOI-AE19-005
  - the added `2111` record has the same populated field positions as the observed `2000` single-record shape, except for the identifier flag value
  - voucher-like field was populated in the `2111` record
  - date representation matched a Japanese-era dot/slash candidate shape
  - debit/credit amount fields were parseable
  - debit/credit totals were balanced in aggregate
  - tax category and tax amount fields were non-empty
  - trailing empty field count was zero for all records
- comparison to `2000`:
  - observed structure remained 25 fields, CP932, CRLF, BOMなし, no header, parseable date/amount fields, and balanced totals
  - observed structural difference was the identifier flag value changing from `2000` to `2111`
- official comparison:
  - `2111` is in the official documented identifier flag set
  - official documented column count and observed dominant column count both 25
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, department names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - only a one-line `2111` case has been observed
  - `2110/2100/2101` multi-record voucher behavior remains unverified in raw AE19 evidence
  - no import success into Yayoi has been verified from generated output
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-007

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- purpose:
  - observe a multi-record voucher-style journal sequence and journal grouping candidate
- observed structure:
  - file size: 1057 bytes
  - CP932
  - CRLF
  - BOMなし
  - 8 physical lines
  - 8 data records
  - 6 journal candidates
  - every record has 25 fields
  - no header row observed
  - identifier flags observed: `2000` in 4 records, `2111` in 1 record, `2110` in 1 record, `2100` in 1 record, and `2101` in 1 record
  - the first five records match EVID-YAYOI-AE19-006
  - one multi-record sequence was observed as `2110 -> 2100 -> 2101`
  - all records in the multi-record sequence had the same voucher-like field
  - all records in the multi-record sequence had the same date field
  - multi-record sequence debit total and credit total were balanced
  - debit-only records were represented with debit account/amount populated and credit account blank with zero amount
  - credit-only record was represented with credit account/amount populated and debit account blank with zero amount
  - tax category and tax amount fields were non-empty in all records
  - description field was populated on the closing `2101` record in the observed multi-record sequence
  - trailing empty field count was zero for all records
- official comparison:
  - `2110`, `2100`, and `2101` are in the official documented identifier flag set
  - official documented column count and observed dominant column count both 25
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, department names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - only one `2110 -> 2100 -> 2101` sequence has been observed
  - multiple `2100` middle rows remain unverified in raw AE19 evidence
  - no import success into Yayoi has been verified from generated output
  - no claim is made that all Yayoi products or versions use this exact shape

## EVID-YAYOI-AE19-008

- source: fully fictional Yayoi AE 19 direct export raw file
- product reported: 弥生会計 AE 19
- installer version reported: 25.1.1
- export route reported: 仕訳日記帳 -> エクスポート -> 弥生インポート形式
- evidence level: `OBSERVED`
- raw byte verification status: verified locally
- purpose:
  - observe a multi-record voucher-style journal sequence with more than one middle `2100` record
- observed structure:
  - file size: 1523 bytes
  - CP932
  - CRLF
  - BOMなし
  - 12 physical lines
  - 12 data records
  - 7 journal candidates
  - every record has 25 fields
  - no header row observed
  - identifier flags observed: `2000` in 4 records, `2111` in 1 record, `2110` in 2 records, `2100` in 3 records, and `2101` in 2 records
  - the first eight records match EVID-YAYOI-AE19-007
  - one multi-record sequence was observed as `2110 -> 2100 -> 2101`
  - one multi-record sequence was observed as `2110 -> 2100 -> 2100 -> 2101`
  - all records inside each multi-record sequence had the same voucher-like field
  - all records inside each multi-record sequence had the same date field
  - each multi-record sequence debit total and credit total was balanced
  - debit-only records were represented with debit account/amount populated and credit account blank with zero amount
  - credit-only records were represented with credit account/amount populated and debit account blank with zero amount
  - tax category and tax amount fields were non-empty in all records
  - description field was populated on the closing `2101` records in the observed multi-record sequences
  - trailing empty field count was zero for all records
- official comparison:
  - `2110`, `2100`, and `2101` are in the official documented identifier flag set
  - official documented column count and observed dominant column count both 25
  - structural status remains `MATCH_CANDIDATE`
  - `formal_profile_ready` remains false
- privacy note:
  - account names, subaccount names, department names, description text, individual dates, individual amounts, and raw rows are not recorded here
- limits:
  - only two multi-record sequences have been observed
  - generated output import success into Yayoi has not been verified
  - no claim is made that all Yayoi products or versions use this exact shape

## Internal Parser Status

- `YayoiObservedSingleRecordParser` can parse only the narrow observed subset:
  - CP932 path input
  - 25 fields
  - identifier flag `2000` or observed one-line `2111`
  - observed multi-record sequence `2110 -> 2100+ -> 2101`
  - same non-blank voucher-like field across a multi-record sequence
  - same non-blank date field across a multi-record sequence
  - parseable date
  - parseable debit/credit amounts
  - balanced single-record journals or balanced multi-record sequence totals
  - optional debit/credit subaccount and department values, mapped by the official documented column names
- It is diagnostics/internal infrastructure, not a production `YayoiInputAdapter`.
- Unknown flags, malformed multi-record sequences, voucher/date mismatches, unknown column counts, unparseable dates, unparseable amounts, and unbalanced records are blocking errors.

## Required Additional Yayoi Evidence

Before implementing a production `YayoiInputAdapter`, collect at least:

1. Multiple independent single-line journals.
2. Multiple tax category and tax amount patterns.
3. Blank description.
4. Description with comma and quotes.
5. Debit multi-line voucher variations.
6. Credit multi-line voucher variations.
7. Empty optional trailing fields.
8. Import success verification for generated output.
9. Export files from the exact production Yayoi product/version intended for MVP.

## Current Boundary

- Official documented evidence and observed/export evidence stay separate.
- `formal_profile_ready` remains false.
- No customer-specific value becomes a specification.
- No automatic mapping, normalization, or accounting judgment is created from this evidence.

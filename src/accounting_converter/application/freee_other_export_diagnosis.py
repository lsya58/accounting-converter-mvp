"""freee会計's OTHER-VENDOR exports (JDLインポート形式 9列 / 弥生会計インポート形式 25列): spec comparison only.

Read-only and diagnosis-only. These are files freee writes FOR other products; this module only
describes their structure and how it differs from what this application already handles:

- freee JDL形式 (freee says: for JDL「会計net」) vs the JDL IBEX 出納帳 35.5 30-column import that
  this application writes (profiles.jdl_official). Nothing here says the 9-column file can be
  imported into IBEX 出納帳 35.5: that is UNVERIFIED and is not tried here.
- freee 弥生形式 vs the existing Yayoi import-format reader's contract
  (adapters.input.yayoi.import_format_parser). The file is NOT fed to that reader or to any
  conversion: whether Yayoi imports it, and whether it means what a real Yayoi export means, is
  UNVERIFIED.

Evidence: real exports of each (freee test office, private): E4 (six fictitious 振替伝票, 2026-11-15),
E5B第1回 (eight fictitious journals, 税込経理, 2026-11-22) and E5B-2B (two journals registered under
税抜経理, 2026-11-22); IDs in adapters.input.freee.journal_csv. Under 税抜経理 (E5B-2B) the JDL形式 kept the
仮払/仮受消費税 as a separate row with the same 課区・税区 as its base row, while the 弥生形式 folded it back into
one 税込 row with an explicit 税金額. Neither representation is verified for any target.
Account / subaccount codes in the JDL file come from freee's export settings: in E5B 1001 / 9999 were
the values the settings screen showed by default and 8888 / 0001 were typed for the comparison. None
is a code of a real JDL company, approved or verified for IBEX 35.5. The report holds counts and
codes of the FORMAT only: no accounts, codes, amounts or descriptions.

Information loss: in E5B the 経過措置 purchases (課対仕入（控80）10% / （控70）10%) came out with BLANK
課区・税区 (JDL9) and a BLANK 税区分 (弥生25), while 対象外 is 0/0 resp. 対象外. A blank tax cell is
therefore reported as lost information. It is never read as 対象外 and never filled with a guessed
code; from one file alone the cause of a blank is not identified.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from accounting_converter.adapters.input.yayoi.import_format_parser import OBSERVED_ADJUSTMENT, OBSERVED_TYPE
from accounting_converter.profiles.jdl_official import JDL_IBEX_CASHBOOK_OFFICIAL_JOURNAL_IMPORT_COLUMNS
from accounting_converter.profiles.yayoi_official import yayoi_accounting_05_official_import_spec

# ----------------------------------------------------------------------------- freee JDL形式 (9 columns)

FREEE_JDL_TITLE = "＜仕訳一覧＞"
FREEE_JDL_END = "＜仕訳一覧終了＞"
FREEE_JDL9_HEADER: tuple[str, ...] = ("日付", "借方科目", "貸方科目", "借方補助", "貸方補助", "金額", "摘要", "課区", "税区")

# Structural facts from the real sample and the two column tables. Codes only; meaning in the research doc.
FREEE_JDL9_VS_JDL30_DIFFERENCES: tuple[str, ...] = (
    "NO_IDENTIFIER_FLAG_COLUMN",  # JDL30 //識別フラグ groups a compound journal; freee JDL has no such column
    "NO_VOUCHER_NUMBER_COLUMN",  # JDL30 伝番
    "COMPOUND_EXPANDED_VIA_RELAY_ACCOUNT",  # 1D2C -> 3 rows through the code the user set for 諸口 (sample)
    "SINGLE_AMOUNT_COLUMN",  # JDL30 has 借方金額 and 貸方金額
    "SINGLE_TAX_CELL_PAIR_PER_ROW",  # one 課区/税区 per row; JDL30 has them per side
    "NO_TAX_AMOUNT_COLUMN",  # JDL30 借方消費税 / 貸方消費税
    "NO_TAX_INPUT_METHOD_COLUMN",  # JDL30 借方税入力方法 / 貸方税入力方法
    "NO_ACCOUNT_NAME_COLUMNS",  # JDL30 科目名称 / 科目正式名称 / 補助名称
    "NO_DEPARTMENT_COLUMNS",
    "NO_TRANSACTION_ACCOUNT_COLUMNS",  # JDL30 借方取引科目 / 貸方取引科目
    "TITLE_AND_END_RECORDS",  # ＜仕訳一覧＞ / ＜仕訳一覧終了＞ one-column records
    "CLOSING_AS_MONTH_13_DATE",  # 決算整理 dated YYYY13DD (sample: 20261331); meaning for the target unverified
    "DESCRIPTION_IS_COMPOSED",  # 取引先 品目 メモ 備考 joined by spaces (sample); relay rows may be blank
    "CODES_FROM_FREEE_EXPORT_SETTINGS",  # codes come from freee's export settings; not target master codes
    "TRANSITIONAL_CREDIT_TAX_CELLS_BLANK",  # E5B: 控80 / 控70 rows have blank 課区・税区 (not 0/0)
)

# Lost information (code -> what is lost). Counted, never repaired.
INFORMATION_LOSS_CODES: dict[str, str] = {
    "JDL9_TAX_CELLS_BLANK": "課区・税区とも空欄の行（E5Bでは控80・控70の仕入で観測）。対象外（0/0）とは別",
    "YAYOI25_TAX_CATEGORY_BLANK": "勘定科目のある側の税区分が空欄（E5Bでは控80・控70の仕入で観測）。対象外とは別",
}

_DATE8 = re.compile(r"[0-9]{8}")
_INT = re.compile(r"-?[0-9]+")


@dataclass
class FreeeOtherExportDiagnosis:
    format: str
    readable: bool
    issues: Counter = field(default_factory=Counter)
    counts: Counter = field(default_factory=Counter)
    values: dict[str, Counter] = field(default_factory=dict)  # product codes only (課区, 決算, タイプ …)
    differences: tuple[str, ...] = ()
    information_loss: Counter = field(default_factory=Counter)  # INFORMATION_LOSS_CODES -> rows / sides

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "diagnosis_only": True,
            "formal_ready": 0,
            "target_import_verified": False,
            "readable": self.readable,
            "issues": dict(sorted(self.issues.items())),
            "counts": dict(sorted(self.counts.items())),
            "values": {name: dict(sorted(counter.items())) for name, counter in sorted(self.values.items())},
            "differences": list(self.differences),
            "information_loss": {
                code: {"count": count, "meaning": INFORMATION_LOSS_CODES[code]}
                for code, count in sorted(self.information_loss.items())
            },
        }


def _rows(raw: bytes) -> list[list[str]] | None:
    try:
        text = raw.decode("cp932", errors="strict")
    except UnicodeDecodeError:
        return None
    try:
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        return None


def jdl30_columns_absent_from_freee_jdl9() -> tuple[str, ...]:
    names = {column.name.lstrip("/") for column in JDL_IBEX_CASHBOOK_OFFICIAL_JOURNAL_IMPORT_COLUMNS}
    return tuple(sorted(name for name in names if name not in FREEE_JDL9_HEADER))


def diagnose_freee_jdl9(raw: bytes) -> FreeeOtherExportDiagnosis:
    result = FreeeOtherExportDiagnosis("freee_jdl_import_9", False, differences=FREEE_JDL9_VS_JDL30_DIFFERENCES)
    rows = _rows(raw)
    if rows is None:
        result.issues["NOT_CP932_CSV"] += 1
        return result
    if len(rows) < 3 or rows[0] != [FREEE_JDL_TITLE] or rows[-1] != [FREEE_JDL_END]:
        result.issues["TITLE_OR_END_RECORD_MISSING"] += 1
        return result
    if tuple(rows[1]) != FREEE_JDL9_HEADER:
        result.issues["HEADER_NOT_OBSERVED"] += 1
        return result
    result.readable = True
    tax_pairs = result.values.setdefault("課区/税区", Counter())
    for row in rows[2:-1]:
        result.counts["data_rows"] += 1
        if len(row) != len(FREEE_JDL9_HEADER):
            result.issues["COLUMN_COUNT_MISMATCH"] += 1
            continue
        record = dict(zip(FREEE_JDL9_HEADER, row))
        day = record["日付"]
        if not _DATE8.fullmatch(day):
            result.issues["DATE_FORMAT_UNOBSERVED"] += 1
        elif day[4:6] == "13":
            result.counts["rows_dated_month_13"] += 1  # not a calendar date; never converted to one
        else:
            try:
                date(int(day[:4]), int(day[4:6]), int(day[6:]))
            except ValueError:
                result.issues["DATE_NOT_CALENDAR"] += 1
        if not _INT.fullmatch(record["金額"]):
            result.issues["AMOUNT_FORMAT_UNOBSERVED"] += 1
        if not record["摘要"]:
            result.counts["rows_with_blank_description"] += 1
        for side in ("借方", "貸方"):
            if not record[f"{side}科目"]:
                result.issues["BLANK_ACCOUNT_CODE"] += 1
            if record[f"{side}補助"]:
                result.counts[f"rows_with_{'debit' if side == '借方' else 'credit'}_subaccount"] += 1
        tax_pairs[f"{record['課区']}/{record['税区']}"] += 1
        if not record["課区"] and not record["税区"]:
            result.information_loss["JDL9_TAX_CELLS_BLANK"] += 1
        elif not record["課区"] or not record["税区"]:
            result.issues["TAX_CELL_PAIR_PARTIAL"] += 1  # never observed: one of the two blank
    return result


# ----------------------------------------------------------------------------- freee 弥生形式 (25 columns)

_YAYOI_SPEC = yayoi_accounting_05_official_import_spec()
YAYOI25_COLUMNS: tuple[str, ...] = tuple(column.name for column in _YAYOI_SPEC.columns)
_YAYOI_MAX_LENGTH = {column.name: column.max_length for column in _YAYOI_SPEC.columns if column.max_length}
_YAYOI_DATE = re.compile(r"[0-9]{4}/[0-9]{2}/[0-9]{2}")

FREEE_YAYOI25_VS_EXISTING_YAYOI_IMPORT: tuple[str, ...] = (
    "NO_HEADER_ROW",
    "TAX_AMOUNT_COLUMNS_BLANK",  # 税込経理 samples (E4, E5B第1回): 税金額 empty on taxed sides; never computed here
    "DUE_DATE_FILLED_WITH_TRANSACTION_DATE",  # 期日 = 取引日付 on every row (sample)
    "TYPE_3_ON_COMPOUND",  # タイプ 3 on 2110/2101 rows (sample)
    "SUBACCOUNT_CARRIES_FREEE_NAME",  # 借方補助科目 = 口座名 / 取引先名 (sample); Yayoi meaning unverified
    "BLANK_SIDE_IS_EMPTY_ACCOUNT_ZERO_AMOUNT_OUT_OF_SCOPE",  # 2101 row debit: "" / 対象外 / 0
    "DESCRIPTION_IS_COMPOSED",  # same composed 摘要 as the 旧CSV; can exceed the official 30 characters
    "CLOSING_IN_決算_COLUMN",  # 本決 (sample)
    "TRANSITIONAL_CREDIT_TAX_CATEGORY_BLANK",  # E5B: 控80 / 控70 sides have a blank 税区分 (not 対象外)
    "NOT_FED_TO_EXISTING_YAYOI_READER",
)


def diagnose_freee_yayoi25(raw: bytes) -> FreeeOtherExportDiagnosis:
    result = FreeeOtherExportDiagnosis(
        "freee_yayoi_import_25", False, differences=FREEE_YAYOI25_VS_EXISTING_YAYOI_IMPORT,
    )
    rows = _rows(raw)
    if rows is None:
        result.issues["NOT_CP932_CSV"] += 1
        return result
    if not rows or any(len(row) != len(YAYOI25_COLUMNS) for row in rows):
        result.issues["COLUMN_COUNT_MISMATCH"] += 1
        return result
    if rows[0][0] == YAYOI25_COLUMNS[0]:
        result.issues["HEADER_ROW_UNOBSERVED"] += 1
        return result
    result.readable = True
    for name in ("識別フラグ", "決算", "タイプ", "調整", "借方税区分", "貸方税区分"):
        result.values[name] = Counter()
    open_compound = False
    for row in rows:
        record = dict(zip(YAYOI25_COLUMNS, row))
        result.counts["data_rows"] += 1
        flag = record["識別フラグ"]
        for name in ("識別フラグ", "決算", "タイプ", "調整", "借方税区分", "貸方税区分"):
            result.values[name][record[name] or "(空欄)"] += 1
        if flag not in {"2000", "2111", "2110", "2100", "2101"}:
            result.issues["IDENTIFIER_FLAG_UNKNOWN"] += 1
        if flag == "2110":
            if open_compound:
                result.issues["COMPOUND_NOT_CLOSED"] += 1
            open_compound = True
        elif flag in {"2100", "2101"}:
            if not open_compound:
                result.issues["COMPOUND_CONTINUATION_WITHOUT_START"] += 1
            open_compound = flag == "2100"
        elif open_compound:
            result.issues["COMPOUND_NOT_CLOSED"] += 1
            open_compound = False
        if not _YAYOI_DATE.fullmatch(record["取引日付"]):
            result.issues["DATE_FORMAT_UNOBSERVED"] += 1
        if record["タイプ"] not in OBSERVED_TYPE:
            result.counts["rows_type_outside_existing_reader_contract"] += 1
        if record["調整"] not in OBSERVED_ADJUSTMENT:
            result.counts["rows_adjustment_outside_existing_reader_contract"] += 1
        if record["期日"]:
            result.counts["rows_with_due_date"] += 1
            if record["期日"] == record["取引日付"]:
                result.counts["rows_due_date_equals_transaction_date"] += 1
        limit = _YAYOI_MAX_LENGTH.get("摘要")
        if limit and len(record["摘要"]) > limit:
            result.counts["rows_description_over_official_length"] += 1
        for side in ("借方", "貸方"):
            key = "debit" if side == "借方" else "credit"
            account, amount = record[f"{side}勘定科目"], record[f"{side}金額"]
            if not account:
                if amount == "0" and not record[f"{side}補助科目"] and not record[f"{side}税金額"]:
                    result.counts[f"blank_{key}_sides"] += 1
                else:
                    result.issues["BLANK_ACCOUNT_WITH_VALUES"] += 1
                continue
            if not _INT.fullmatch(amount):
                result.issues["AMOUNT_FORMAT_UNOBSERVED"] += 1
            if record[f"{side}補助科目"]:
                result.counts[f"{key}_sides_with_subaccount"] += 1
            category = record[f"{side}税区分"]
            if not category:
                # Lost, not 対象外: counted neither as taxed nor as untaxed.
                result.information_loss["YAYOI25_TAX_CATEGORY_BLANK"] += 1
                continue
            if category != "対象外" and not category.startswith(("非課", "不課")):
                result.counts["taxed_sides"] += 1
                if not record[f"{side}税金額"]:
                    result.counts["taxed_sides_with_blank_tax_amount"] += 1
                else:
                    result.counts["taxed_sides_with_tax_amount"] += 1  # E5B-2B (税抜経理): filled, never verified
    if open_compound:
        result.issues["COMPOUND_NOT_CLOSED"] += 1
    return result

"""freee会計 仕訳帳CSV -> JDL IBEX 出納帳 35.5: read-only diagnosis (DIAGNOSE_ONLY direction).

What it does: reads the file with the strict header-driven freee reader, then reports — in counts
and codes only — what a JDL conversion would need: Human mappings, information JDL cannot hold,
unverified source semantics and unknown columns. It never writes a file, never touches a
CompanySetting and never yields READY: the direction is not PRODUCTION and the freee header is
not verified (no real sample). Customer values (accounts, partners, descriptions, amounts) are not
in the report; freee tax category names and column names are (they are product vocabulary).

Target facts used here are the existing JDL ones (source-independent): what JDL IBEX 出納帳 35.5
can hold, and which physical-row shapes already have JDL row-description Evidence. They are
reported as information, not applied.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from accounting_converter.adapters.input.freee.journal_csv import (
    COLUMN_ROLES,
    FreeeJournalCsvParser,
    FreeeJournalVariant,
    FreeeParseResult,
    Role,
)
from accounting_converter.adapters.output.jdl.row_evidence import JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
from accounting_converter.domain.conversion_direction import direction_for
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.journal_rows import journal_physical_rows, physical_row_shape
from accounting_converter.domain.source_information import closing_adjustment_marker, source_fields

DIRECTION_KEY = "freee_journal_csv->jdl_ibex_cashbook_35_5"

# freee information with no JDL IBEX 出納帳 35.5 import column (JDL holds date, account, subaccount,
# department, tax cells, amounts and a 64-byte description). Counterparty: the MF route needs a
# Human-confirmed transformation (into the description); nothing is decided here.
NO_JDL_COLUMN = "NO_JDL_COLUMN"
NEEDS_HUMAN_TRANSFORMATION = "NEEDS_HUMAN_TRANSFORMATION"
MAPPING_AID = "MAPPING_AID"  # e.g. 決算書表示名 / ショートカット: helps the Human map, not output


def information_class(column: str) -> str:
    base = column[2:] if column[:2] in {"借方", "貸方"} else column
    if base in {"取引先名", "取引先"}:
        return NEEDS_HUMAN_TRANSFORMATION
    if base in {"決算書表示名", "勘定科目ショートカット", "取引先コード", "取引先ショートカット1",
                "取引先ショートカット2", "品目ショートカット1", "部門ショートカット"}:
        return MAPPING_AID
    return NO_JDL_COLUMN


@dataclass(frozen=True)
class FreeeTaxHint:
    """What the freee tax NAME suggests. A hint for the Human, never a mapping."""
    kind: str  # SALES_TAXABLE / PURCHASE_TAXABLE / NON_TAXABLE_SALES / NON_TAXABLE_PURCHASE / EXPORT_SALES / OUT_OF_SCOPE / UNKNOWN
    rate: str | None = None  # "10" / "8"
    reduced: bool = False
    deduction_ratio: str | None = None  # 経過措置 "80" / "50" / "30" ...
    allocation: str | None = None  # 個別対応: 課税売上対応 / 共通対応 / 非課税売上対応

    @property
    def taxed(self) -> bool:
        return self.kind in {"SALES_TAXABLE", "PURCHASE_TAXABLE"}


_RATE = re.compile(r"(10|8)%")
_DEDUCTION = re.compile(r"控(\d{2})")


def tax_hint(name: str | None) -> FreeeTaxHint:
    if not name:
        return FreeeTaxHint("OUT_OF_SCOPE")
    rate_match = _RATE.search(name)
    rate = rate_match.group(1) if rate_match else None
    reduced = "軽" in name
    deduction = _DEDUCTION.search(name)
    if name in {"対象外", "不課税"}:
        return FreeeTaxHint("OUT_OF_SCOPE")
    if name.startswith("輸出"):
        return FreeeTaxHint("EXPORT_SALES")
    if name.startswith("非課売上"):
        return FreeeTaxHint("NON_TAXABLE_SALES")
    if name.startswith("非課仕入"):
        return FreeeTaxHint("NON_TAXABLE_PURCHASE")
    if name.startswith("課税売上"):
        return FreeeTaxHint("SALES_TAXABLE", rate, reduced)
    for prefix, allocation in (("課対仕入", "課税売上対応"), ("共対仕入", "共通対応"), ("非対仕入", "非課税売上対応")):
        if name.startswith(prefix):
            return FreeeTaxHint(
                "PURCHASE_TAXABLE", rate, reduced, deduction.group(1) if deduction else None,
                allocation if prefix != "課対仕入" else None,
            )
    return FreeeTaxHint("UNKNOWN", rate, reduced)


@dataclass
class FreeeDiagnosis:
    parse: FreeeParseResult
    direction_stage: str
    ready_allowed: bool
    journal_blockers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tax_categories: Counter = field(default_factory=Counter)
    information_fields: Counter = field(default_factory=Counter)  # column -> journals
    shapes: Counter = field(default_factory=Counter)
    shapes_with_jdl_row_evidence: int = 0

    @property
    def formal_ready(self) -> int:
        """Always 0 today. Kept computed (not a constant) so the guard is visible and tested."""
        if not self.ready_allowed:
            return 0
        return sum(1 for blockers in self.journal_blockers.values() if not blockers)

    def to_dict(self) -> dict:
        header = self.parse.header
        blockers = Counter(code for codes in self.journal_blockers.values() for code in codes)
        return {
            "direction": DIRECTION_KEY,
            "direction_stage": self.direction_stage,
            "ready_allowed": self.ready_allowed,
            "formal_ready": self.formal_ready,
            "format": None if header is None else {
                "variant": header.variant.value,
                "encoding": header.encoding,
                "header_fingerprint": header.fingerprint,
                "header_verified": header.verified,
                "columns": len(header.columns),
                "unknown_columns": list(header.unknown_columns),
                "assumed_columns": list(header.assumed_columns),
                "source_format_key": header.source_format_key,
            },
            "file_readable": self.parse.file_readable,
            "data_rows": self.parse.data_rows,
            "journals_parsed": len(self.parse.entries),
            "journals_rejected": self.parse.rejected_journals,
            "rows_rejected": self.parse.rejected_rows,
            "issues": dict(Counter(issue.code.value for issue in self.parse.issues)),
            "blockers": dict(sorted(blockers.items())),
            "tax_categories": {
                name or "(空欄)": {"lines": count, "hint": tax_hint(name).__dict__}
                for name, count in sorted(self.tax_categories.items(), key=lambda item: item[0] or "")
            },
            "information_without_jdl_column": {
                column: {"journals": count, "class": information_class(column)}
                for column, count in sorted(self.information_fields.items())
            },
            "shapes": {f"{d}D{c}C/{r}rows": n for (d, c, r), n in sorted(self.shapes.items())},
            "journals_simple_1d1c_or_shape_with_jdl_row_evidence": self.shapes_with_jdl_row_evidence,
        }


def journal_blockers(entry: JournalEntry, *, header_verified: bool, ready_allowed: bool, has_description: bool,
                     variant_known: bool = True) -> tuple[str, ...]:
    found: set[str] = {"HUMAN:ACCOUNT_MAPPING"}  # freee has no confirmed mapping store
    if not variant_known:
        found.add("SYSTEM_EVIDENCE:FREEE_VARIANT_UNKNOWN")
    if not header_verified:
        found.add("SYSTEM_EVIDENCE:FREEE_SOURCE_FORMAT_UNVERIFIED")
    if not ready_allowed:
        found.add("SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION")
    if not has_description:
        found.add("SYSTEM_EVIDENCE:FREEE_DESCRIPTION_SOURCE_UNKNOWN")
    for line in entry.lines:
        info = line.tax_info
        if info is not None and info.category:
            found.add("HUMAN:TAX_MAPPING")
            hint = tax_hint(info.category)
            if hint.kind == "UNKNOWN":
                found.add("SYSTEM_EVIDENCE:FREEE_TAX_CATEGORY_UNRECOGNISED")
            if hint.taxed:
                found.add("SYSTEM_EVIDENCE:FREEE_TAX_INCLUSION_UNKNOWN")  # 内税/外税・税込/税抜
                if info.tax_amount is None:
                    found.add("SYSTEM_EVIDENCE:FREEE_TAX_AMOUNT_ABSENT")
        if line.amount < 0 or (info is not None and info.tax_amount is not None and info.tax_amount < 0):
            found.add("HUMAN:NEGATIVE_AMOUNT")
        if line.department:
            found.add("HUMAN:DEPARTMENT_MAPPING")
        display = line.metadata.get("freee_account_display_name")
        if display and display != line.account:
            found.add("HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS")  # 口座名 etc.: account+subaccount decision
    for value in source_fields(entry):
        if not value.known:
            found.add("SYSTEM_EVIDENCE:UNKNOWN_SOURCE_COLUMN")
        elif information_class(value.field) == NEEDS_HUMAN_TRANSFORMATION:
            found.add("HUMAN:COUNTERPARTY_POLICY")
        elif information_class(value.field) == NO_JDL_COLUMN:
            found.add("HUMAN:NON_RETAINED_INFORMATION")
    if closing_adjustment_marker(entry) is not None:
        found.add("SYSTEM_EVIDENCE:FREEE_CLOSING_MARKER_UNVERIFIED")
    return tuple(sorted(found))


def diagnose_freee_journal_csv(path: Path) -> FreeeDiagnosis:
    return diagnose_parse_result(FreeeJournalCsvParser().parse_path(path))


def diagnose_parse_result(parse: FreeeParseResult) -> FreeeDiagnosis:
    direction = direction_for(DIRECTION_KEY)
    diagnosis = FreeeDiagnosis(parse, direction.stage.value, direction.ready_allowed)
    header = parse.header
    if header is None or not parse.file_readable:
        return diagnosis
    has_description = any(COLUMN_ROLES.get(name) and COLUMN_ROLES[name].role is Role.DESCRIPTION for name in header.columns)
    for entry in parse.entries:
        diagnosis.journal_blockers[entry.id] = journal_blockers(
            entry, header_verified=header.verified, ready_allowed=direction.ready_allowed,
            has_description=has_description, variant_known=header.variant is not FreeeJournalVariant.UNKNOWN,
        )
        for line in entry.lines:
            if line.tax_info is not None:
                diagnosis.tax_categories[line.tax_info.category] += 1
        for column in {value.field for value in source_fields(entry) if value.known}:
            diagnosis.information_fields[column] += 1
        rows = journal_physical_rows(entry)
        if rows is not None:
            shape = physical_row_shape(rows)
            diagnosis.shapes[shape] += 1
            if shape in JDL_ROW_DESCRIPTION_VERIFIED_SHAPES or (shape[2] == 1 and shape[:2] == (1, 1)):
                diagnosis.shapes_with_jdl_row_evidence += 1
    return diagnosis

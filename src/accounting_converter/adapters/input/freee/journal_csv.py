"""freee会計 仕訳帳CSV (新CSV / 旧CSV): strict, header-driven reading for DIAGNOSIS ONLY.

Status: NOT a production input adapter. No real freee export has been seen. What is known comes
from fragments of freee's public help (docs/research/freee_journal_csv_public_spec.md); the full
column list, its order, the 摘要 column and the 税込/税抜・内税/外税 representation are UNVERIFIED.
Consequently:

- columns are recognised by NAME, never by position;
- a column this module does not know is kept verbatim (SourceFieldValue known=False) and blocks;
- the header is fingerprinted (SHA-256) so a real sample can later be registered EXACTLY
  (`VERIFIED_HEADER_FINGERPRINTS` is empty: every header is unverified today);
- this module is not registered in `production_adapter_registry` and is not an `InputAdapter`, so
  it cannot be plugged into ConversionService / any formal output.

Entries use the common model (domain.journal) and the neutral keys of domain.journal_rows and
domain.source_information. Nothing is dropped silently.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY, journal_content_identity
from accounting_converter.domain.journal_rows import (
    LINE_COUNTERPARTY_KEY,
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
)
from accounting_converter.domain.source_information import (
    ENTRY_CLOSING_ADJUSTMENT_KEY,
    ENTRY_SOURCE_FIELDS_KEY,
    ENTRY_SOURCE_FORMAT_KEY,
    SourceFieldScope,
    SourceFieldValue,
)

SOURCE_FORMAT_PREFIX = "freee_journal_csv"

# Real freee headers confirmed from an actual export (none yet). Only an exact fingerprint here may
# ever be treated as a verified source format.
VERIFIED_HEADER_FINGERPRINTS: frozenset[str] = frozenset()


class FreeeJournalVariant(str, Enum):
    NEW_CSV = "NEW_CSV"  # 「CSVエクスポート」: all items incl. internal data, no per-item choice
    OLD_CSV = "OLD_CSV"  # 「CSV・PDFエクスポート(旧)」: general items, some optional per checkbox
    UNKNOWN = "UNKNOWN"


class Provenance(str, Enum):
    PUBLIC_HELP_EXCERPT = "PUBLIC_HELP_EXCERPT"  # column name seen in freee help text (excerpt)
    SYMMETRIC_ASSUMPTION = "SYMMETRIC_ASSUMPTION"  # 貸方 counterpart of a documented 借方 column


class Role(str, Enum):
    JOURNAL_NUMBER = "JOURNAL_NUMBER"  # No.: same number = one journal (documented for 旧CSV)
    DATE = "DATE"
    ACCOUNT = "ACCOUNT"
    AMOUNT = "AMOUNT"
    TAX_CATEGORY = "TAX_CATEGORY"
    TAX_AMOUNT = "TAX_AMOUNT"
    DEPARTMENT = "DEPARTMENT"
    COUNTERPARTY = "COUNTERPARTY"
    DESCRIPTION = "DESCRIPTION"  # 摘要: existence and name UNVERIFIED
    CLOSING = "CLOSING"  # 決算整理仕訳: value semantics UNVERIFIED
    INFORMATION = "INFORMATION"  # kept as source field; no common-model slot


@dataclass(frozen=True)
class ColumnRole:
    role: Role
    side: Side | None
    provenance: Provenance
    variants: frozenset[FreeeJournalVariant]


_BOTH = frozenset({FreeeJournalVariant.NEW_CSV, FreeeJournalVariant.OLD_CSV})
_NEW = frozenset({FreeeJournalVariant.NEW_CSV})
_OLD = frozenset({FreeeJournalVariant.OLD_CSV})
_H = Provenance.PUBLIC_HELP_EXCERPT
_S = Provenance.SYMMETRIC_ASSUMPTION

_JOURNAL_COLUMNS: dict[str, ColumnRole] = {
    "No.": ColumnRole(Role.JOURNAL_NUMBER, None, _H, _BOTH),
    "取引日": ColumnRole(Role.DATE, None, _H, _BOTH),
    "管理番号": ColumnRole(Role.INFORMATION, None, _H, _NEW),
    "仕訳番号": ColumnRole(Role.INFORMATION, None, _H, _OLD),
    "作成日時": ColumnRole(Role.INFORMATION, None, _H, _OLD),
    "決算整理仕訳": ColumnRole(Role.CLOSING, None, _H, _OLD),
    "摘要": ColumnRole(Role.DESCRIPTION, None, _S, _BOTH),
}

# (suffix after 借方/貸方, role, provenance of the 借方 column, variants)
_SIDE_COLUMNS: tuple[tuple[str, Role, Provenance, frozenset[FreeeJournalVariant]], ...] = (
    ("勘定科目", Role.ACCOUNT, _H, _BOTH),
    ("決算書表示名", Role.INFORMATION, _H, _NEW),
    ("勘定科目ショートカット", Role.INFORMATION, _H, _NEW),
    ("金額", Role.AMOUNT, _H, _BOTH),
    ("税区分", Role.TAX_CATEGORY, _H, _BOTH),
    ("税金額", Role.TAX_AMOUNT, _H, _NEW),
    ("取引先コード", Role.INFORMATION, _H, _NEW),
    ("取引先名", Role.COUNTERPARTY, _H, _NEW),
    ("取引先ショートカット1", Role.INFORMATION, _H, _NEW),
    ("取引先ショートカット2", Role.INFORMATION, _H, _NEW),
    ("取引先", Role.COUNTERPARTY, _H, _OLD),
    ("品目", Role.INFORMATION, _H, _BOTH),
    ("品目ショートカット1", Role.INFORMATION, _H, _NEW),
    ("部門", Role.DEPARTMENT, _H, _BOTH),
    ("部門ショートカット", Role.INFORMATION, _H, _NEW),
    ("メモタグ", Role.INFORMATION, _H, _OLD),
    ("セグメント1", Role.INFORMATION, _H, _BOTH),
    ("セグメント2", Role.INFORMATION, _H, _OLD),
    ("セグメント3", Role.INFORMATION, _H, _OLD),
    ("備考", Role.INFORMATION, _S, _BOTH),
)


def _column_roles() -> dict[str, ColumnRole]:
    roles = dict(_JOURNAL_COLUMNS)
    for suffix, role, provenance, variants in _SIDE_COLUMNS:
        roles[f"借方{suffix}"] = ColumnRole(role, Side.DEBIT, provenance, variants)
        roles[f"貸方{suffix}"] = ColumnRole(role, Side.CREDIT, _S, variants)
    return roles


COLUMN_ROLES: dict[str, ColumnRole] = _column_roles()
REQUIRED_COLUMNS = ("No.", "取引日", "借方勘定科目", "借方金額", "貸方勘定科目", "貸方金額")
NEW_CSV_MARKERS = frozenset(
    name for name, role in COLUMN_ROLES.items() if role.variants == _NEW and role.provenance is _H
)
OLD_CSV_MARKERS = frozenset(
    name for name, role in COLUMN_ROLES.items() if role.variants == _OLD and role.provenance is _H
)

_DATE = re.compile(r"(?P<y>[0-9]{4})/(?P<m>[0-9]{1,2})/(?P<d>[0-9]{1,2})")
_AMOUNT = re.compile(r"-?[0-9]+")


class FreeeIssue(str, Enum):
    # file level (nothing is parsed)
    UNREADABLE = "UNREADABLE"
    ENCODING_UNKNOWN = "ENCODING_UNKNOWN"
    MALFORMED_CSV = "MALFORMED_CSV"
    NO_DATA_ROWS = "NO_DATA_ROWS"
    REQUIRED_COLUMN_MISSING = "REQUIRED_COLUMN_MISSING"
    DUPLICATE_COLUMN = "DUPLICATE_COLUMN"
    COLUMN_COUNT_MISMATCH = "COLUMN_COUNT_MISMATCH"
    VARIANT_AMBIGUOUS = "VARIANT_AMBIGUOUS"
    # journal level (that journal is rejected)
    JOURNAL_NUMBER_MISSING = "JOURNAL_NUMBER_MISSING"
    JOURNAL_NUMBER_REUSED = "JOURNAL_NUMBER_REUSED"
    DATE_FORMAT_UNVERIFIED = "DATE_FORMAT_UNVERIFIED"
    MULTIPLE_DATES = "MULTIPLE_DATES"
    AMOUNT_FORMAT_UNVERIFIED = "AMOUNT_FORMAT_UNVERIFIED"
    SIDE_WITHOUT_ACCOUNT_OR_AMOUNT = "SIDE_WITHOUT_ACCOUNT_OR_AMOUNT"
    EMPTY_ROW = "EMPTY_ROW"
    UNBALANCED = "UNBALANCED"


FILE_LEVEL_ISSUES = frozenset({
    FreeeIssue.UNREADABLE, FreeeIssue.ENCODING_UNKNOWN, FreeeIssue.MALFORMED_CSV, FreeeIssue.NO_DATA_ROWS,
    FreeeIssue.REQUIRED_COLUMN_MISSING, FreeeIssue.DUPLICATE_COLUMN, FreeeIssue.COLUMN_COUNT_MISMATCH,
})  # VARIANT_AMBIGUOUS is not file level: the file is read as variant UNKNOWN and every journal blocks


@dataclass(frozen=True)
class FreeeHeader:
    columns: tuple[str, ...]
    variant: FreeeJournalVariant
    encoding: str  # "utf-8-sig" | "utf-8" | "cp932"
    fingerprint: str
    unknown_columns: tuple[str, ...]
    assumed_columns: tuple[str, ...]  # recognised only by symmetry / analogy (not seen in help text)

    @property
    def verified(self) -> bool:
        return self.fingerprint in VERIFIED_HEADER_FINGERPRINTS

    @property
    def source_format_key(self) -> str:
        return f"{SOURCE_FORMAT_PREFIX}:{self.variant.value}:{self.fingerprint[:16]}"


@dataclass(frozen=True)
class FreeeJournalIssue:
    code: FreeeIssue
    row_number: int | None = None
    journal_number: str | None = None
    column: str | None = None


@dataclass
class FreeeParseResult:
    header: FreeeHeader | None
    entries: tuple[JournalEntry, ...] = ()
    issues: tuple[FreeeJournalIssue, ...] = ()
    data_rows: int = 0
    rejected_journals: int = 0
    rejected_rows: int = 0
    _rejected_numbers: tuple[str, ...] = field(default=(), repr=False)

    @property
    def file_readable(self) -> bool:
        return self.header is not None and not any(i.code in FILE_LEVEL_ISSUES for i in self.issues)


def header_fingerprint(columns: tuple[str, ...]) -> str:
    return hashlib.sha256("\x1f".join(columns).encode("utf-8")).hexdigest()


def decode(raw: bytes) -> tuple[str, str] | None:
    """(text, encoding) using only the encodings freee documents (UTF-8 with/without BOM, Shift-JIS).

    UTF-16 (BOM) and NUL bytes are rejected: CP932 would otherwise "decode" them into garbage.
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        return None
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig", errors="strict"), "utf-8-sig"
        except UnicodeDecodeError:
            return None
    for encoding in ("utf-8", "cp932"):
        try:
            return raw.decode(encoding, errors="strict"), encoding
        except UnicodeDecodeError:
            continue
    return None


def classify_header(columns: tuple[str, ...]) -> FreeeJournalVariant | None:
    """NEW / OLD from documented marker columns; None when both sets of markers are present."""
    names = set(columns)
    new, old = bool(names & NEW_CSV_MARKERS), bool(names & OLD_CSV_MARKERS)
    if new and old:
        return None
    if new:
        return FreeeJournalVariant.NEW_CSV
    if old:
        return FreeeJournalVariant.OLD_CSV
    return FreeeJournalVariant.UNKNOWN


class FreeeJournalCsvParser:
    def parse_path(self, path: Path) -> FreeeParseResult:
        try:
            raw = path.read_bytes()
        except OSError:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.UNREADABLE),))
        return self.parse_bytes(raw, file_name=path.name)

    def parse_bytes(self, raw: bytes, file_name: str = "<memory>") -> FreeeParseResult:
        decoded = decode(raw)
        if decoded is None:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.ENCODING_UNKNOWN),))
        text, encoding = decoded
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.MALFORMED_CSV),))
        if not rows:
            return FreeeParseResult(None, issues=(FreeeJournalIssue(FreeeIssue.NO_DATA_ROWS),))
        columns = tuple(rows[0])
        issues: list[FreeeJournalIssue] = []
        duplicates = sorted({name for name in columns if columns.count(name) > 1})
        issues += [FreeeJournalIssue(FreeeIssue.DUPLICATE_COLUMN, 1, column=name) for name in duplicates]
        issues += [
            FreeeJournalIssue(FreeeIssue.REQUIRED_COLUMN_MISSING, 1, column=name)
            for name in REQUIRED_COLUMNS if name not in columns
        ]
        variant = classify_header(columns)
        if variant is None:
            issues.append(FreeeJournalIssue(FreeeIssue.VARIANT_AMBIGUOUS, 1))
            variant = FreeeJournalVariant.UNKNOWN
        header = FreeeHeader(
            columns=columns,
            variant=variant,
            encoding=encoding,
            fingerprint=header_fingerprint(columns),
            unknown_columns=tuple(name for name in columns if name not in COLUMN_ROLES),
            assumed_columns=tuple(
                name for name in columns
                if name in COLUMN_ROLES and COLUMN_ROLES[name].provenance is Provenance.SYMMETRIC_ASSUMPTION
            ),
        )
        data = rows[1:]
        if not data:
            issues.append(FreeeJournalIssue(FreeeIssue.NO_DATA_ROWS))
        issues += [
            FreeeJournalIssue(FreeeIssue.COLUMN_COUNT_MISMATCH, index)
            for index, row in enumerate(data, start=2) if len(row) != len(columns)
        ]
        if any(issue.code in FILE_LEVEL_ISSUES for issue in issues):
            return FreeeParseResult(header, issues=tuple(issues), data_rows=len(data))
        return self._parse_rows(header, data, file_name, issues)

    # ------------------------------------------------------------------ rows -> journals

    def _parse_rows(self, header, data, file_name, issues) -> FreeeParseResult:
        records = [(index, dict(zip(header.columns, row))) for index, row in enumerate(data, start=2)]
        groups: list[tuple[str, list[tuple[int, dict]]]] = []
        seen: set[str] = set()
        reused: set[str] = set()
        for row_number, record in records:
            number = record.get("No.", "").strip()
            if not number:
                issues.append(FreeeJournalIssue(FreeeIssue.JOURNAL_NUMBER_MISSING, row_number))
                groups.append(("", [(row_number, record)]))
                continue
            if groups and groups[-1][0] == number:
                groups[-1][1].append((row_number, record))
                continue
            if number in seen:
                reused.add(number)
            seen.add(number)
            groups.append((number, [(row_number, record)]))
        entries: list[JournalEntry] = []
        rejected: list[str] = []
        rejected_rows = 0
        for number, rows in groups:
            if not number:
                rejected_rows += len(rows)
                rejected.append("")
                continue
            if number in reused:
                issues.append(FreeeJournalIssue(FreeeIssue.JOURNAL_NUMBER_REUSED, rows[0][0], number))
                rejected_rows += len(rows)
                rejected.append(number)
                continue
            entry, journal_issues = self._entry(header, file_name, number, rows)
            issues += journal_issues
            if entry is None:
                rejected_rows += len(rows)
                rejected.append(number)
            else:
                entries.append(entry)
        return FreeeParseResult(
            header, tuple(entries), tuple(issues), data_rows=len(records),
            rejected_journals=len(rejected), rejected_rows=rejected_rows, _rejected_numbers=tuple(rejected),
        )

    def _entry(self, header: FreeeHeader, file_name: str, number: str, rows):
        issues: list[FreeeJournalIssue] = []
        dates = {record.get("取引日", "") for _, record in rows}
        if len(dates) != 1:
            return None, [FreeeJournalIssue(FreeeIssue.MULTIPLE_DATES, rows[0][0], number)]
        entry_date = _parse_date(next(iter(dates)))
        if entry_date is None:
            return None, [FreeeJournalIssue(FreeeIssue.DATE_FORMAT_UNVERIFIED, rows[0][0], number, "取引日")]
        lines: list[JournalLine] = []
        fields: list[SourceFieldValue] = []
        closing: list[str] = []
        for row_number, record in rows:
            description = record.get("摘要", "")
            row_lines = []
            for side in (Side.DEBIT, Side.CREDIT):
                line, problem = self._line(file_name, number, row_number, record, side, description)
                if problem is not None:
                    issues.append(problem)
                elif line is not None:
                    row_lines.append(line)
            if not row_lines and not any(issue.row_number == row_number for issue in issues):
                issues.append(FreeeJournalIssue(FreeeIssue.EMPTY_ROW, row_number, number))
            lines += row_lines
            for name in header.columns:
                value = record.get(name, "")
                if not value:
                    continue
                role = COLUMN_ROLES.get(name)
                if role is None:  # unknown column: kept verbatim, never interpreted
                    fields.append(SourceFieldValue(name, value, SourceFieldScope.ROW, row_number, known=False))
                elif role.role is Role.CLOSING:
                    closing.append(value)
                elif role.role in {Role.INFORMATION, Role.COUNTERPARTY}:
                    scope = SourceFieldScope(role.side.value) if role.side is not None else SourceFieldScope.ROW
                    fields.append(SourceFieldValue(name, value, scope, row_number))
                # other roles are carried by the common model (account, amount, tax, department, …)
        if issues:
            return None, issues
        entry = JournalEntry(
            id=f"freee:{file_name}:{number}",
            source_reference=SourceReference(file_name, rows[0][0], number),
            date=entry_date,
            lines=lines,
            description=_single({record.get("摘要", "") for _, record in rows}),
            metadata={
                "source": SOURCE_FORMAT_PREFIX,
                "evidence_level": "UNVERIFIED_PUBLIC_SPEC_FRAGMENTS",
                "production_registry_enabled": False,
                "freee_variant": header.variant.value,
                "freee_header_fingerprint": header.fingerprint,
                ENTRY_SOURCE_FORMAT_KEY: header.source_format_key,
                ENTRY_SOURCE_FIELDS_KEY: tuple(fields),
                **({ENTRY_CLOSING_ADJUSTMENT_KEY: "|".join(dict.fromkeys(closing))} if closing else {}),
                ROW_ORDER_KEY: tuple(row_number for row_number, _ in rows),
                JOURNAL_CONTENT_IDENTITY_KEY: journal_content_identity(
                    header.source_format_key,
                    entry_date.isoformat(),
                    tuple(
                        tuple(record.get(name, "") for name in header.columns if name != "No.")
                        for _, record in rows
                    ),
                ),
                "transaction_number_scope": "SOURCE_FILE_LOCAL",
            },
        )
        if not entry.is_balanced():
            return None, [FreeeJournalIssue(FreeeIssue.UNBALANCED, rows[0][0], number)]
        return entry, []

    @staticmethod
    def _line(file_name, number, row_number, record, side: Side, description: str):
        prefix = "借方" if side is Side.DEBIT else "貸方"
        account = record.get(f"{prefix}勘定科目", "")
        amount_text = record.get(f"{prefix}金額", "")
        details = [
            record.get(f"{prefix}{suffix}", "")
            for suffix, role, _p, _v in _SIDE_COLUMNS if role not in {Role.ACCOUNT, Role.AMOUNT}
        ]
        if not account and not amount_text:
            if any(details):
                return None, FreeeJournalIssue(FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT, row_number, number, prefix)
            return None, None
        if not account or not amount_text:
            return None, FreeeJournalIssue(FreeeIssue.SIDE_WITHOUT_ACCOUNT_OR_AMOUNT, row_number, number, prefix)
        amount = _parse_amount(amount_text)
        if amount is None:
            return None, FreeeJournalIssue(FreeeIssue.AMOUNT_FORMAT_UNVERIFIED, row_number, number, f"{prefix}金額")
        tax_category = record.get(f"{prefix}税区分", "")
        tax_amount_text = record.get(f"{prefix}税金額", "")
        tax_amount = None
        if tax_amount_text:
            tax_amount = _parse_amount(tax_amount_text)
            if tax_amount is None:
                return None, FreeeJournalIssue(
                    FreeeIssue.AMOUNT_FORMAT_UNVERIFIED, row_number, number, f"{prefix}税金額",
                )
        tax_info = None
        if tax_category or tax_amount_text:
            tax_info = TaxInfo(
                category=tax_category or None,
                tax_amount=tax_amount,
                # 税込/税抜・内税/外税 is not in any documented column: left unknown, never guessed.
                tax_inclusion=None,
                metadata={
                    "source_format": SOURCE_FORMAT_PREFIX,
                    "tax_amount_column_present": f"{prefix}税金額" in record,
                    "tax_inclusion_source": "NOT_IN_DOCUMENTED_COLUMNS",
                },
            )
        counterparty = record.get(f"{prefix}取引先名", "") or record.get(f"{prefix}取引先", "")
        return JournalLine(
            side=side,
            account=account,
            amount=amount,
            source_reference=SourceReference(file_name, row_number, number),
            sub_account=None,  # freee has no 補助科目 column in the documented export; never derived
            department=record.get(f"{prefix}部門", "") or None,
            tax_info=tax_info,
            metadata={
                LINE_ROW_KEY: row_number,
                LINE_ROW_DESCRIPTION_KEY: description,
                **({LINE_COUNTERPARTY_KEY: counterparty} if counterparty else {}),
                **(
                    {"freee_account_display_name": record[f"{prefix}決算書表示名"]}
                    if record.get(f"{prefix}決算書表示名") else {}
                ),
            },
        ), None


def _parse_date(value: str) -> date | None:
    match = _DATE.fullmatch(value)
    if match is None:
        return None
    try:
        return date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError:
        return None


def _parse_amount(value: str) -> Decimal | None:
    return Decimal(value) if _AMOUNT.fullmatch(value) else None


def _single(values: set[str]) -> str | None:
    values = {value for value in values if value}
    return next(iter(values)) if len(values) == 1 else None

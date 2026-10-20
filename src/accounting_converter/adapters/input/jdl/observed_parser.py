from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)


class JdlMigrationParseError(ValueError):
    pass


def jdl_source_account_key(code: str, name: str) -> str:
    return json.dumps(("JDL_ACCOUNT", code, name), ensure_ascii=False, separators=(",", ":"))


def jdl_source_subaccount_key(code: str, name: str) -> str:
    return json.dumps(("JDL_SUBACCOUNT", code, name), ensure_ascii=False, separators=(",", ":"))


def jdl_source_tax_key(scope: str, category: str, input_method: str) -> str:
    return json.dumps(
        ("JDL_TAX", scope, category, input_method),
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class JdlMigrationSourceMetadata:
    row_number: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class JdlMigrationParseResult:
    entries: tuple[JournalEntry, ...]
    journal_record_count: int
    diagnostic_rows: tuple[JdlMigrationSourceMetadata, ...]
    preamble_rows: tuple[JdlMigrationSourceMetadata, ...]
    encoding: str = "cp932"
    line_ending: str = "CRLF"
    has_bom: bool = False


@dataclass(frozen=True)
class _Row:
    row_number: int
    columns: tuple[str, ...]

    def value(self, position: int) -> str:
        return self.columns[position - 1].strip()


class JdlMigrationParser:
    """Strict JDL 30-column reader for an old-master migration source."""

    FLAGS = frozenset({"1000", "1111", "1110", "1100", "1101"})

    def __init__(self) -> None:
        self.spec = jdl_ibex_cashbook_official_journal_import_spec()

    def parse_path(self, path: Path) -> JdlMigrationParseResult:
        raw = path.read_bytes()
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            raise JdlMigrationParseError("JDL migration source must not contain a BOM")
        remainder = raw.replace(b"\r\n", b"")
        if b"\n" in remainder or b"\r" in remainder:
            raise JdlMigrationParseError("JDL migration source requires CRLF line endings")
        try:
            text = raw.decode("cp932", errors="strict")
        except UnicodeDecodeError as exc:
            raise JdlMigrationParseError(
                f"JDL migration source requires strict CP932 bytes: {exc.reason}"
            ) from exc
        return self.parse_text(text, file_name=path.name)

    def parse_text(
        self,
        text: str,
        *,
        file_name: str = "<memory>",
    ) -> JdlMigrationParseResult:
        rows = self._read_rows(text)
        header_indexes = [
            index
            for index, row in enumerate(rows)
            if row.columns == self.spec.column_names
        ]
        if len(header_indexes) != 1:
            raise JdlMigrationParseError(
                "JDL migration source requires exactly one exact 30-column header"
            )
        header_index = header_indexes[0]
        preamble = tuple(
            self._metadata_row(row, "preamble") for row in rows[:header_index]
        )
        records: list[_Row] = []
        diagnostics: list[JdlMigrationSourceMetadata] = []
        for row in rows[header_index + 1 :]:
            if len(row.columns) != self.spec.column_count:
                raise JdlMigrationParseError(
                    f"JDL row {row.row_number} has {len(row.columns)} columns; "
                    f"expected {self.spec.column_count}"
                )
            flag = row.value(1)
            if flag in self.FLAGS:
                records.append(row)
            elif flag.startswith("//") and all(not value for value in row.columns[1:]):
                diagnostics.append(
                    JdlMigrationSourceMetadata(row.row_number, row.columns)
                )
            else:
                raise JdlMigrationParseError(
                    f"JDL row {row.row_number} is neither a journal record nor "
                    "an observed diagnostic metadata row"
                )
        if not records:
            raise JdlMigrationParseError("JDL migration source contains no journal rows")
        groups = self._group(records)
        entries = tuple(self._entry(file_name, group) for group in groups)
        return JdlMigrationParseResult(
            entries=entries,
            journal_record_count=len(records),
            diagnostic_rows=tuple(diagnostics),
            preamble_rows=preamble,
        )

    def _read_rows(self, text: str) -> tuple[_Row, ...]:
        try:
            reader = csv.reader(StringIO(text, newline=""), strict=True)
            rows = tuple(_Row(reader.line_num, tuple(row)) for row in reader)
        except csv.Error as exc:
            raise JdlMigrationParseError(f"JDL CSV parse failed: {exc}") from exc
        if not rows:
            raise JdlMigrationParseError("JDL migration source is empty")
        return rows

    def _metadata_row(self, row: _Row, kind: str) -> JdlMigrationSourceMetadata:
        if len(row.columns) != self.spec.column_count:
            raise JdlMigrationParseError(
                f"JDL {kind} row {row.row_number} is not 30 columns"
            )
        if row.value(1) and not row.value(1).startswith("//"):
            raise JdlMigrationParseError(
                f"JDL {kind} row {row.row_number} has an unknown structure"
            )
        return JdlMigrationSourceMetadata(row.row_number, row.columns)

    def _group(self, records: list[_Row]) -> tuple[tuple[_Row, ...], ...]:
        groups: list[tuple[_Row, ...]] = []
        index = 0
        while index < len(records):
            row = records[index]
            flag = row.value(1)
            if flag in {"1000", "1111"}:
                groups.append((row,))
                index += 1
                continue
            if flag != "1110":
                raise JdlMigrationParseError(
                    f"JDL row {row.row_number} starts with an invalid group flag: {flag}"
                )
            group = [row]
            index += 1
            while index < len(records):
                current = records[index]
                current_flag = current.value(1)
                if current_flag == "1100":
                    group.append(current)
                    index += 1
                    continue
                if current_flag == "1101":
                    group.append(current)
                    index += 1
                    break
                raise JdlMigrationParseError(
                    f"JDL compound journal at row {row.row_number} has an invalid "
                    f"flag sequence at row {current.row_number}: {current_flag}"
                )
            else:
                raise JdlMigrationParseError(
                    f"JDL compound journal at row {row.row_number} is not closed"
                )
            groups.append(tuple(group))
        return tuple(groups)

    def _entry(self, file_name: str, rows: tuple[_Row, ...]) -> JournalEntry:
        first = rows[0]
        dates = {row.value(3) for row in rows}
        vouchers = {row.value(2) for row in rows}
        if len(dates) != 1 or "" in dates:
            raise JdlMigrationParseError(
                f"JDL journal at row {first.row_number} has inconsistent dates"
            )
        if len(vouchers) != 1:
            raise JdlMigrationParseError(
                f"JDL journal at row {first.row_number} has inconsistent voucher numbers"
            )
        try:
            journal_date = datetime.strptime(next(iter(dates)), "%Y%m%d").date()
        except ValueError as exc:
            raise JdlMigrationParseError(
                f"JDL journal at row {first.row_number} has an invalid date"
            ) from exc
        entry_id = f"jdl:{first.row_number}"
        source = SourceReference(file_name, first.row_number, entry_id)
        lines: list[JournalLine] = []
        row_metadata: list[dict[str, object]] = []
        for physical_index, row in enumerate(rows):
            debit = self._line(file_name, entry_id, row, Side.DEBIT, 4)
            credit = self._line(file_name, entry_id, row, Side.CREDIT, 14)
            debit_index = len(lines) if debit is not None else None
            if debit is not None:
                lines.append(debit)
            credit_index = len(lines) if credit is not None else None
            if credit is not None:
                lines.append(credit)
            if debit is None and credit is None:
                raise JdlMigrationParseError(
                    f"JDL row {row.row_number} has neither a debit nor credit line"
                )
            row_metadata.append(
                {
                    "source_row_number": row.row_number,
                    "physical_row_index": physical_index,
                    "identifier_flag": row.value(1),
                    "voucher_number": row.value(2),
                    "description": row.value(24),
                    "debit_line_index": debit_index,
                    "credit_line_index": credit_index,
                    "source_columns": row.columns,
                }
            )
        entry = JournalEntry(
            id=entry_id,
            source_reference=source,
            date=journal_date,
            lines=lines,
            description=(row_metadata[0]["description"] or None),
            metadata={
                "source": "jdl_30_column_migration_input",
                "input_adapter": "JdlMigrationInputAdapter",
                "identifier_flags": tuple(row.value(1) for row in rows),
                "physical_rows": tuple(row_metadata),
                "voucher_number": next(iter(vouchers)),
                "production_adapter": False,
                "formal_output_enabled": False,
            },
        )
        if not entry.is_balanced():
            raise JdlMigrationParseError(
                f"JDL journal at row {first.row_number} is not balanced"
            )
        return entry

    def _line(
        self,
        file_name: str,
        entry_id: str,
        row: _Row,
        side: Side,
        base: int,
    ) -> JournalLine | None:
        code = row.value(base)
        short_name = row.value(base + 1)
        formal_name = row.value(base + 2)
        account_side_values = tuple(row.value(base + offset) for offset in range(8))
        amount_raw = row.value(base + 8)
        tax_amount_raw = row.value(base + 9)
        if (
            not any(account_side_values)
            and amount_raw in {"", "0"}
            and tax_amount_raw in {"", "0"}
        ):
            return None
        amount = self._amount(amount_raw, row.row_number)
        tax_amount = self._amount(tax_amount_raw or "0", row.row_number)
        account_name = formal_name or short_name
        if not code or not account_name:
            raise JdlMigrationParseError(
                f"JDL row {row.row_number} has an incomplete {side.value} account identity"
            )
        sub_code = row.value(base + 3)
        sub_name = row.value(base + 4)
        if bool(sub_code) != bool(sub_name):
            raise JdlMigrationParseError(
                f"JDL row {row.row_number} has an incomplete {side.value} subaccount identity"
            )
        tax_scope = row.value(base + 5)
        tax_category = row.value(base + 6)
        tax_input_method = row.value(base + 7)
        tax_info = None
        if tax_scope or tax_category or tax_input_method or tax_amount:
            tax_info = TaxInfo(
                category=jdl_source_tax_key(
                    tax_scope, tax_category, tax_input_method
                ),
                tax_amount=tax_amount,
                metadata={
                    "jdl_tax_scope": tax_scope,
                    "jdl_tax_category": tax_category,
                    "jdl_tax_input_method": tax_input_method,
                    "jdl_tax_amount_raw": row.value(base + 9),
                },
            )
        source = SourceReference(file_name, row.row_number, entry_id)
        department_code = row.value(27 if side is Side.DEBIT else 29)
        department_name = row.value(28 if side is Side.DEBIT else 30)
        return JournalLine(
            side=side,
            account=jdl_source_account_key(code, account_name),
            sub_account=(
                jdl_source_subaccount_key(sub_code, sub_name)
                if sub_name
                else None
            ),
            department=department_name or None,
            amount=amount,
            tax_info=tax_info,
            source_reference=source,
            metadata={
                "jdl_source_account_code": code,
                "jdl_source_account_name": short_name,
                "jdl_source_account_formal_name": formal_name,
                "jdl_source_subaccount_code": sub_code,
                "jdl_source_subaccount_name": sub_name,
                "jdl_source_department_code": department_code,
                "jdl_source_department_name": department_name,
                "jdl_physical_row_number": row.row_number,
            },
        )

    @staticmethod
    def _amount(value: str, row_number: int) -> Decimal:
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise JdlMigrationParseError(
                f"JDL row {row_number} has an invalid amount"
            ) from exc
        if amount != amount.to_integral_value() or amount < 0:
            raise JdlMigrationParseError(
                f"JDL row {row_number} requires a non-negative integer amount"
            )
        return amount

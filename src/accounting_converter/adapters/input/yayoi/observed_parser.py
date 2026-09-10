from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
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
from accounting_converter.profiles.yayoi_official import (
    YayoiOfficialImportSpecification,
    yayoi_accounting_05_official_import_spec,
)


class YayoiObservedSingleRecordParserError(ValueError):
    pass


@dataclass(frozen=True)
class YayoiObservedSingleRecordRow:
    row_number: int
    columns: tuple[str, ...]

    def value(self, position: int) -> str:
        return self.columns[position - 1].strip()


class YayoiObservedSingleRecordParser:
    """Strict internal parser for narrow observed Yayoi AE19 rows.

    This is not a production YayoiInputAdapter. It exists to validate whether the
    current official + observed evidence can safely produce Common Journal Model
    objects for the narrow observed subset. The class name is retained for
    compatibility with earlier single-record-only diagnostics.
    """

    SUPPORTED_SINGLE_RECORD_FLAGS = frozenset({"2000", "2111"})

    def __init__(
        self,
        spec: YayoiOfficialImportSpecification | None = None,
    ) -> None:
        self.spec = spec or yayoi_accounting_05_official_import_spec()

    def parse_path(self, path: Path) -> tuple[JournalEntry, ...]:
        raw = path.read_bytes()
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as exc:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed parser requires cp932 bytes: {exc.reason}"
            ) from exc
        return self.parse_text(text, file_name=path.name)

    def record_count(self, path: Path) -> int:
        raw = path.read_bytes()
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as exc:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed parser requires cp932 bytes: {exc.reason}"
            ) from exc
        return len(self._read_rows(text))

    def parse_text(
        self,
        text: str,
        file_name: str = "<memory>",
    ) -> tuple[JournalEntry, ...]:
        rows = self._read_rows(text)
        entries: list[JournalEntry] = []
        for row in rows:
            self._validate_row(row)
        index = 0
        while index < len(rows):
            row = rows[index]
            flag = row.value(1)
            if flag in self.SUPPORTED_SINGLE_RECORD_FLAGS:
                entries.append(self._entry_from_rows(file_name, (row,)))
                index += 1
                continue
            if flag == "2110":
                group, index = self._read_observed_multi_record_group(rows, index)
                self._validate_observed_multi_record_group(group)
                entries.append(self._entry_from_rows(file_name, group))
                continue
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row.row_number} has unsupported "
                f"identifier flag: {flag or '(blank)'}"
            )
        return tuple(entries)

    def _read_rows(self, text: str) -> tuple[YayoiObservedSingleRecordRow, ...]:
        try:
            reader = csv.reader(StringIO(text), delimiter=",", strict=True)
            rows = tuple(
                YayoiObservedSingleRecordRow(
                    row_number=reader.line_num,
                    columns=tuple(row),
                )
                for row in reader
            )
        except csv.Error as exc:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed CSV parse failed: {exc}"
            ) from exc
        if not rows:
            raise YayoiObservedSingleRecordParserError(
                "Yayoi observed parser received no rows"
            )
        return rows

    def _validate_row(self, row: YayoiObservedSingleRecordRow) -> None:
        if len(row.columns) != self.spec.column_count:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row.row_number} has {len(row.columns)} "
                f"columns; expected {self.spec.column_count}"
            )
        if tuple(row.columns) == self.spec.column_names:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row.row_number} is a header row, not data"
            )
        flag = row.value(1)
        if (
            flag not in self.SUPPORTED_SINGLE_RECORD_FLAGS
            and flag not in {"2110", "2100", "2101"}
        ):
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row.row_number} has unsupported "
                f"identifier flag: {flag or '(blank)'}"
            )

    def _read_observed_multi_record_group(
        self,
        rows: tuple[YayoiObservedSingleRecordRow, ...],
        start_index: int,
    ) -> tuple[tuple[YayoiObservedSingleRecordRow, ...], int]:
        group = [rows[start_index]]
        index = start_index + 1
        while index < len(rows):
            row = rows[index]
            flag = row.value(1)
            group.append(row)
            index += 1
            if flag == "2101":
                return tuple(group), index
            if flag != "2100":
                raise YayoiObservedSingleRecordParserError(
                    f"Yayoi observed multi-record voucher starting at row "
                    f"{rows[start_index].row_number} has unexpected flag at "
                    f"row {row.row_number}: {flag or '(blank)'}"
                )
        raise YayoiObservedSingleRecordParserError(
            f"Yayoi observed multi-record voucher starting at row "
            f"{rows[start_index].row_number} is not closed by 2101"
        )

    def _validate_observed_multi_record_group(
        self,
        rows: tuple[YayoiObservedSingleRecordRow, ...],
    ) -> None:
        flags = tuple(row.value(1) for row in rows)
        if len(rows) < 2 or flags[0] != "2110" or flags[-1] != "2101":
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed multi-record voucher at row "
                f"{rows[0].row_number} has unsupported flag sequence: {flags}"
            )
        if any(flag != "2100" for flag in flags[1:-1]):
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed multi-record voucher at row "
                f"{rows[0].row_number} has unsupported middle flag sequence: {flags}"
            )
        vouchers = {row.value(self._position("伝票No.")) for row in rows}
        if len(vouchers) != 1 or "" in vouchers:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed multi-record voucher at row "
                f"{rows[0].row_number} has inconsistent voucher number"
            )
        dates = {row.value(self._position("取引日付")) for row in rows}
        if len(dates) != 1 or "" in dates:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed multi-record voucher at row "
                f"{rows[0].row_number} has inconsistent date"
            )

    def _entry_from_rows(
        self,
        file_name: str,
        rows: tuple[YayoiObservedSingleRecordRow, ...],
    ) -> JournalEntry:
        first = rows[0]
        entry_id = self._entry_id(first)
        source = SourceReference(
            file_name=file_name,
            row_number=first.row_number,
            source_journal_id=entry_id,
        )
        lines: list[JournalLine] = []
        for row in rows:
            lines.extend(self._lines_from_row(file_name, row))
        if not lines:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {first.row_number} produced no journal lines"
            )
        descriptions = tuple(
            dict.fromkeys(
                row.value(self._position("摘要"))
                for row in rows
                if row.value(self._position("摘要"))
            )
        )
        if len(descriptions) > 1:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed journal starting at row {first.row_number} "
                "has multiple distinct descriptions"
            )
        entry = JournalEntry(
            id=entry_id,
            source_reference=source,
            date=self._date(
                first.value(self._position("取引日付")),
                first.row_number,
            ),
            description=descriptions[0] if descriptions else None,
            lines=lines,
            metadata={
                "source": "yayoi_ae19_observed_internal_parser",
                "identifier_flags": tuple(row.value(1) for row in rows),
                "grouping_basis": (
                    "OBSERVED_MULTI_RECORD_SEQUENCE"
                    if len(rows) > 1
                    else "OBSERVED_SINGLE_RECORD"
                ),
                "evidence_level": "OBSERVED",
                "production_adapter": False,
            },
        )
        if not entry.is_balanced():
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed journal starting at row "
                f"{first.row_number} is not balanced"
            )
        return entry

    def _lines_from_row(
        self,
        file_name: str,
        row: YayoiObservedSingleRecordRow,
    ) -> list[JournalLine]:
        source = SourceReference(
            file_name=file_name,
            row_number=row.row_number,
            source_journal_id=self._entry_id(row),
        )
        lines: list[JournalLine] = []
        lines.extend(
            self._line_from_side(
                row=row,
                side=Side.DEBIT,
                source=source,
                account_position=self._position("借方勘定科目"),
                sub_account_position=self._position("借方補助科目"),
                department_position=self._position("借方部門"),
                tax_category_position=self._position("借方税区分"),
                amount_position=self._position("借方金額"),
                tax_amount_position=self._position("借方税金額"),
            )
        )
        lines.extend(
            self._line_from_side(
                row=row,
                side=Side.CREDIT,
                source=source,
                account_position=self._position("貸方勘定科目"),
                sub_account_position=self._position("貸方補助科目"),
                department_position=self._position("貸方部門"),
                tax_category_position=self._position("貸方税区分"),
                amount_position=self._position("貸方金額"),
                tax_amount_position=self._position("貸方税金額"),
            )
        )
        return lines

    def _line_from_side(
        self,
        row: YayoiObservedSingleRecordRow,
        side: Side,
        source: SourceReference,
        account_position: int,
        sub_account_position: int,
        department_position: int,
        tax_category_position: int,
        amount_position: int,
        tax_amount_position: int,
    ) -> list[JournalLine]:
        account = row.value(account_position)
        amount = self._required_amount(
            row.value(amount_position),
            row.row_number,
            f"{side.value}_amount",
        )
        tax_amount = self._optional_amount(
            row.value(tax_amount_position),
            row.row_number,
            f"{side.value}_tax_amount",
        )
        if not account and amount == Decimal("0"):
            if row.value(sub_account_position) or row.value(department_position):
                raise YayoiObservedSingleRecordParserError(
                    f"Yayoi observed row {row.row_number} has ambiguous "
                    f"{side.value} subaccount or department without account"
                )
            if tax_amount not in {None, Decimal("0")}:
                raise YayoiObservedSingleRecordParserError(
                    f"Yayoi observed row {row.row_number} has ambiguous "
                    f"{side.value} tax amount without account"
                )
            return []
        if not account:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row.row_number} has blank account on "
                f"{side.value}"
            )
        return [
            JournalLine(
                side=side,
                account=account,
                sub_account=row.value(sub_account_position) or None,
                department=row.value(department_position) or None,
                amount=amount,
                tax_info=TaxInfo(
                    category=row.value(tax_category_position) or None,
                    tax_amount=tax_amount,
                    metadata={"source": "yayoi_ae19_observed"},
                ),
                source_reference=source,
            )
        ]

    def _entry_id(self, row: YayoiObservedSingleRecordRow) -> str:
        voucher = row.value(self._position("伝票No."))
        return voucher or f"ROW-{row.row_number}"

    def _position(self, name: str) -> int:
        for column in self.spec.columns:
            if column.name == name:
                return column.position
        raise YayoiObservedSingleRecordParserError(
            f"Yayoi official documented column is not available: {name}"
        )

    def _date(self, value: str, row_number: int) -> date:
        if not value:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row_number} has blank date"
            )
        for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        if len(value) >= 3 and value[1] == ".":
            era = value[0]
            rest = value[2:]
            base_years = {"H": 1988, "R": 2018, "S": 1925}
            if era in base_years:
                try:
                    year_text, month_text, day_text = rest.split("/")
                    year = base_years[era] + int(year_text)
                    return date(year, int(month_text), int(day_text))
                except (ValueError, TypeError) as exc:
                    raise YayoiObservedSingleRecordParserError(
                        f"Yayoi observed row {row_number} has invalid era date"
                    ) from exc
        raise YayoiObservedSingleRecordParserError(
            f"Yayoi observed row {row_number} has unsupported date format"
        )

    def _required_amount(
        self,
        value: str,
        row_number: int,
        field: str,
    ) -> Decimal:
        if not value:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row_number} has blank {field}"
            )
        return self._decimal(value, row_number, field)

    def _optional_amount(
        self,
        value: str,
        row_number: int,
        field: str,
    ) -> Decimal | None:
        if not value:
            return None
        return self._decimal(value, row_number, field)

    def _decimal(self, value: str, row_number: int, field: str) -> Decimal:
        try:
            return Decimal(value.replace(",", ""))
        except InvalidOperation as exc:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi observed row {row_number} has invalid {field}"
            ) from exc

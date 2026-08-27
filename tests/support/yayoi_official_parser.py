from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
)


@dataclass(frozen=True)
class YayoiOfficialRow:
    row_number: int
    columns: tuple[str, ...]

    def value(self, position: int) -> str:
        return self.columns[position - 1].strip()


class YayoiOfficialImportTestParser:
    def __init__(self, spec: YayoiOfficialImportSpecification) -> None:
        self.spec = spec

    def parse_path(self, path: Path) -> tuple[JournalEntry, ...]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return self.parse_text(handle.read(), file_name=path.name)

    def parse_text(
        self,
        text: str,
        file_name: str = "<memory>",
    ) -> tuple[JournalEntry, ...]:
        rows = tuple(
            YayoiOfficialRow(row_number=index, columns=tuple(row))
            for index, row in enumerate(csv.reader(text.splitlines()), start=1)
            if row
        )
        for row in rows:
            self._validate_row_width(row)
        entries: list[JournalEntry] = []
        index = 0
        while index < len(rows):
            flag = rows[index].value(1)
            if flag in {"2000", "2111"}:
                entries.append(self._entry_from_rows(file_name, (rows[index],)))
                index += 1
                continue
            if flag == "2110":
                start = index
                group = [rows[index]]
                index += 1
                while index < len(rows):
                    next_flag = rows[index].value(1)
                    group.append(rows[index])
                    index += 1
                    if next_flag == "2101":
                        break
                    if next_flag != "2100":
                        raise ValueError(
                            f"Unexpected Yayoi voucher flag at row {rows[index - 1].row_number}: {next_flag}"
                        )
                if group[-1].value(1) != "2101":
                    raise ValueError(
                        f"Yayoi multi-line voucher starting at row {rows[start].row_number} is not closed"
                    )
                entries.append(self._entry_from_rows(file_name, tuple(group)))
                continue
            raise ValueError(
                f"Unknown Yayoi identifier flag at row {rows[index].row_number}: {flag}"
            )
        return tuple(entries)

    def _entry_from_rows(
        self,
        file_name: str,
        rows: tuple[YayoiOfficialRow, ...],
    ) -> JournalEntry:
        first = rows[0]
        lines: list[JournalLine] = []
        for row in rows:
            lines.extend(self._journal_lines_from_row(file_name, row))
        if not lines:
            raise ValueError(f"Yayoi row {first.row_number} produced no journal lines")
        return JournalEntry(
            id=self._entry_id(first),
            source_reference=SourceReference(
                file_name=file_name,
                row_number=first.row_number,
                source_journal_id=self._entry_id(first),
            ),
            date=datetime.strptime(first.value(4), "%Y/%m/%d").date(),
            description=first.value(17) or None,
            lines=lines,
            metadata={
                "source": "yayoi_official_documented_test_parser",
                "identifier_flags": tuple(row.value(1) for row in rows),
                "real_data_verification": "pending",
            },
        )

    def _journal_lines_from_row(
        self,
        file_name: str,
        row: YayoiOfficialRow,
    ) -> list[JournalLine]:
        source = SourceReference(
            file_name=file_name,
            row_number=row.row_number,
            source_journal_id=self._entry_id(row),
        )
        lines: list[JournalLine] = []
        lines.extend(
            self._line_from_side(
                side=Side.DEBIT,
                row=row,
                source=source,
                account_position=5,
                sub_account_position=6,
                department_position=7,
                tax_category_position=8,
                amount_position=9,
                tax_amount_position=10,
            )
        )
        lines.extend(
            self._line_from_side(
                side=Side.CREDIT,
                row=row,
                source=source,
                account_position=11,
                sub_account_position=12,
                department_position=13,
                tax_category_position=14,
                amount_position=15,
                tax_amount_position=16,
            )
        )
        return lines

    def _line_from_side(
        self,
        side: Side,
        row: YayoiOfficialRow,
        source: SourceReference,
        account_position: int,
        sub_account_position: int,
        department_position: int,
        tax_category_position: int,
        amount_position: int,
        tax_amount_position: int,
    ) -> list[JournalLine]:
        account = row.value(account_position)
        amount = self._amount(row.value(amount_position))
        if account == "" and amount == Decimal("0"):
            return []
        if account == "":
            raise ValueError(
                f"Yayoi row {row.row_number} has amount without account on {side.value}"
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
                    tax_amount=self._optional_amount(row.value(tax_amount_position)),
                    metadata={"source": "yayoi_official_documented"},
                ),
                source_reference=source,
            )
        ]

    def _validate_row_width(self, row: YayoiOfficialRow) -> None:
        if len(row.columns) != self.spec.column_count:
            raise ValueError(
                f"Yayoi official import row {row.row_number} has {len(row.columns)} columns; "
                f"expected {self.spec.column_count}"
            )

    def _entry_id(self, row: YayoiOfficialRow) -> str:
        voucher = row.value(2)
        if voucher:
            return voucher
        return f"ROW-{row.row_number}"

    def _amount(self, value: str) -> Decimal:
        if value == "":
            return Decimal("0")
        return Decimal(value.replace(",", ""))

    def _optional_amount(self, value: str) -> Decimal | None:
        if value == "":
            return None
        return self._amount(value)

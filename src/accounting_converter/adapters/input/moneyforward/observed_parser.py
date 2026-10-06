from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.profiles.known_formats import MONEYFORWARD_JOURNAL_EXPORT_HEADER


MONEYFORWARD_OBSERVED_HEADER = MONEYFORWARD_JOURNAL_EXPORT_HEADER
EVIDENCE_ID = "EVID-MF-JOURNAL-EXPORT-OBSERVED-001"
_INTEGER_PATTERN = re.compile(r"[0-9]+")


class MoneyForwardObservedParserError(ValueError):
    pass


@dataclass(frozen=True)
class MoneyForwardObservedRow:
    row_number: int
    values: tuple[str, ...]

    @property
    def transaction_number(self) -> str:
        return self.values[0]

    @property
    def date_value(self) -> str:
        return self.values[1]


class MoneyForwardObservedParser:
    def parse_path(self, path: Path) -> list[JournalEntry]:
        rows = self._read_rows(path)
        return [self._build_entry(path, group) for group in self._group_rows(rows)]

    def record_count(self, path: Path) -> int:
        return len(self._read_rows(path))

    def _read_rows(self, path: Path) -> list[MoneyForwardObservedRow]:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MoneyForwardObservedParserError("Money Forward CSV could not be read") from exc
        if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            raise MoneyForwardObservedParserError("BOM is not supported by the observed format")
        if b"\r" in raw or (raw and not raw.endswith(b"\n")):
            raise MoneyForwardObservedParserError(
                "observed Money Forward CSV requires LF line endings and a final LF"
            )
        try:
            text = raw.decode("cp932", errors="strict")
        except UnicodeDecodeError as exc:
            raise MoneyForwardObservedParserError("CSV is not strict CP932") from exc
        if text.encode("cp932", errors="strict") != raw:
            raise MoneyForwardObservedParserError("CP932 round-trip mismatch")

        try:
            parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as exc:
            raise MoneyForwardObservedParserError("malformed CSV") from exc
        if not parsed or tuple(parsed[0]) != MONEYFORWARD_OBSERVED_HEADER:
            raise MoneyForwardObservedParserError("exact observed 19-column header is required")
        if len(parsed) == 1:
            raise MoneyForwardObservedParserError("CSV has no data rows")
        if any(len(row) != 19 for row in parsed):
            raise MoneyForwardObservedParserError("every header and data row must have 19 columns")
        if any("\n" in value or "\r" in value for row in parsed for value in row):
            raise MoneyForwardObservedParserError(
                "raw multiline fields are outside the observed v0 scope"
            )
        self._validate_quote_all_serialization(text, parsed)
        return [
            MoneyForwardObservedRow(row_number=index, values=tuple(row))
            for index, row in enumerate(parsed[1:], start=2)
        ]

    @staticmethod
    def _validate_quote_all_serialization(original: str, rows: list[list[str]]) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerows(rows)
        if output.getvalue() != original:
            raise MoneyForwardObservedParserError(
                "observed identity requires every field to use canonical CSV quoting"
            )

    @staticmethod
    def _group_rows(
        rows: list[MoneyForwardObservedRow],
    ) -> list[list[MoneyForwardObservedRow]]:
        groups: list[list[MoneyForwardObservedRow]] = []
        seen: set[str] = set()
        for row in rows:
            transaction_number = row.transaction_number
            if not transaction_number:
                raise MoneyForwardObservedParserError("transaction number is required")
            if groups and groups[-1][0].transaction_number == transaction_number:
                groups[-1].append(row)
                continue
            if transaction_number in seen:
                raise MoneyForwardObservedParserError(
                    "non-consecutive transaction number reuse is unsupported"
                )
            seen.add(transaction_number)
            groups.append([row])
        return groups

    def _build_entry(
        self,
        path: Path,
        rows: list[MoneyForwardObservedRow],
    ) -> JournalEntry:
        transaction_number = rows[0].transaction_number
        date_values = {row.date_value for row in rows}
        if len(date_values) != 1:
            raise MoneyForwardObservedParserError("group contains multiple transaction dates")
        entry_date = self._parse_date(rows[0].date_value)
        descriptions = {row.values[16] for row in rows if row.values[16]}
        if len(descriptions) > 1:
            raise MoneyForwardObservedParserError("group contains conflicting descriptions")

        lines: list[JournalLine] = []
        for row in rows:
            debit = self._build_line(path, row, Side.DEBIT)
            credit = self._build_line(path, row, Side.CREDIT)
            if debit is None and credit is None:
                raise MoneyForwardObservedParserError("physical row has no debit or credit line")
            if debit is not None:
                lines.append(debit)
            if credit is not None:
                lines.append(credit)

        source = SourceReference(
            file_name=path.name,
            row_number=rows[0].row_number,
            source_journal_id=transaction_number,
        )
        entry = JournalEntry(
            id=f"moneyforward:{path.name}:{transaction_number}",
            source_reference=source,
            date=entry_date,
            lines=lines,
            description=next(iter(descriptions), None),
            metadata={
                "source": "moneyforward_cloud_journal_export_observed",
                "evidence_id": EVIDENCE_ID,
                "evidence_level": "OBSERVED",
                "grouping_basis": "CONSECUTIVE_SOURCE_LOCAL_TRANSACTION_NUMBER",
                "physical_row_numbers": tuple(row.row_number for row in rows),
                "moneyforward_tags": tuple(
                    {"row_number": row.row_number, "value": row.values[17]}
                    for row in rows if row.values[17]
                ),
                "moneyforward_memos": tuple(
                    {"row_number": row.row_number, "value": row.values[18]}
                    for row in rows if row.values[18]
                ),
                "transaction_number_scope": "SOURCE_FILE_LOCAL",
                "production_registry_enabled": False,
            },
        )
        if not entry.is_balanced():
            raise MoneyForwardObservedParserError("journal group is not balanced")
        return entry

    def _build_line(
        self,
        path: Path,
        row: MoneyForwardObservedRow,
        side: Side,
    ) -> JournalLine | None:
        if side is Side.DEBIT:
            account, sub_account, department, partner, tax, invoice, amount = row.values[2:9]
        else:
            account, sub_account, department, partner, tax, invoice, amount = row.values[9:16]
        side_details = (sub_account, department, partner, tax, invoice)
        if not account and not amount:
            if any(side_details):
                raise MoneyForwardObservedParserError(
                    "side metadata exists without an account and amount"
                )
            return None
        if not account or not amount:
            raise MoneyForwardObservedParserError("account and amount must be populated together")

        tax_info = None
        if tax or invoice:
            tax_info = TaxInfo(
                category=tax or None,
                invoice_classification=invoice or None,
                metadata={"source_format": "moneyforward_journal_export"},
            )
        return JournalLine(
            side=side,
            account=account,
            amount=self._parse_amount(amount),
            source_reference=SourceReference(
                file_name=path.name,
                row_number=row.row_number,
                source_journal_id=row.transaction_number,
            ),
            sub_account=sub_account or None,
            department=department or None,
            tax_info=tax_info,
            metadata=({"moneyforward_trade_partner": partner} if partner else {}),
        )

    @staticmethod
    def _parse_date(value: str):
        try:
            parsed = datetime.strptime(value, "%Y/%m/%d")
        except ValueError as exc:
            raise MoneyForwardObservedParserError("invalid YYYY/MM/DD date") from exc
        if parsed.strftime("%Y/%m/%d") != value:
            raise MoneyForwardObservedParserError("date is not canonical YYYY/MM/DD")
        return parsed.date()

    @staticmethod
    def _parse_amount(value: str) -> Decimal:
        if not _INTEGER_PATTERN.fullmatch(value):
            raise MoneyForwardObservedParserError("amount must be an integer yen value")
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise MoneyForwardObservedParserError("invalid amount") from exc
        if amount <= 0:
            raise MoneyForwardObservedParserError(
                "zero or negative amounts are outside the observed v0 scope"
            )
        return amount

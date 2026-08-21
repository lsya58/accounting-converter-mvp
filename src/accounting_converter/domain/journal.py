from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any


class Side(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


@dataclass(frozen=True)
class SourceReference:
    file_name: str
    row_number: int | None = None
    source_journal_id: str | None = None


@dataclass(frozen=True)
class TaxInfo:
    category: str | None = None
    rate: Decimal | None = None
    tax_inclusion: str | None = None
    reduced_rate: bool | None = None
    invoice_classification: str | None = None
    tax_amount: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JournalLine:
    side: Side
    account: str | None
    amount: Decimal
    source_reference: SourceReference
    sub_account: str | None = None
    department: str | None = None
    tax_info: TaxInfo | None = None


@dataclass
class JournalEntry:
    id: str
    source_reference: SourceReference
    date: date
    lines: list[JournalLine]
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def debit_total(self) -> Decimal:
        return sum(
            (line.amount for line in self.lines if line.side is Side.DEBIT),
            Decimal("0"),
        )

    def credit_total(self) -> Decimal:
        return sum(
            (line.amount for line in self.lines if line.side is Side.CREDIT),
            Decimal("0"),
        )

    def is_balanced(self) -> bool:
        return self.debit_total() == self.credit_total()

    def is_compound(self) -> bool:
        debit_lines = sum(1 for line in self.lines if line.side is Side.DEBIT)
        credit_lines = sum(1 for line in self.lines if line.side is Side.CREDIT)
        return debit_lines > 1 or credit_lines > 1

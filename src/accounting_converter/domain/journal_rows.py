"""Source-neutral physical-row semantics of a journal.

A target such as JDL writes one CSV row per physical row, each with its own
debit side, credit side and description. Every source adapter fills these keys
(after its own source-specific transforms); targets read them through
`journal_physical_rows` and never through source-specific metadata.

- line.metadata[LINE_ROW_KEY]: int, physical row the line belongs to
- line.metadata[LINE_ROW_DESCRIPTION_KEY]: str, description of that row
- line.metadata[LINE_COUNTERPARTY_KEY]: str, counterparty (取引先) if the
  source carried one; targets need to know it exists, not where it came from
- entry.metadata[ROW_ORDER_KEY]: tuple[int, ...], the rows in output order
"""
from __future__ import annotations

from dataclasses import dataclass

from .journal import JournalEntry, JournalLine, Side

LINE_ROW_KEY = "journal_row_number"
LINE_ROW_DESCRIPTION_KEY = "journal_row_description"
LINE_COUNTERPARTY_KEY = "journal_counterparty"
ROW_ORDER_KEY = "physical_row_numbers"


@dataclass(frozen=True)
class PhysicalRow:
    row_number: int
    debit: JournalLine | None
    credit: JournalLine | None
    description: str


def journal_physical_rows(entry: JournalEntry) -> tuple[PhysicalRow, ...] | None:
    """Rows in order, or None when the row semantics are missing or inconsistent."""
    grouped: dict[int, dict[Side, JournalLine]] = {}
    descriptions: dict[int, str] = {}
    for line in entry.lines:
        row_number = line.metadata.get(LINE_ROW_KEY)
        description = line.metadata.get(LINE_ROW_DESCRIPTION_KEY)
        if not isinstance(row_number, int) or not isinstance(description, str):
            return None
        if row_number in descriptions and descriptions[row_number] != description:
            return None
        descriptions[row_number] = description
        sides = grouped.setdefault(row_number, {})
        if line.side in sides:
            return None
        sides[line.side] = line
    row_numbers = sorted(grouped)
    if tuple(row_numbers) != tuple(entry.metadata.get(ROW_ORDER_KEY, ())):
        return None
    return tuple(
        PhysicalRow(
            row_number=number,
            debit=grouped[number].get(Side.DEBIT),
            credit=grouped[number].get(Side.CREDIT),
            description=descriptions[number],
        )
        for number in row_numbers
    )


def physical_row_shape(rows: tuple[PhysicalRow, ...]) -> tuple[int, int, int]:
    """(debit lines, credit lines, physical rows)."""
    return (
        sum(row.debit is not None for row in rows),
        sum(row.credit is not None for row in rows),
        len(rows),
    )


def has_counterparty(entry: JournalEntry) -> bool:
    return any(bool(line.metadata.get(LINE_COUNTERPARTY_KEY)) for line in entry.lines)

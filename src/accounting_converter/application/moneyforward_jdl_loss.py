from __future__ import annotations

from dataclasses import dataclass

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side


VERIFIED_DESCRIPTION_SHAPES = frozenset(
    {
        (1, 3, 3),
        (2, 2, 2),
        (2, 1, 2),
        (2, 3, 3),
        (4, 6, 6),
        (5, 7, 7),
        (5, 8, 8),
    }
)


@dataclass(frozen=True)
class MoneyForwardPhysicalRow:
    row_number: int
    debit: JournalLine | None
    credit: JournalLine | None
    description: str
from accounting_converter.domain.validation import Severity, ValidationResult


class MoneyForwardToJdlLossRule:
    """Blocks observed MF fields that JDL output v0 cannot preserve."""

    rule_id = "MF-JDL-LOSS"

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        fields: set[str] = set()
        if entry.metadata.get("moneyforward_tags"):
            fields.add("tag")
        if entry.metadata.get("moneyforward_memos"):
            fields.add("memo")
        descriptions = {
            item["value"]
            for item in entry.metadata.get("moneyforward_descriptions", ())
            if item.get("value")
        }
        if len(descriptions) > 1 and moneyforward_verified_description_rows(entry) is None:
            fields.add("description")

        for line in entry.lines:
            if line.metadata.get("moneyforward_trade_partner"):
                fields.add("trade_partner")
            if line.tax_info and line.tax_info.invoice_classification:
                fields.add("invoice_classification")

        return [self._error(entry, field) for field in sorted(fields)]

    def _error(self, entry: JournalEntry, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=f"{self.rule_id}-{field.upper()}",
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field=field,
            message=(
                "Money Forward入力にJDL Output v0で保持できない項目があります。"
            ),
            suggested_action=(
                "値を破棄せず、明示的なloss policyまたはtarget表現を確認してください。"
            ),
        )


def moneyforward_1d3c_row_descriptions(
    entry: JournalEntry,
) -> tuple[str, str, str] | None:
    """Return source-row descriptions only for the verified MF 1D3C shape."""

    rows = moneyforward_verified_description_rows(entry)
    if rows is None or len(rows) != 3:
        return None
    if (sum(row.debit is not None for row in rows), sum(row.credit is not None for row in rows)) != (1, 3):
        return None
    return rows[0].description, rows[1].description, rows[2].description


def moneyforward_verified_description_rows(
    entry: JournalEntry,
) -> tuple[MoneyForwardPhysicalRow, ...] | None:
    grouped: dict[int, dict[Side, JournalLine]] = {}
    descriptions: dict[int, str] = {}
    for line in entry.lines:
        row_number = line.metadata.get("moneyforward_source_row_number")
        description = line.metadata.get("moneyforward_description")
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
    if tuple(row_numbers) != tuple(entry.metadata.get("physical_row_numbers", ())):
        return None
    observed = tuple(
        (item.get("row_number"), item.get("value"))
        for item in entry.metadata.get("moneyforward_descriptions", ())
    )
    expected = tuple(
        (row_number, descriptions[row_number])
        for row_number in row_numbers
        if descriptions[row_number]
    )
    if observed != expected:
        return None
    shape = (
        sum(Side.DEBIT in grouped[number] for number in row_numbers),
        sum(Side.CREDIT in grouped[number] for number in row_numbers),
        len(row_numbers),
    )
    if shape not in VERIFIED_DESCRIPTION_SHAPES:
        return None
    return tuple(
        MoneyForwardPhysicalRow(
            row_number=number,
            debit=grouped[number].get(Side.DEBIT),
            credit=grouped[number].get(Side.CREDIT),
            description=descriptions[number],
        )
        for number in row_numbers
    )

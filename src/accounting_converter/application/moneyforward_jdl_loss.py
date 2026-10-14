from __future__ import annotations

from accounting_converter.domain.journal import JournalEntry, Side
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
        if len(descriptions) > 1 and moneyforward_1d3c_row_descriptions(entry) is None:
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

    debit = [line for line in entry.lines if line.side is Side.DEBIT]
    credit = [line for line in entry.lines if line.side is Side.CREDIT]
    if len(debit) != 1 or len(credit) != 3 or len(entry.lines) != 4:
        return None

    row_numbers: list[int] = []
    descriptions: list[str] = []
    for line in credit:
        row_number = line.metadata.get("moneyforward_source_row_number")
        description = line.metadata.get("moneyforward_description")
        if not isinstance(row_number, int) or not isinstance(description, str):
            return None
        row_numbers.append(row_number)
        descriptions.append(description)
    if row_numbers != sorted(row_numbers) or len(set(row_numbers)) != 3:
        return None

    observed = tuple(
        (item.get("row_number"), item.get("value"))
        for item in entry.metadata.get("moneyforward_descriptions", ())
    )
    expected = tuple(
        (row_number, description)
        for row_number, description in zip(row_numbers, descriptions, strict=True)
        if description
    )
    if observed != expected:
        return None
    return descriptions[0], descriptions[1], descriptions[2]

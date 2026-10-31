from __future__ import annotations

import hashlib
from dataclasses import dataclass

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side
from accounting_converter.domain.conversion_profile import (
    LossPolicy,
    TRADE_PARTNER_TRANSFORMATION_KEY,
)


VERIFIED_DESCRIPTION_SHAPES = frozenset(
    {
        (1, 3, 3),
        (1, 2, 2),
        (2, 2, 2),
        (2, 1, 2),
        (2, 3, 3),
        (4, 6, 6),
        (4, 6, 10),
        (5, 7, 7),
        (5, 7, 12),
        (5, 8, 8),
        (5, 8, 13),
        (10, 9, 10),  # 0877 10D9C row descriptions, strict PASS
    }
)


@dataclass(frozen=True)
class MoneyForwardPhysicalRow:
    row_number: int
    debit: JournalLine | None
    credit: JournalLine | None
    description: str
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.application.moneyforward_description_replacement import (
    description_requires_replacement,
    unsafe_description_positions,
)


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
        if any(
            description_requires_replacement(value)
            for value in (*descriptions, entry.description or "")
        ):
            fields.add("description_character")

        for line in entry.lines:
            if (
                line.metadata.get("moneyforward_trade_partner")
                and not self._has_confirmed_trade_partner_transformation(entry)
            ):
                fields.add("trade_partner")
            if line.tax_info and line.tax_info.invoice_classification:
                fields.add("invoice_classification")

        return [self._error(entry, field) for field in sorted(fields)]

    @staticmethod
    def _has_confirmed_trade_partner_transformation(entry: JournalEntry) -> bool:
        marker = entry.metadata.get(TRADE_PARTNER_TRANSFORMATION_KEY)
        return bool(
            isinstance(marker, dict)
            and marker.get("policy")
            == LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value
            and marker.get("target_description_sha256")
            == hashlib.sha256((entry.description or "").encode("utf-8")).hexdigest()
        )

    def _error(self, entry: JournalEntry, field: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=f"{self.rule_id}-{field.upper()}",
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field=field,
            message=(
                "摘要にJDLで保持できない文字、または32文字を超える摘要があります。"
                if field == "description_character"
                else "Money Forward入力にJDL Output v0で保持できない項目があります。"
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
    *,
    additional_shapes: frozenset[tuple[int, int, int]] = frozenset(),
) -> tuple[MoneyForwardPhysicalRow, ...] | None:
    """Physical rows with per-row descriptions for a verified shape.

    additional_shapes is only for NOT_FOR_PRODUCTION probe generation.
    """
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
    if shape not in VERIFIED_DESCRIPTION_SHAPES | additional_shapes:
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

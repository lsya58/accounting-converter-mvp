from __future__ import annotations

import hashlib

from accounting_converter.adapters.output.jdl.row_evidence import (
    JDL_ROW_DESCRIPTION_VERIFIED_SHAPES,
    jdl_row_description_rows,
)
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side
from accounting_converter.domain.journal_rows import PhysicalRow
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.application.moneyforward_description_replacement import (
    description_requires_replacement,
    unsafe_description_positions,
)
from accounting_converter.domain.conversion_profile import (
    LossPolicy,
    TRADE_PARTNER_TRANSFORMATION_KEY,
)


# Re-exported for older imports; the Evidence itself belongs to the JDL target.
VERIFIED_DESCRIPTION_SHAPES = JDL_ROW_DESCRIPTION_VERIFIED_SHAPES
MoneyForwardPhysicalRow = PhysicalRow


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
) -> tuple[PhysicalRow, ...] | None:
    """MF route: JDL-verified rows plus an MF-only integrity check.

    The MF parser also records the observed per-row descriptions; after the MF
    transforms they must still match the row semantics the target will write.
    """
    rows = jdl_row_description_rows(entry, additional_shapes=additional_shapes)
    if rows is None:
        return None
    observed = tuple(
        (item.get("row_number"), item.get("value"))
        for item in entry.metadata.get("moneyforward_descriptions", ())
    )
    expected = tuple(
        (row.row_number, row.description) for row in rows if row.description
    )
    if observed != expected:
        return None
    return rows

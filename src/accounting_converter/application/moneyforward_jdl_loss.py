from __future__ import annotations

from accounting_converter.domain.journal import JournalEntry
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

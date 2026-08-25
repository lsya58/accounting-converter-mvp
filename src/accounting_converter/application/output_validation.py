from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol, Sequence

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult


@dataclass(frozen=True)
class OutputValidationResult:
    success: bool
    record_count: int
    journal_count: int
    debit_total: Decimal
    credit_total: Decimal
    validation_results: tuple[ValidationResult, ...] = ()

    @classmethod
    def failed(cls, results: Sequence[ValidationResult]) -> OutputValidationResult:
        return cls(
            success=False,
            record_count=0,
            journal_count=0,
            debit_total=Decimal("0"),
            credit_total=Decimal("0"),
            validation_results=tuple(results),
        )


class OutputValidator(Protocol):
    def validate(
        self,
        path: Path,
        expected_entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> OutputValidationResult:
        ...


def output_validation_error(
    rule_id: str,
    message: str,
    field: str,
    input_value: object,
) -> ValidationResult:
    return ValidationResult(
        severity=Severity.ERROR,
        rule_id=rule_id,
        message=message,
        field=field,
        input_value=input_value,
        suggested_action="出力Adapterまたは出力形式検証を確認してください。",
    )

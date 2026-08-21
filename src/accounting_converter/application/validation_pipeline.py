from collections.abc import Iterable

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.validation import (
    JournalValidationRule,
    Severity,
    ValidationResult,
)


class ValidationPipeline:
    def __init__(self, rules: Iterable[JournalValidationRule]) -> None:
        self._rules = tuple(rules)

    def validate(self, entries: Iterable[JournalEntry]) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        for entry in entries:
            for rule in self._rules:
                results.extend(rule.validate(entry))
        return results

    @staticmethod
    def can_export(results: Iterable[ValidationResult]) -> bool:
        return all(
            result.severity not in {Severity.ERROR, Severity.FATAL}
            for result in results
        )

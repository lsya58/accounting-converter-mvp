from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .journal import JournalEntry, SourceReference


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


@dataclass(frozen=True)
class ValidationResult:
    severity: Severity
    rule_id: str
    message: str
    journal_id: str | None = None
    source_reference: SourceReference | None = None
    field: str | None = None
    input_value: Any = None
    suggested_action: str | None = None


class JournalValidationRule(Protocol):
    rule_id: str

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        ...


class BalanceRule:
    rule_id = "VR-04"

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        if entry.is_balanced():
            return []
        return [
            ValidationResult(
                severity=Severity.ERROR,
                rule_id=self.rule_id,
                journal_id=entry.id,
                source_reference=entry.source_reference,
                field="amount",
                input_value={
                    "debit_total": str(entry.debit_total()),
                    "credit_total": str(entry.credit_total()),
                },
                message="借方合計と貸方合計が一致しません。",
            )
        ]


class UnsupportedCompoundStructureRule:
    rule_id = "VR-15"

    def __init__(self, compound_supported: bool) -> None:
        self.compound_supported = compound_supported

    def validate(self, entry: JournalEntry) -> list[ValidationResult]:
        if self.compound_supported or not entry.is_compound():
            return []
        return [
            ValidationResult(
                severity=Severity.ERROR,
                rule_id=self.rule_id,
                journal_id=entry.id,
                source_reference=entry.source_reference,
                field="journal_structure",
                input_value="compound",
                message="MVPで未対応の複合仕訳構造を検出しました。",
                suggested_action="複合仕訳対応方針を確認してください。",
            )
        ]

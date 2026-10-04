from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.validation import ValidationResult


@dataclass(frozen=True)
class JournalRouteResult:
    entries: tuple[JournalEntry, ...]
    validation_results: tuple[ValidationResult, ...] = ()


class JournalRoutePolicy(Protocol):
    def apply(self, entries: Sequence[JournalEntry]) -> JournalRouteResult:
        ...

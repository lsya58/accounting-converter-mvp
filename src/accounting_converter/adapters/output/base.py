from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import ValidationResult


class OutputAdapter(ABC):
    def preflight(
        self,
        entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> list[ValidationResult]:
        _ = entries, profile
        return []

    @abstractmethod
    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        raise NotImplementedError

from abc import ABC, abstractmethod
from pathlib import Path

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile


class InputAdapter(ABC):
    @abstractmethod
    def supports(self, path: Path, profile: FormatProfile) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        raise NotImplementedError

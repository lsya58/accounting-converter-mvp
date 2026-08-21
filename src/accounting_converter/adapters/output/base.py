from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile


class OutputAdapter(ABC):
    @abstractmethod
    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        raise NotImplementedError

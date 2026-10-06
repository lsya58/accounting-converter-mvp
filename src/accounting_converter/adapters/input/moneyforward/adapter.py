from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
)

from .observed_parser import MoneyForwardObservedParser, MoneyForwardObservedParserError


class MoneyForwardInputAdapterError(ValueError):
    pass


class MoneyForwardInputAdapter(InputAdapter):
    """Evidence-limited adapter for the observed 19-column journal export."""

    def __init__(self, parser: MoneyForwardObservedParser | None = None) -> None:
        self.parser = parser or MoneyForwardObservedParser()
        self.schema = moneyforward_cloud_journal_export_observed_schema()

    def supports(self, path: Path, profile: FormatProfile) -> bool:
        return (
            path.suffix.lower() == ".csv"
            and profile.format_id == self.schema.identity.stable_key
            and profile.encoding.lower() == "cp932"
        )

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        self._ensure_supported(path, profile)
        try:
            return self.parser.record_count(path)
        except MoneyForwardObservedParserError as exc:
            raise MoneyForwardInputAdapterError(str(exc)) from exc

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        self._ensure_supported(path, profile)
        try:
            entries = self.parser.parse_path(path)
        except MoneyForwardObservedParserError as exc:
            raise MoneyForwardInputAdapterError(str(exc)) from exc
        return [
            replace(
                entry,
                metadata={
                    **entry.metadata,
                    "input_adapter": "MoneyForwardInputAdapter",
                    "format_identity": self.schema.identity.stable_key,
                    "format_profile_id": profile.format_id,
                },
            )
            for entry in entries
        ]

    def _ensure_supported(self, path: Path, profile: FormatProfile) -> None:
        if not self.supports(path, profile):
            raise MoneyForwardInputAdapterError(
                "MoneyForwardInputAdapter supports only the exact observed CP932 "
                "19-column journal export identity."
            )

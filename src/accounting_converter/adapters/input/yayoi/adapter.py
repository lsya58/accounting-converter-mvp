from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    yayoi_ae19_direct_export_observed_schema,
)

from .observed_parser import (
    YayoiObservedSingleRecordParser,
    YayoiObservedSingleRecordParserError,
)


class YayoiInputAdapterError(ValueError):
    pass


class YayoiInputAdapter(InputAdapter):
    """Minimal production input adapter for the observed Yayoi AE19 subset."""

    def __init__(
        self,
        parser: YayoiObservedSingleRecordParser | None = None,
    ) -> None:
        self.parser = parser or YayoiObservedSingleRecordParser()
        self.schema = yayoi_ae19_direct_export_observed_schema()

    def supports(self, path: Path, profile: FormatProfile) -> bool:
        return (
            path.suffix.lower() in {".txt", ".csv"}
            and profile.format_id == self.schema.identity.stable_key
            and profile.encoding.lower() == "cp932"
        )

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        self._ensure_supported(path, profile)
        try:
            return self.parser.record_count(path)
        except YayoiObservedSingleRecordParserError as exc:
            raise YayoiInputAdapterError(str(exc)) from exc

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        self._ensure_supported(path, profile)
        try:
            entries = self.parser.parse_path(path)
        except YayoiObservedSingleRecordParserError as exc:
            raise YayoiInputAdapterError(str(exc)) from exc
        return [self._mark_adapter_entry(entry, profile) for entry in entries]

    def _ensure_supported(self, path: Path, profile: FormatProfile) -> None:
        if not self.supports(path, profile):
            raise YayoiInputAdapterError(
                "YayoiInputAdapter supports only the observed AE19 CP932 25-field profile."
            )

    def _mark_adapter_entry(
        self,
        entry: JournalEntry,
        profile: FormatProfile,
    ) -> JournalEntry:
        return replace(
            entry,
            metadata={
                **entry.metadata,
                "source": "yayoi_ae19_observed_input_adapter",
                "input_adapter": "YayoiInputAdapter",
                "format_identity": self.schema.identity.stable_key,
                "format_profile_id": profile.format_id,
                "official_documented_model": (
                    "弥生取り込み（インポート）形式（弥生会計05以降）"
                ),
                "evidence_level": "OBSERVED",
                "production_adapter": True,
            },
        )

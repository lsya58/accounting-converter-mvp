from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_migration_input_schema_definition,
)

from .observed_parser import JdlMigrationParseError, JdlMigrationParser


class JdlMigrationInputAdapterError(ValueError):
    pass


class JdlMigrationInputAdapter(InputAdapter):
    """Non-production strict input adapter for JDL old-master migration."""

    def __init__(self, parser: JdlMigrationParser | None = None) -> None:
        self.parser = parser or JdlMigrationParser()
        self.schema = jdl_ibex_cashbook_migration_input_schema_definition()

    def supports(self, path: Path, profile: FormatProfile) -> bool:
        return (
            path.suffix.lower() == ".csv"
            and profile.format_id == self.schema.identity.stable_key
            and profile.encoding.lower() == "cp932"
        )

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        self._ensure_supported(path, profile)
        try:
            return self.parser.parse_path(path).journal_record_count
        except JdlMigrationParseError as exc:
            raise JdlMigrationInputAdapterError(str(exc)) from exc

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        self._ensure_supported(path, profile)
        try:
            parsed = self.parser.parse_path(path)
        except JdlMigrationParseError as exc:
            raise JdlMigrationInputAdapterError(str(exc)) from exc
        return [
            replace(
                entry,
                metadata={
                    **entry.metadata,
                    "format_identity": self.schema.identity.stable_key,
                    "format_profile_id": profile.format_id,
                    "source_diagnostic_row_count": len(parsed.diagnostic_rows),
                    "source_preamble_row_count": len(parsed.preamble_rows),
                },
            )
            for entry in parsed.entries
        ]

    def _ensure_supported(self, path: Path, profile: FormatProfile) -> None:
        if not self.supports(path, profile):
            raise JdlMigrationInputAdapterError(
                "JdlMigrationInputAdapter supports only the strict CP932 "
                "JDL 30-column migration input identity."
            )

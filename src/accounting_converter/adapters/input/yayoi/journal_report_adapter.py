from __future__ import annotations

from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.profiles.known_formats import yayoi_journal_report_generic_identity

from .journal_report_parser import YayoiJournalReportParseError, YayoiJournalReportParser


class YayoiJournalReportInputAdapterError(ValueError):
    pass


def yayoi_journal_report_input_profile() -> FormatProfile:
    return FormatProfile(
        software="弥生",
        product="弥生会計",
        version="UNKNOWN",
        format_id=yayoi_journal_report_generic_identity().stable_key,
        encoding="cp932",
    )


class YayoiJournalReportInputAdapter(InputAdapter):
    """Input adapter for the Yayoi 仕訳日記帳 汎用形式 report (fail-closed)."""

    def __init__(self, parser: YayoiJournalReportParser | None = None) -> None:
        self.parser = parser or YayoiJournalReportParser()

    def supports(self, path: Path, profile: FormatProfile) -> bool:
        return (
            profile.format_id == yayoi_journal_report_generic_identity().stable_key
            and profile.encoding.lower() == "cp932"
        )

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        self._ensure(path, profile)
        return self.parser.diagnose(path).detail_rows

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        self._ensure(path, profile)
        try:
            return list(self.parser.parse_path(path))
        except YayoiJournalReportParseError as exc:
            raise YayoiJournalReportInputAdapterError(str(exc)) from exc

    def _ensure(self, path: Path, profile: FormatProfile) -> None:
        if not self.supports(path, profile):
            raise YayoiJournalReportInputAdapterError("unsupported Yayoi journal report profile")


class YayoiJournalReportStructuralValidator:
    def __init__(self, parser: YayoiJournalReportParser | None = None) -> None:
        self.parser = parser or YayoiJournalReportParser()

    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        return [
            ValidationResult(
                severity=Severity.ERROR,
                rule_id=f"YAYOI-REPORT-{issue.code}",
                message="弥生の仕訳日記帳（汎用形式）として安全に読み込めません。",
                field="source",
                input_value={"row": issue.row_number},
            )
            for issue in self.parser.diagnose(path).issues
        ]

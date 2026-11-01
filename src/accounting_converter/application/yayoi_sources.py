"""The two Yayoi source formats the JDL workflow accepts, behind one interface.

- 仕訳日記帳 汎用形式 (report export, 31 columns, preamble, totals)
- 弥生インポート形式 (25 columns, identifier flags)

A CompanySetting's profile names exactly one of them; the file must match it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from accounting_converter.adapters.input.yayoi.adapter import YayoiInputAdapter
from accounting_converter.adapters.input.yayoi.import_format_parser import (
    YayoiImportFormatParser,
    looks_like_yayoi_import_format,
)
from accounting_converter.adapters.input.yayoi.journal_report_adapter import (
    YayoiJournalReportInputAdapter,
    YayoiJournalReportStructuralValidator,
    yayoi_journal_report_input_profile,
)
from accounting_converter.adapters.input.yayoi.journal_report_parser import YayoiJournalReportParser
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.domain.format_metadata import FormatIdentity
from accounting_converter.profiles.known_formats import (
    yayoi_ae19_direct_export_observed_schema,
    yayoi_journal_report_generic_identity,
)


@dataclass(frozen=True)
class YayoiParsedSource:
    entries: tuple[JournalEntry, ...]
    issue_codes: tuple[str, ...]
    detail_rows: int
    rejected_journals: int

    @property
    def ok(self) -> bool:
        return not self.issue_codes


@dataclass(frozen=True)
class YayoiSourceFormat:
    key: str
    label: str
    identity: Callable[[], FormatIdentity]
    _diagnose: Callable[[Path], YayoiParsedSource]
    adapter: Callable[[], object]
    validator: Callable[[], object]
    input_profile: Callable[[], FormatProfile]

    def diagnose(self, path: Path) -> YayoiParsedSource:
        return self._diagnose(path)

    def read(self, path: Path) -> tuple[JournalEntry, ...]:
        return tuple(self.adapter().read(path, self.input_profile()))


def _report_diagnose(path: Path) -> YayoiParsedSource:
    result = YayoiJournalReportParser().diagnose(path)
    return YayoiParsedSource(
        result.entries, tuple(issue.code for issue in result.issues),
        result.detail_rows, result.rejected_journals,
    )


def _import_diagnose(path: Path) -> YayoiParsedSource:
    result = YayoiImportFormatParser().diagnose(path)
    codes = ("IMPORT_FORMAT_REJECTED",) if result.issues else ()
    return YayoiParsedSource(result.entries, codes, result.detail_rows, result.rejected_journals)


def _import_identity() -> FormatIdentity:
    return yayoi_ae19_direct_export_observed_schema().identity


def _import_profile() -> FormatProfile:
    return FormatProfile("弥生", "弥生会計", "UNKNOWN", _import_identity().stable_key, "cp932")


class YayoiImportFormatStructuralValidator:
    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        return [
            ValidationResult(
                severity=Severity.ERROR,
                rule_id="YAYOI-IMPORT-FORMAT",
                message="弥生インポート形式として安全に読み込めません。",
                field="source",
            )
            for _ in YayoiImportFormatParser().diagnose(path).issues
        ]


REPORT = YayoiSourceFormat(
    key="yayoi_journal_report_generic",
    label="弥生 仕訳日記帳（汎用形式）",
    identity=yayoi_journal_report_generic_identity,
    _diagnose=_report_diagnose,
    adapter=YayoiJournalReportInputAdapter,
    validator=YayoiJournalReportStructuralValidator,
    input_profile=yayoi_journal_report_input_profile,
)
IMPORT = YayoiSourceFormat(
    key="yayoi_import_format",
    label="弥生インポート形式",
    identity=_import_identity,
    _diagnose=_import_diagnose,
    adapter=lambda: YayoiInputAdapter(YayoiImportFormatParser()),
    validator=YayoiImportFormatStructuralValidator,
    input_profile=_import_profile,
)
FORMATS = (REPORT, IMPORT)


def format_for_identity_key(key: str | None) -> YayoiSourceFormat | None:
    return next((item for item in FORMATS if item.identity().stable_key == key), None)


def detect_format(path: Path) -> YayoiSourceFormat:
    """Choose by content (not by file name). Unknown content goes to the report parser, which fails closed."""
    return IMPORT if looks_like_yayoi_import_format(path) else REPORT

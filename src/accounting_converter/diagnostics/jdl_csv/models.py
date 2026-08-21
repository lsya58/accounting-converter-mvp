from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from accounting_converter.domain.mapping import MappingValue
from accounting_converter.domain.validation import ValidationResult


class CsvLineClassification(str, Enum):
    METADATA = "metadata"
    HEADER = "header"
    JOURNAL_RECORD = "journal_record"
    DIAGNOSTIC_MESSAGE = "diagnostic_message"
    UNKNOWN = "unknown"
    EMPTY = "empty"
    INVALID_CSV = "invalid_csv"


class DiagnosticIssueCategory(str, Enum):
    MASTER_MISMATCH = "MASTER_MISMATCH"
    UNKNOWN_JDL_MESSAGE = "UNKNOWN_JDL_MESSAGE"


class AccountingSide(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class JdlMasterType(str, Enum):
    ACCOUNT = "ACCOUNT"
    SUB_ACCOUNT = "SUB_ACCOUNT"
    DEPARTMENT = "DEPARTMENT"
    TAX_CATEGORY = "TAX_CATEGORY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DiagnosticAssociationStatus(str, Enum):
    LINKED_TO_PREVIOUS_RECORD = "LINKED_TO_PREVIOUS_RECORD"
    UNRESOLVED = "UNRESOLVED"


class FieldResolutionStatus(str, Enum):
    FROM_MESSAGE = "FROM_MESSAGE"
    FROM_FORMAT_PROFILE = "FROM_FORMAT_PROFILE"
    FIELD_UNRESOLVED = "FIELD_UNRESOLVED"


@dataclass(frozen=True)
class DiagnosticMappingCandidate:
    master_type: JdlMasterType
    side: AccountingSide
    source_value: str
    mapping_value: MappingValue
    account_value: str | None = None


@dataclass(frozen=True)
class DiagnosticIssue:
    category: DiagnosticIssueCategory
    side: AccountingSide
    master_type: JdlMasterType
    source_row: int
    source_value: str | None
    raw_message: str
    severity: str
    field: str | None = None
    related_record_row: int | None = None
    account_value: str | None = None
    association_status: DiagnosticAssociationStatus = (
        DiagnosticAssociationStatus.UNRESOLVED
    )
    field_resolution_status: FieldResolutionStatus = (
        FieldResolutionStatus.FIELD_UNRESOLVED
    )

    @property
    def is_resolved_to_record(self) -> bool:
        return (
            self.association_status
            is DiagnosticAssociationStatus.LINKED_TO_PREVIOUS_RECORD
        )

    def to_mapping_candidate(self) -> DiagnosticMappingCandidate | None:
        if self.category is not DiagnosticIssueCategory.MASTER_MISMATCH:
            return None
        if self.source_value is None:
            return None
        return DiagnosticMappingCandidate(
            master_type=self.master_type,
            side=self.side,
            source_value=self.source_value,
            account_value=self.account_value,
            mapping_value=MappingValue(source_value=self.source_value),
        )


@dataclass(frozen=True)
class MasterReferenceIssue:
    row_number: int
    field: str
    message: str
    raw_text: str
    diagnostic_issue: DiagnosticIssue | None = None


@dataclass(frozen=True)
class MasterMismatchSummaryItem:
    side: AccountingSide
    master_type: JdlMasterType
    source_value: str | None
    count: int
    first_row: int
    account_value: str | None = None


@dataclass(frozen=True)
class MasterMismatchSummary:
    total_count: int
    counts_by_type: tuple[tuple[str, int], ...]
    items: tuple[MasterMismatchSummaryItem, ...]
    mapping_candidates: tuple[DiagnosticMappingCandidate, ...]

    @classmethod
    def from_issues(
        cls, issues: tuple[DiagnosticIssue, ...]
    ) -> MasterMismatchSummary:
        master_issues = tuple(
            issue
            for issue in issues
            if issue.category is DiagnosticIssueCategory.MASTER_MISMATCH
        )
        type_counts = Counter(
            cls._type_key(issue.side, issue.master_type) for issue in master_issues
        )
        grouped: dict[
            tuple[AccountingSide, JdlMasterType, str | None, str | None],
            list[DiagnosticIssue],
        ] = {}
        for issue in master_issues:
            key = (
                issue.side,
                issue.master_type,
                issue.source_value,
                issue.account_value,
            )
            grouped.setdefault(key, []).append(issue)

        items = tuple(
            sorted(
                (
                    MasterMismatchSummaryItem(
                        side=side,
                        master_type=master_type,
                        source_value=source_value,
                        account_value=account_value,
                        count=len(group_issues),
                        first_row=min(issue.source_row for issue in group_issues),
                    )
                    for (
                        side,
                        master_type,
                        source_value,
                        account_value,
                    ), group_issues in grouped.items()
                ),
                key=lambda item: (-item.count, item.first_row),
            )
        )
        candidates_by_key: dict[
            tuple[JdlMasterType, AccountingSide, str, str | None],
            DiagnosticMappingCandidate,
        ] = {}
        for issue in master_issues:
            candidate = issue.to_mapping_candidate()
            if candidate is None:
                continue
            key = (
                candidate.master_type,
                candidate.side,
                candidate.source_value,
                candidate.account_value,
            )
            candidates_by_key.setdefault(key, candidate)

        return cls(
            total_count=len(master_issues),
            counts_by_type=tuple(sorted(type_counts.items())),
            items=items,
            mapping_candidates=tuple(candidates_by_key.values()),
        )

    @staticmethod
    def _type_key(side: AccountingSide, master_type: JdlMasterType) -> str:
        if side in {AccountingSide.DEBIT, AccountingSide.CREDIT}:
            return f"{side.value}:{master_type.value}"
        return master_type.value


@dataclass(frozen=True)
class JdlCsvLineObservation:
    row_number: int
    raw_text: str
    classification: CsvLineClassification
    columns: tuple[str, ...] = field(default_factory=tuple)
    csv_error: str | None = None
    master_reference_issue: MasterReferenceIssue | None = None
    diagnostic_issue: DiagnosticIssue | None = None

    @property
    def column_count(self) -> int:
        return len(self.columns)


@dataclass(frozen=True)
class JdlCsvSchemaFingerprint:
    encoding: str
    delimiter: str
    header_names: tuple[str, ...]
    column_count: int | None
    line_ending: str
    has_bom: bool
    metadata_pattern: tuple[str, ...]
    record_column_counts: tuple[tuple[int, int], ...]

    @classmethod
    def from_analysis(cls, analysis: JdlCsvAnalysisResult) -> JdlCsvSchemaFingerprint:
        patterns: list[str] = []
        if any(line.raw_text.lstrip().startswith("//") for line in analysis.metadata_lines):
            patterns.append("slash_comment")
        if analysis.metadata_line_count:
            patterns.append("metadata_present")
        if analysis.diagnostic_message_lines:
            patterns.append("diagnostic_message_present")

        counts = Counter(
            line.column_count for line in analysis.journal_record_lines
        )
        return cls(
            encoding=analysis.encoding,
            delimiter=analysis.delimiter,
            header_names=analysis.header_columns,
            column_count=analysis.header_column_count,
            line_ending=analysis.line_ending,
            has_bom=analysis.has_bom,
            metadata_pattern=tuple(patterns),
            record_column_counts=tuple(sorted(counts.items())),
        )


@dataclass(frozen=True)
class JdlCsvSchemaComparison:
    baseline: JdlCsvSchemaFingerprint
    target: JdlCsvSchemaFingerprint
    differences: tuple[ValidationResult, ...]

    @property
    def has_differences(self) -> bool:
        return bool(self.differences)


@dataclass(frozen=True)
class JdlCsvAnalysisResult:
    file_name: str
    encoding: str
    delimiter: str
    total_physical_lines: int
    comment_metadata_line_count: int
    header_row_number: int | None
    header_columns: tuple[str, ...]
    data_line_count: int
    line_column_counts: tuple[tuple[int, int], ...]
    max_column_count: int
    min_column_count: int
    invalid_csv_lines: tuple[JdlCsvLineObservation, ...]
    empty_lines: tuple[JdlCsvLineObservation, ...]
    diagnostic_message_lines: tuple[JdlCsvLineObservation, ...]
    analysis_warnings: tuple[ValidationResult, ...]
    analysis_errors: tuple[ValidationResult, ...]
    line_observations: tuple[JdlCsvLineObservation, ...]
    has_bom: bool
    line_ending: str
    schema_fingerprint: JdlCsvSchemaFingerprint | None = None
    diagnostic_issues: tuple[DiagnosticIssue, ...] = field(default_factory=tuple)
    master_mismatch_summary: MasterMismatchSummary = field(
        default_factory=lambda: MasterMismatchSummary(
            total_count=0,
            counts_by_type=(),
            items=(),
            mapping_candidates=(),
        )
    )

    @property
    def metadata_line_count(self) -> int:
        return self.comment_metadata_line_count

    @property
    def header_column_count(self) -> int | None:
        if not self.header_columns:
            return None
        return len(self.header_columns)

    @property
    def journal_record_lines(self) -> tuple[JdlCsvLineObservation, ...]:
        return tuple(
            line
            for line in self.line_observations
            if line.classification is CsvLineClassification.JOURNAL_RECORD
        )

    @property
    def metadata_lines(self) -> tuple[JdlCsvLineObservation, ...]:
        return tuple(
            line
            for line in self.line_observations
            if line.classification is CsvLineClassification.METADATA
        )

    @property
    def unknown_lines(self) -> tuple[JdlCsvLineObservation, ...]:
        return tuple(
            line
            for line in self.line_observations
            if line.classification is CsvLineClassification.UNKNOWN
        )

    @property
    def validation_results(self) -> tuple[ValidationResult, ...]:
        return self.analysis_errors + self.analysis_warnings

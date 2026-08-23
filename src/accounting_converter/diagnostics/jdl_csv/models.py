from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
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
    FROM_OBSERVED_SCHEMA = "FROM_OBSERVED_SCHEMA"
    FROM_FORMAT_PROFILE = "FROM_FORMAT_PROFILE"
    FIELD_UNRESOLVED = "FIELD_UNRESOLVED"


class IdentifierFlagMeaningStatus(str, Enum):
    OBSERVED_ONLY = "OBSERVED_ONLY"
    UNRESOLVED = "UNRESOLVED"


class ObservedJournalGroupStatus(str, Enum):
    OBSERVED_SINGLE_RECORD = "OBSERVED_SINGLE_RECORD"
    OBSERVED_MULTI_RECORD_SEQUENCE = "OBSERVED_MULTI_RECORD_SEQUENCE"
    UNRESOLVED = "UNRESOLVED"


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
    counts_by_master_type: tuple[tuple[str, int], ...]
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
        master_type_counts = Counter(
            issue.master_type.value for issue in master_issues
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
            counts_by_master_type=tuple(sorted(master_type_counts.items())),
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
class ObservedJournalGroupCandidate:
    candidate_id: str
    start_record_index: int
    end_record_index: int
    record_count: int
    identifier_flags: tuple[str, ...]
    voucher_number: str | None
    date: str | None
    debit_total: Decimal
    credit_total: Decimal
    balanced: bool
    grouping_confidence: str
    grouping_basis: tuple[str, ...]
    status: ObservedJournalGroupStatus
    valid_sequence: bool | None = None
    same_voucher_number: bool | None = None
    same_date: bool | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ObservedJournalGroupingSummary:
    candidates: tuple[ObservedJournalGroupCandidate, ...] = field(default_factory=tuple)

    @property
    def total_candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def single_record_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.status is ObservedJournalGroupStatus.OBSERVED_SINGLE_RECORD
        )

    @property
    def multi_record_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.identifier_flags[:1] == ("1110",)
        )

    @property
    def valid_multi_record_sequence_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.identifier_flags[:1] == ("1110",)
            and candidate.valid_sequence is True
        )

    @property
    def same_voucher_number_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.identifier_flags[:1] == ("1110",)
            and candidate.same_voucher_number is True
        )

    @property
    def same_date_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.identifier_flags[:1] == ("1110",)
            and candidate.same_date is True
        )

    @property
    def balanced_multi_record_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.identifier_flags[:1] == ("1110",)
            and candidate.balanced
        )

    @property
    def unresolved_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.candidates
            if candidate.status is ObservedJournalGroupStatus.UNRESOLVED
        )


@dataclass(frozen=True)
class ObservedJdlSchema:
    product: str
    observed_version: str
    encoding: str
    has_bom: bool
    line_ending: str
    journal_column_count: int
    observed_header: tuple[str, ...]
    journal_count: int
    field_names: dict[str, str] = field(default_factory=dict)
    observed_identifier_flags: tuple[str, ...] = field(default_factory=tuple)
    identifier_flag_meaning_status: IdentifierFlagMeaningStatus = (
        IdentifierFlagMeaningStatus.OBSERVED_ONLY
    )
    observed_behavior: tuple[str, ...] = field(default_factory=tuple)
    is_formal_format_profile: bool = False

    def column_index_for(self, field: str) -> int | None:
        header_name = self.field_names.get(field)
        if header_name is None:
            return None
        try:
            return self.observed_header.index(header_name)
        except ValueError:
            return None


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
    identifier_flag_counts: tuple[tuple[str, int], ...]
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
            counts_by_master_type=(),
            counts_by_type=(),
            items=(),
            mapping_candidates=(),
        )
    )
    observed_schema: ObservedJdlSchema | None = None
    observed_grouping_summary: ObservedJournalGroupingSummary = field(
        default_factory=ObservedJournalGroupingSummary
    )

    @property
    def data_record_count(self) -> int:
        return self.data_line_count

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

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from accounting_converter.domain.validation import ValidationResult


class YayoiStructuralMatchStatus(str, Enum):
    MATCH_CANDIDATE = "MATCH_CANDIDATE"
    STRUCTURAL_DIFFERENCE = "STRUCTURAL_DIFFERENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class YayoiLineClassification(str, Enum):
    EMPTY = "EMPTY"
    HEADER = "HEADER"
    DATA_RECORD = "DATA_RECORD"
    INVALID_CSV = "INVALID_CSV"
    UNKNOWN = "UNKNOWN"


class YayoiGroupCandidateStatus(str, Enum):
    OBSERVED_SINGLE_RECORD = "OBSERVED_SINGLE_RECORD"
    OBSERVED_MULTI_RECORD_SEQUENCE = "OBSERVED_MULTI_RECORD_SEQUENCE"
    MALFORMED_SEQUENCE = "MALFORMED_SEQUENCE"
    UNCLOSED_SEQUENCE = "UNCLOSED_SEQUENCE"
    UNKNOWN_FLAG_SEQUENCE = "UNKNOWN_FLAG_SEQUENCE"


@dataclass(frozen=True)
class YayoiCsvLineObservation:
    row_number: int
    classification: YayoiLineClassification
    column_count: int
    csv_error: str | None = None


@dataclass(frozen=True)
class YayoiHeaderObservation:
    detected: bool
    row_number: int | None
    exact_official_header: bool
    column_count: int | None
    matched_column_names_count: int = 0


@dataclass(frozen=True)
class YayoiFlagObservation:
    official_flag_counts: tuple[tuple[str, int], ...] = ()
    unknown_flag_counts: tuple[tuple[str, int], ...] = ()
    unknown_flag_rows: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class YayoiGroupCandidate:
    candidate_id: str
    start_row_number: int
    end_row_number: int
    record_count: int
    identifier_flags: tuple[str, ...]
    status: YayoiGroupCandidateStatus
    starts_with_2110: bool = False
    ends_with_2101: bool = False
    middle_2100_count: int = 0
    malformed_reason: str | None = None


@dataclass(frozen=True)
class YayoiAmountObservation:
    debit_total: Decimal | None = None
    credit_total: Decimal | None = None
    balanced: bool | None = None
    amount_parse_error_count: int = 0
    amount_unknown_count: int = 0
    amount_issue_rows: tuple[tuple[int, str, str], ...] = ()
    date_parse_candidate_error_count: int = 0
    date_issue_rows: tuple[tuple[int, str], ...] = ()
    date_format_candidates: tuple[str, ...] = ()
    amount_field_parseable_positions: tuple[int, ...] = ()


@dataclass(frozen=True)
class YayoiOfficialComparison:
    official_column_count: int
    observed_dominant_column_count: int | None
    column_count_difference: int | None
    header_observation: YayoiHeaderObservation
    structural_match_status: YayoiStructuralMatchStatus
    possible_official_25_column_format: bool
    additional_column_count: int = 0
    missing_column_count: int = 0
    formal_profile_ready: bool = False
    human_review_required: bool = True


@dataclass(frozen=True)
class YayoiCsvAnalysisResult:
    file_name: str
    encoding: str
    encoding_candidates: tuple[str, ...]
    delimiter: str
    has_bom: bool
    line_ending: str
    total_physical_lines: int
    empty_line_count: int
    csv_parseable: bool
    line_observations: tuple[YayoiCsvLineObservation, ...]
    row_column_count_distribution: tuple[tuple[int, int], ...]
    dominant_column_count: int | None
    column_count_mismatch_rows: tuple[int, ...]
    first_rows_features: tuple[dict[str, object], ...]
    data_record_count: int
    header_observation: YayoiHeaderObservation
    flag_observation: YayoiFlagObservation
    group_candidates: tuple[YayoiGroupCandidate, ...]
    amount_observation: YayoiAmountObservation
    official_comparison: YayoiOfficialComparison
    validation_results: tuple[ValidationResult, ...] = field(default_factory=tuple)

    @property
    def official_flag_count(self) -> int:
        return sum(count for _, count in self.flag_observation.official_flag_counts)

    @property
    def unknown_flag_count(self) -> int:
        return sum(count for _, count in self.flag_observation.unknown_flag_counts)

    @property
    def group_candidate_count(self) -> int:
        return len(self.group_candidates)

    @property
    def single_record_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.group_candidates
            if candidate.status is YayoiGroupCandidateStatus.OBSERVED_SINGLE_RECORD
        )

    @property
    def multi_record_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.group_candidates
            if candidate.status is YayoiGroupCandidateStatus.OBSERVED_MULTI_RECORD_SEQUENCE
        )

    @property
    def malformed_group_candidate_count(self) -> int:
        return sum(
            1
            for candidate in self.group_candidates
            if candidate.status
            in {
                YayoiGroupCandidateStatus.MALFORMED_SEQUENCE,
                YayoiGroupCandidateStatus.UNCLOSED_SEQUENCE,
                YayoiGroupCandidateStatus.UNKNOWN_FLAG_SEQUENCE,
            }
        )

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from accounting_converter.domain.validation import ValidationResult

from .observed_schemas import ObservedJdlAccountingJournalListSchema


class JdlAccountingJournalListComparison(str, Enum):
    SAME_FAMILY_CANDIDATE = "SAME_FAMILY_CANDIDATE"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    DIFFERENT_STRUCTURE = "DIFFERENT_STRUCTURE"


class JdlAccountingJournalListReadiness(str, Enum):
    READ_ONLY_RECORD_CANDIDATES = "READ_ONLY_RECORD_CANDIDATES"
    INSUFFICIENT_EVIDENCE_FOR_COMMON_JOURNAL = (
        "INSUFFICIENT_EVIDENCE_FOR_COMMON_JOURNAL"
    )
    PARSE_FAILED = "PARSE_FAILED"


class PostImportVerificationStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    PARSE_FAILED = "PARSE_FAILED"


@dataclass(frozen=True)
class ColumnPopulation:
    column_name: str
    position_1_based: int
    blank_count: int
    nonblank_count: int
    distinct_count: int


@dataclass(frozen=True)
class JdlAccountingJournalListRecordCandidate:
    row_number: int
    voucher_number: str
    date: date
    debit_account: str
    debit_sub_account: str | None
    credit_account: str
    credit_sub_account: str | None
    amount: Decimal
    description: str | None
    tax_scope: str | None
    tax_category: str | None

    @property
    def match_key(self) -> tuple[str, str, str, str, str, str | None]:
        return (
            self.date.isoformat(),
            str(self.amount),
            self.debit_account,
            self.credit_account,
            self.description or "",
            self.voucher_number or None,
        )


@dataclass(frozen=True)
class JdlAccountingJournalListAnalysisResult:
    file_name: str
    encoding: str
    has_bom: bool
    line_ending: str
    total_physical_lines: int
    logical_row_count: int
    preamble_line_count: int
    header_row_number: int | None
    header_columns: tuple[str, ...]
    header_column_count: int | None
    data_row_count: int
    data_row_column_count_distribution: tuple[tuple[int, int], ...]
    malformed_row_numbers: tuple[int, ...]
    blank_row_count: int
    column_populations: tuple[ColumnPopulation, ...]
    parseable_date_count: int
    parseable_amount_count: int
    record_candidates: tuple[JdlAccountingJournalListRecordCandidate, ...]
    warnings: tuple[ValidationResult, ...]
    errors: tuple[ValidationResult, ...]
    observed_schema: ObservedJdlAccountingJournalListSchema
    comparison_to_cashbook_30_column: JdlAccountingJournalListComparison
    readiness: JdlAccountingJournalListReadiness

    @property
    def validation_results(self) -> tuple[ValidationResult, ...]:
        return self.errors + self.warnings

    @property
    def can_build_common_journal_entries(self) -> bool:
        return False


@dataclass(frozen=True)
class PostImportVerificationResult:
    status: PostImportVerificationStatus
    expected_count: int
    actual_count: int
    matched_count: int
    mismatch_categories: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    structural_status: str = "not_evaluated"
    validation_results: tuple[ValidationResult, ...] = field(default_factory=tuple)

    @property
    def success(self) -> bool:
        return self.status is PostImportVerificationStatus.MATCH

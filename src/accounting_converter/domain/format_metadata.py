from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class EvidenceLevel(str, Enum):
    OFFICIAL_DOCUMENTED = "OFFICIAL_DOCUMENTED"
    OBSERVED = "OBSERVED"
    VERIFIED_BY_REAL_IMPORT = "VERIFIED_BY_REAL_IMPORT"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class FormatDirection(str, Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    BOTH = "BOTH"


class CapabilityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONDITIONAL = "CONDITIONAL"


class SemanticField(str, Enum):
    IDENTIFIER_FLAG = "IDENTIFIER_FLAG"
    VOUCHER_NUMBER = "VOUCHER_NUMBER"
    DATE = "DATE"
    DEBIT_ACCOUNT = "DEBIT_ACCOUNT"
    DEBIT_SUBACCOUNT = "DEBIT_SUBACCOUNT"
    DEBIT_DEPARTMENT = "DEBIT_DEPARTMENT"
    DEBIT_TAX_CATEGORY = "DEBIT_TAX_CATEGORY"
    DEBIT_AMOUNT = "DEBIT_AMOUNT"
    DEBIT_TAX_AMOUNT = "DEBIT_TAX_AMOUNT"
    CREDIT_ACCOUNT = "CREDIT_ACCOUNT"
    CREDIT_SUBACCOUNT = "CREDIT_SUBACCOUNT"
    CREDIT_DEPARTMENT = "CREDIT_DEPARTMENT"
    CREDIT_TAX_CATEGORY = "CREDIT_TAX_CATEGORY"
    CREDIT_AMOUNT = "CREDIT_AMOUNT"
    CREDIT_TAX_AMOUNT = "CREDIT_TAX_AMOUNT"
    DESCRIPTION = "DESCRIPTION"
    INVOICE_CLASSIFICATION = "INVOICE_CLASSIFICATION"
    JOURNAL_MEMO = "JOURNAL_MEMO"
    ADJUSTMENT_FLAG = "ADJUSTMENT_FLAG"
    UNKNOWN = "UNKNOWN"


class FieldDataType(str, Enum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    BOOLEAN = "BOOLEAN"
    UNKNOWN = "UNKNOWN"


class BlankPolicy(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    ZERO_ALLOWED = "ZERO_ALLOWED"
    UNKNOWN = "UNKNOWN"


class JournalGroupingStrategy(str, Enum):
    SINGLE_RECORD = "SINGLE_RECORD"
    IDENTIFIER_FLAG_SEQUENCE = "IDENTIFIER_FLAG_SEQUENCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceProvenance:
    title: str
    url: str | None
    evidence_level: EvidenceLevel
    retrieved_at: date | None = None
    verified_at: date | None = None
    notes: str | None = None


@dataclass(frozen=True)
class FormatIdentity:
    vendor: str
    product: str
    format_name: str
    direction: FormatDirection
    evidence_level: EvidenceLevel
    edition: str | None = None
    major_version: str | None = None
    minor_version: str | None = None
    version_range: str | None = None
    format_version: str | None = None
    source_reference: SourceProvenance | None = None
    verified_at: date | None = None
    notes: str | None = None

    @property
    def stable_key(self) -> str:
        parts = (
            self.vendor,
            self.product,
            self.edition or "",
            self.major_version or "",
            self.minor_version or "",
            self.version_range or "",
            self.format_name,
            self.format_version or "",
            self.direction.value,
            self.evidence_level.value,
        )
        return "|".join(parts)


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    display_name: str
    semantic_field: SemanticField
    column_position: int | None = None
    required: bool = False
    data_type: FieldDataType = FieldDataType.UNKNOWN
    max_length: int | None = None
    allowed_values: tuple[str, ...] = ()
    blank_policy: BlankPolicy = BlankPolicy.UNKNOWN
    evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    source: SourceProvenance | None = None
    notes: str | None = None


@dataclass(frozen=True)
class Capability:
    status: CapabilityStatus
    notes: str | None = None


@dataclass(frozen=True)
class FormatCapabilities:
    supports_subaccount: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_department: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_tax_category: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_tax_amount: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_invoice_classification: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_description: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_voucher_number: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_compound_journal: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_multiple_debit_lines: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_multiple_credit_lines: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    supports_header: Capability = field(
        default_factory=lambda: Capability(CapabilityStatus.UNKNOWN)
    )
    accepted_extensions: tuple[str, ...] = ()
    encoding_candidates: tuple[str, ...] = ()
    delimiter: str | None = None
    column_count_rules: tuple[int, ...] = ()
    maximum_field_lengths: dict[SemanticField, int] = field(default_factory=dict)
    journal_grouping_strategy: JournalGroupingStrategy = (
        JournalGroupingStrategy.UNKNOWN
    )


@dataclass(frozen=True)
class SchemaDefinition:
    identity: FormatIdentity
    fields: tuple[FieldDefinition, ...]
    capabilities: FormatCapabilities = field(default_factory=FormatCapabilities)
    delimiter: str | None = None
    encoding: str | None = None
    has_header: CapabilityStatus = CapabilityStatus.UNKNOWN
    column_count: int | None = None
    date_formats: tuple[str, ...] = ()
    numeric_format: str | None = None
    blank_representation: str | None = None
    notes: str | None = None

    @property
    def semantic_fields(self) -> frozenset[SemanticField]:
        return frozenset(field.semantic_field for field in self.fields)

    def field_for(self, semantic_field: SemanticField) -> FieldDefinition | None:
        for field_definition in self.fields:
            if field_definition.semantic_field is semantic_field:
                return field_definition
        return None

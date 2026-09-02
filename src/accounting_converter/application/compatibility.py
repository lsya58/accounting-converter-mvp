from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from accounting_converter.domain.format_metadata import (
    CapabilityStatus,
    FieldDataType,
    SchemaDefinition,
    SemanticField,
)


class CompatibilityClassification(str, Enum):
    DIRECT = "DIRECT"
    NORMALIZATION_REQUIRED = "NORMALIZATION_REQUIRED"
    MAPPING_REQUIRED = "MAPPING_REQUIRED"
    DEFAULT_REQUIRED = "DEFAULT_REQUIRED"
    STRUCTURAL_TRANSFORMATION_REQUIRED = "STRUCTURAL_TRANSFORMATION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    HUMAN_CONFIRMATION_REQUIRED = "HUMAN_CONFIRMATION_REQUIRED"


class Lossiness(str, Enum):
    LOSSLESS = "LOSSLESS"
    LOSSY = "LOSSY"
    UNKNOWN = "UNKNOWN"


class TransformationStepType(str, Enum):
    COPY = "COPY"
    REORDER = "REORDER"
    NORMALIZE_TEXT = "NORMALIZE_TEXT"
    DATE_FORMAT = "DATE_FORMAT"
    NUMERIC_FORMAT = "NUMERIC_FORMAT"
    MASTER_MAPPING = "MASTER_MAPPING"
    TAX_MAPPING = "TAX_MAPPING"
    DEFAULT_VALUE = "DEFAULT_VALUE"
    GROUPING_TRANSFORMATION = "GROUPING_TRANSFORMATION"
    DROP_WITH_CONFIRMATION = "DROP_WITH_CONFIRMATION"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CompatibilityFinding:
    subject: str
    classification: CompatibilityClassification
    lossiness: Lossiness
    message: str
    semantic_field: SemanticField | None = None
    requires_human_confirmation: bool = False


@dataclass(frozen=True)
class CompatibilityReport:
    source_schema: SchemaDefinition
    target_schema: SchemaDefinition
    findings: tuple[CompatibilityFinding, ...]
    overall_lossiness: Lossiness

    @property
    def requires_human_confirmation(self) -> bool:
        return any(finding.requires_human_confirmation for finding in self.findings)


@dataclass(frozen=True)
class TransformationStep:
    step_type: TransformationStepType
    field: SemanticField | None
    description: str
    requires_user_confirmation: bool = False


@dataclass(frozen=True)
class TransformationPlan:
    source_schema_id: str
    target_schema_id: str
    steps: tuple[TransformationStep, ...]
    lossiness: Lossiness
    executable_without_confirmation: bool


class FormatCompatibilityAnalyzer:
    MASTER_FIELDS = {
        SemanticField.DEBIT_ACCOUNT,
        SemanticField.CREDIT_ACCOUNT,
        SemanticField.DEBIT_SUBACCOUNT,
        SemanticField.CREDIT_SUBACCOUNT,
        SemanticField.DEBIT_DEPARTMENT,
        SemanticField.CREDIT_DEPARTMENT,
    }
    TAX_FIELDS = {
        SemanticField.DEBIT_TAX_CATEGORY,
        SemanticField.CREDIT_TAX_CATEGORY,
    }

    def analyze(
        self,
        source_schema: SchemaDefinition,
        target_schema: SchemaDefinition,
    ) -> CompatibilityReport:
        findings: list[CompatibilityFinding] = []
        findings.extend(self._field_findings(source_schema, target_schema))
        findings.extend(self._format_findings(source_schema, target_schema))
        findings.extend(self._capability_findings(source_schema, target_schema))
        overall = self._overall_lossiness(findings)
        return CompatibilityReport(
            source_schema=source_schema,
            target_schema=target_schema,
            findings=tuple(findings),
            overall_lossiness=overall,
        )

    def build_transformation_plan(
        self,
        report: CompatibilityReport,
    ) -> TransformationPlan:
        steps: list[TransformationStep] = []
        for finding in report.findings:
            field = finding.semantic_field
            step_type = self._step_type_for(finding)
            steps.append(
                TransformationStep(
                    step_type=step_type,
                    field=field,
                    description=finding.message,
                    requires_user_confirmation=finding.requires_human_confirmation,
                )
            )
        return TransformationPlan(
            source_schema_id=report.source_schema.identity.stable_key,
            target_schema_id=report.target_schema.identity.stable_key,
            steps=tuple(steps),
            lossiness=report.overall_lossiness,
            executable_without_confirmation=not report.requires_human_confirmation,
        )

    def _field_findings(
        self,
        source_schema: SchemaDefinition,
        target_schema: SchemaDefinition,
    ) -> list[CompatibilityFinding]:
        findings: list[CompatibilityFinding] = []
        all_fields = sorted(
            source_schema.semantic_fields | target_schema.semantic_fields,
            key=lambda field: field.value,
        )
        for semantic_field in all_fields:
            if semantic_field is SemanticField.UNKNOWN:
                continue
            source_field = source_schema.field_for(semantic_field)
            target_field = target_schema.field_for(semantic_field)
            if source_field and target_field:
                findings.append(
                    CompatibilityFinding(
                        subject="semantic_field_presence",
                        classification=self._classification_for_shared_field(
                            semantic_field,
                            source_field.data_type,
                            target_field.data_type,
                        ),
                        lossiness=Lossiness.LOSSLESS,
                        message=f"{semantic_field.value} is present in both schemas.",
                        semantic_field=semantic_field,
                        requires_human_confirmation=semantic_field
                        in self.MASTER_FIELDS | self.TAX_FIELDS,
                    )
                )
                continue
            if source_field and not target_field:
                findings.append(
                    CompatibilityFinding(
                        subject="semantic_field_presence",
                        classification=CompatibilityClassification.HUMAN_CONFIRMATION_REQUIRED,
                        lossiness=Lossiness.LOSSY,
                        message=f"{semantic_field.value} is present only in source.",
                        semantic_field=semantic_field,
                        requires_human_confirmation=True,
                    )
                )
                continue
            if target_field and not source_field:
                classification = (
                    CompatibilityClassification.DEFAULT_REQUIRED
                    if target_field.required
                    else CompatibilityClassification.UNKNOWN
                )
                findings.append(
                    CompatibilityFinding(
                        subject="required_fields",
                        classification=classification,
                        lossiness=Lossiness.UNKNOWN,
                        message=f"{semantic_field.value} is present only in target.",
                        semantic_field=semantic_field,
                        requires_human_confirmation=target_field.required,
                    )
                )
        return findings

    def _format_findings(
        self,
        source_schema: SchemaDefinition,
        target_schema: SchemaDefinition,
    ) -> list[CompatibilityFinding]:
        findings: list[CompatibilityFinding] = []
        if source_schema.encoding and target_schema.encoding:
            findings.append(
                self._simple_format_finding(
                    subject="encoding",
                    same=source_schema.encoding == target_schema.encoding,
                    requires_confirmation=False,
                )
            )
        else:
            findings.append(
                CompatibilityFinding(
                    subject="encoding",
                    classification=CompatibilityClassification.UNKNOWN,
                    lossiness=Lossiness.UNKNOWN,
                    message="Encoding compatibility is unknown.",
                    requires_human_confirmation=True,
                )
            )
        findings.append(
            self._simple_format_finding(
                subject="delimiter",
                same=source_schema.delimiter == target_schema.delimiter,
                requires_confirmation=False,
            )
        )
        if source_schema.column_count != target_schema.column_count:
            findings.append(
                CompatibilityFinding(
                    subject="column_count",
                    classification=CompatibilityClassification.STRUCTURAL_TRANSFORMATION_REQUIRED,
                    lossiness=Lossiness.LOSSLESS,
                    message="Column count differs; schema-driven reorder/default handling is required.",
                    requires_human_confirmation=True,
                )
            )
        else:
            findings.append(
                CompatibilityFinding(
                    subject="column_count",
                    classification=CompatibilityClassification.DIRECT,
                    lossiness=Lossiness.LOSSLESS,
                    message="Column count is identical.",
                )
            )
        if source_schema.date_formats != target_schema.date_formats:
            findings.append(
                CompatibilityFinding(
                    subject="date_representation",
                    classification=CompatibilityClassification.NORMALIZATION_REQUIRED,
                    lossiness=Lossiness.UNKNOWN,
                    message="Date representation may require normalization.",
                    requires_human_confirmation=True,
                )
            )
        if source_schema.numeric_format != target_schema.numeric_format:
            findings.append(
                CompatibilityFinding(
                    subject="numeric_representation",
                    classification=CompatibilityClassification.NORMALIZATION_REQUIRED,
                    lossiness=Lossiness.UNKNOWN,
                    message="Numeric representation may require normalization.",
                    requires_human_confirmation=True,
                )
            )
        if source_schema.blank_representation != target_schema.blank_representation:
            findings.append(
                CompatibilityFinding(
                    subject="blank_representation",
                    classification=CompatibilityClassification.NORMALIZATION_REQUIRED,
                    lossiness=Lossiness.UNKNOWN,
                    message="Blank representation may require normalization.",
                    requires_human_confirmation=True,
                )
            )
        return findings

    def _capability_findings(
        self,
        source_schema: SchemaDefinition,
        target_schema: SchemaDefinition,
    ) -> list[CompatibilityFinding]:
        findings: list[CompatibilityFinding] = []
        capability_pairs = (
            ("compound_journal_representation", source_schema.capabilities.supports_compound_journal.status, target_schema.capabilities.supports_compound_journal.status),
            ("subaccount_representation", source_schema.capabilities.supports_subaccount.status, target_schema.capabilities.supports_subaccount.status),
            ("department_representation", source_schema.capabilities.supports_department.status, target_schema.capabilities.supports_department.status),
            ("tax_representation", source_schema.capabilities.supports_tax_category.status, target_schema.capabilities.supports_tax_category.status),
            ("header", source_schema.has_header, target_schema.has_header),
        )
        for subject, source_status, target_status in capability_pairs:
            findings.append(
                self._capability_finding(subject, source_status, target_status)
            )
        return findings

    def _classification_for_shared_field(
        self,
        semantic_field: SemanticField,
        source_type: FieldDataType,
        target_type: FieldDataType,
    ) -> CompatibilityClassification:
        if semantic_field in self.MASTER_FIELDS:
            return CompatibilityClassification.MAPPING_REQUIRED
        if semantic_field in self.TAX_FIELDS:
            return CompatibilityClassification.MAPPING_REQUIRED
        if source_type is target_type:
            return CompatibilityClassification.DIRECT
        return CompatibilityClassification.NORMALIZATION_REQUIRED

    def _simple_format_finding(
        self,
        subject: str,
        same: bool,
        requires_confirmation: bool,
    ) -> CompatibilityFinding:
        return CompatibilityFinding(
            subject=subject,
            classification=(
                CompatibilityClassification.DIRECT
                if same
                else CompatibilityClassification.NORMALIZATION_REQUIRED
            ),
            lossiness=Lossiness.LOSSLESS if same else Lossiness.UNKNOWN,
            message=(
                f"{subject} is identical."
                if same
                else f"{subject} differs and may require normalization."
            ),
            requires_human_confirmation=requires_confirmation or not same,
        )

    def _capability_finding(
        self,
        subject: str,
        source_status: CapabilityStatus,
        target_status: CapabilityStatus,
    ) -> CompatibilityFinding:
        if source_status is CapabilityStatus.UNKNOWN or target_status is CapabilityStatus.UNKNOWN:
            return CompatibilityFinding(
                subject=subject,
                classification=CompatibilityClassification.UNKNOWN,
                lossiness=Lossiness.UNKNOWN,
                message=f"{subject} compatibility is unknown.",
                requires_human_confirmation=True,
            )
        if source_status is CapabilityStatus.SUPPORTED and target_status is CapabilityStatus.UNSUPPORTED:
            return CompatibilityFinding(
                subject=subject,
                classification=CompatibilityClassification.UNSUPPORTED,
                lossiness=Lossiness.LOSSY,
                message=f"{subject} is supported by source but not by target.",
                requires_human_confirmation=True,
            )
        if CapabilityStatus.CONDITIONAL in {source_status, target_status}:
            return CompatibilityFinding(
                subject=subject,
                classification=CompatibilityClassification.HUMAN_CONFIRMATION_REQUIRED,
                lossiness=Lossiness.UNKNOWN,
                message=f"{subject} is conditional and requires confirmation.",
                requires_human_confirmation=True,
            )
        return CompatibilityFinding(
            subject=subject,
            classification=CompatibilityClassification.DIRECT,
            lossiness=Lossiness.LOSSLESS,
            message=f"{subject} is directly compatible.",
        )

    def _overall_lossiness(
        self,
        findings: list[CompatibilityFinding],
    ) -> Lossiness:
        if any(finding.lossiness is Lossiness.LOSSY for finding in findings):
            return Lossiness.LOSSY
        if any(finding.lossiness is Lossiness.UNKNOWN for finding in findings):
            return Lossiness.UNKNOWN
        return Lossiness.LOSSLESS

    def _step_type_for(
        self,
        finding: CompatibilityFinding,
    ) -> TransformationStepType:
        if finding.classification is CompatibilityClassification.DIRECT:
            return TransformationStepType.COPY
        if finding.classification is CompatibilityClassification.NORMALIZATION_REQUIRED:
            if finding.subject == "date_representation":
                return TransformationStepType.DATE_FORMAT
            if finding.subject == "numeric_representation":
                return TransformationStepType.NUMERIC_FORMAT
            return TransformationStepType.NORMALIZE_TEXT
        if finding.classification is CompatibilityClassification.MAPPING_REQUIRED:
            if finding.semantic_field in self.TAX_FIELDS:
                return TransformationStepType.TAX_MAPPING
            return TransformationStepType.MASTER_MAPPING
        if finding.classification is CompatibilityClassification.DEFAULT_REQUIRED:
            return TransformationStepType.DEFAULT_VALUE
        if finding.classification is CompatibilityClassification.STRUCTURAL_TRANSFORMATION_REQUIRED:
            return TransformationStepType.REORDER
        if finding.classification is CompatibilityClassification.UNSUPPORTED:
            return TransformationStepType.UNSUPPORTED
        return TransformationStepType.UNKNOWN

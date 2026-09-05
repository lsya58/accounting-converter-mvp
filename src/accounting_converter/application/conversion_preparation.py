from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from accounting_converter.application.compatibility import (
    FormatCompatibilityAnalyzer,
    Lossiness,
    TransformationPlan,
    TransformationStep,
    TransformationStepType,
)
from accounting_converter.application.conversion import ConversionRequest, ConversionResult, ConversionService
from accounting_converter.application.mapping_review import (
    MappingRequirementExtractor,
    MappingRequirementSet,
    mapping_requirements_to_observed_preflight,
)
from accounting_converter.application.profile_preflight import (
    ConversionPreflightService,
    PreflightResult,
    ProfilePreflightStatus,
    mapping_rule_set_from_profile,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.format_metadata import FormatIdentity, SchemaDefinition
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.normalization import NormalizationScope
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    AdapterLookupResult,
    AdapterRegistry,
)


class TransformationSupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_PROFILE = "SUPPORTED_WITH_PROFILE"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    ADAPTER_RESPONSIBILITY = "ADAPTER_RESPONSIBILITY"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class ConversionReadinessStatus(str, Enum):
    READY = "READY"
    REQUIRES_MAPPING = "REQUIRES_MAPPING"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    PROFILE_INVALID = "PROFILE_INVALID"
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
    UNSUPPORTED_TRANSFORMATION = "UNSUPPORTED_TRANSFORMATION"
    LOSSY_CONFIRMATION_REQUIRED = "LOSSY_CONFIRMATION_REQUIRED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TransformationStepSupport:
    step: TransformationStep
    status: TransformationSupportStatus
    reason: str


@dataclass(frozen=True)
class AdapterAvailability:
    input_status: AdapterAvailabilityStatus
    output_status: AdapterAvailabilityStatus

    @property
    def exact_pair_available(self) -> bool:
        return (
            self.input_status is AdapterAvailabilityStatus.EXACT
            and self.output_status is AdapterAvailabilityStatus.EXACT
        )


@dataclass(frozen=True)
class ConversionReadinessResult:
    status: ConversionReadinessStatus
    source_format: FormatIdentity
    target_format: FormatIdentity
    compatibility_report: object
    transformation_plan: TransformationPlan
    profile_preflight_result: PreflightResult
    mapping_requirements: MappingRequirementSet
    transformation_support: tuple[TransformationStepSupport, ...]
    adapter_availability: AdapterAvailability
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def unresolved_mapping_count(self) -> int:
        return self.mapping_requirements.unresolved_count

    @property
    def conversion_enabled(self) -> bool:
        return self.status is ConversionReadinessStatus.READY


class TransformationSupportEvaluator:
    def evaluate(
        self,
        plan: TransformationPlan,
        saved_profile: ConversionProfile | None,
    ) -> tuple[TransformationStepSupport, ...]:
        return tuple(
            self._evaluate_step(step, saved_profile)
            for step in plan.steps
        )

    def _evaluate_step(
        self,
        step: TransformationStep,
        saved_profile: ConversionProfile | None,
    ) -> TransformationStepSupport:
        if step.step_type in {TransformationStepType.COPY, TransformationStepType.REORDER}:
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.ADAPTER_RESPONSIBILITY,
                reason="Format-specific execution belongs to adapters.",
            )
        if step.step_type in {
            TransformationStepType.MASTER_MAPPING,
            TransformationStepType.TAX_MAPPING,
        }:
            if saved_profile is not None:
                return TransformationStepSupport(
                    step=step,
                    status=TransformationSupportStatus.SUPPORTED_WITH_PROFILE,
                    reason="Confirmed profile mappings can support this step.",
                )
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.REQUIRES_CONFIRMATION,
                reason="Human-confirmed mappings are required.",
            )
        if step.step_type in {
            TransformationStepType.DATE_FORMAT,
            TransformationStepType.NUMERIC_FORMAT,
            TransformationStepType.NORMALIZE_TEXT,
        }:
            if self._has_auto_normalization(saved_profile):
                return TransformationStepSupport(
                    step=step,
                    status=TransformationSupportStatus.SUPPORTED_WITH_PROFILE,
                    reason="A deterministic profile normalization rule is available.",
                )
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.UNKNOWN,
                reason="Normalization execution engine is not implemented yet.",
            )
        if step.step_type is TransformationStepType.GROUPING_TRANSFORMATION:
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.ADAPTER_RESPONSIBILITY,
                reason="Grouping transformation requires a verified adapter.",
            )
        if step.step_type is TransformationStepType.DEFAULT_VALUE:
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.REQUIRES_CONFIRMATION,
                reason="Default values require explicit human confirmation.",
            )
        if step.step_type is TransformationStepType.UNSUPPORTED:
            return TransformationStepSupport(
                step=step,
                status=TransformationSupportStatus.UNSUPPORTED,
                reason="Compatibility analyzer marked this step unsupported.",
            )
        return TransformationStepSupport(
            step=step,
            status=TransformationSupportStatus.UNKNOWN,
            reason="Transformation step support is unknown.",
        )

    def _has_auto_normalization(
        self,
        saved_profile: ConversionProfile | None,
    ) -> bool:
        if saved_profile is None:
            return False
        return any(
            rule.can_auto_apply
            and rule.scope is NormalizationScope.SAFE_TEXT_NORMALIZATION
            for rule in saved_profile.normalization_rules
        )


class ConversionPreparationService:
    def __init__(
        self,
        compatibility_analyzer: FormatCompatibilityAnalyzer | None = None,
        mapping_extractor: MappingRequirementExtractor | None = None,
        preflight_service: ConversionPreflightService | None = None,
        support_evaluator: TransformationSupportEvaluator | None = None,
        adapter_registry: AdapterRegistry | None = None,
        production_adapters_only: bool = True,
    ) -> None:
        self.compatibility_analyzer = compatibility_analyzer or FormatCompatibilityAnalyzer()
        self.mapping_extractor = mapping_extractor or MappingRequirementExtractor()
        self.preflight_service = preflight_service or ConversionPreflightService()
        self.support_evaluator = support_evaluator or TransformationSupportEvaluator()
        self.adapter_registry = adapter_registry or AdapterRegistry()
        self.production_adapters_only = production_adapters_only

    def prepare(
        self,
        source_schema: SchemaDefinition,
        target_schema: SchemaDefinition,
        journal_entries: tuple[JournalEntry, ...],
        saved_profile: ConversionProfile | None = None,
    ) -> ConversionReadinessResult:
        compatibility_report = self.compatibility_analyzer.analyze(
            source_schema,
            target_schema,
        )
        transformation_plan = self.compatibility_analyzer.build_transformation_plan(
            compatibility_report
        )
        mapping_requirements = self.mapping_extractor.extract(
            journal_entries,
            saved_profile,
        )
        profile_preflight = self.preflight_service.check(
            source_format_candidate=source_schema.identity,
            target_format_candidate=target_schema.identity,
            observed_mapping_requirements=mapping_requirements_to_observed_preflight(
                mapping_requirements
            ),
            saved_profile=saved_profile,
        )
        transformation_support = self.support_evaluator.evaluate(
            transformation_plan,
            saved_profile,
        )
        input_lookup = self.adapter_registry.get_exact_input(
            source_schema.identity,
            production_only=self.production_adapters_only,
        )
        output_lookup = self.adapter_registry.get_exact_output(
            target_schema.identity,
            production_only=self.production_adapters_only,
        )
        adapter_availability = AdapterAvailability(
            input_status=input_lookup.status,
            output_status=output_lookup.status,
        )
        status, reasons = self._status(
            compatibility_report.overall_lossiness,
            profile_preflight,
            transformation_support,
            adapter_availability,
        )
        return ConversionReadinessResult(
            status=status,
            source_format=source_schema.identity,
            target_format=target_schema.identity,
            compatibility_report=compatibility_report,
            transformation_plan=transformation_plan,
            profile_preflight_result=profile_preflight,
            mapping_requirements=mapping_requirements,
            transformation_support=transformation_support,
            adapter_availability=adapter_availability,
            blocking_reasons=tuple(reasons),
            warnings=tuple(
                support.reason
                for support in transformation_support
                if support.status is TransformationSupportStatus.UNKNOWN
            ),
        )

    def _status(
        self,
        lossiness: Lossiness,
        profile_preflight: PreflightResult,
        transformation_support: tuple[TransformationStepSupport, ...],
        adapter_availability: AdapterAvailability,
    ) -> tuple[ConversionReadinessStatus, list[str]]:
        reasons: list[str] = []
        if profile_preflight.status is ProfilePreflightStatus.FORMAT_MISMATCH:
            return ConversionReadinessStatus.FORMAT_MISMATCH, [
                "Profile format identity does not match selected schemas."
            ]
        if profile_preflight.status is ProfilePreflightStatus.PROFILE_INVALID:
            return ConversionReadinessStatus.PROFILE_INVALID, [
                "Profile is invalid."
            ]
        if profile_preflight.status is ProfilePreflightStatus.UNSUPPORTED:
            return ConversionReadinessStatus.PROFILE_INVALID, [
                "Profile schema version is unsupported."
            ]
        if lossiness is Lossiness.LOSSY:
            return ConversionReadinessStatus.LOSSY_CONFIRMATION_REQUIRED, [
                "Compatibility report indicates possible information loss."
            ]
        if any(
            support.status is TransformationSupportStatus.UNSUPPORTED
            for support in transformation_support
        ):
            return ConversionReadinessStatus.UNSUPPORTED_TRANSFORMATION, [
                "At least one transformation step is unsupported."
            ]
        if any(
            support.status is TransformationSupportStatus.UNKNOWN
            for support in transformation_support
        ):
            return ConversionReadinessStatus.UNSUPPORTED_TRANSFORMATION, [
                "At least one transformation step has unknown support."
            ]
        if profile_preflight.status is ProfilePreflightStatus.REQUIRES_MAPPING:
            return ConversionReadinessStatus.REQUIRES_MAPPING, [
                "Unknown mappings require human confirmation."
            ]
        if profile_preflight.status is ProfilePreflightStatus.UNKNOWN:
            reasons.append("Profile preflight is unknown.")
        if not adapter_availability.exact_pair_available:
            return ConversionReadinessStatus.ADAPTER_UNAVAILABLE, [
                "Exact input/output adapter pair is not available."
            ]
        if reasons:
            return ConversionReadinessStatus.UNKNOWN, reasons
        return ConversionReadinessStatus.READY, []


@dataclass(frozen=True)
class PreparedConversion:
    readiness: ConversionReadinessResult
    request: ConversionRequest
    conversion_service: ConversionService


class ConversionExecutionService:
    def execute(self, prepared: PreparedConversion) -> ConversionResult | None:
        if prepared.readiness.status is not ConversionReadinessStatus.READY:
            return None
        return prepared.conversion_service.convert(prepared.request)


from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.application.compatibility import (
    FormatCompatibilityAnalyzer,
    TransformationStep,
    TransformationStepType,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.conversion_preparation import (
    ConversionExecutionService,
    ConversionPreparationService,
    ConversionReadinessStatus,
    PreparedConversion,
    TransformationSupportEvaluator,
    TransformationSupportStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import (
    MappingConfirmationService,
    MappingRequirementExtractor,
)
from accounting_converter.application.output_validation import OutputValidationResult
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.format_metadata import (
    Capability,
    CapabilityStatus,
    EvidenceLevel,
    FieldDataType,
    FieldDefinition,
    FormatCapabilities,
    FormatDirection,
    FormatIdentity,
    SchemaDefinition,
    SemanticField,
)
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule, UnsupportedCompoundStructureRule
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    AdapterRegistration,
    AdapterRegistry,
    production_adapter_registry,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    UnsupportedProfileVersionError,
)
from tests.support.demo_adapters import (
    DEMO_HEADER,
    DemoInputAdapter,
    DemoOutputAdapter,
    DemoOutputValidator,
    DemoStructuralValidator,
)


class MappingPreparationAndAdapterRegistryTests(unittest.TestCase):
    def test_mapping_requirement_extraction_aggregates_values_and_ignores_empty(self) -> None:
        entries = (
            self.entry(
                "J001",
                debit_account="売掛金",
                debit_sub="カード",
                debit_department="店舗",
                debit_tax="課税売上",
                credit_account="売上",
                row=2,
            ),
            self.entry(
                "J002",
                debit_account="売掛金",
                debit_sub="カード",
                debit_department="",
                debit_tax="課税売上",
                credit_account="売上",
                row=3,
            ),
        )

        requirements = MappingRequirementExtractor().extract(entries)
        review = MappingRequirementExtractor().build_review(requirements)

        account = self._find(requirements.accounts, "売掛金")
        tax = self._find(requirements.tax_categories, "課税売上")
        sub = requirements.subaccounts[0]
        self.assertEqual(account.occurrence_count, 2)
        self.assertEqual(tax.occurrence_count, 2)
        self.assertEqual(sub.source_value, "カード")
        self.assertEqual(sub.parent_account, "売掛金")
        self.assertEqual(sub.side, "DEBIT")
        self.assertEqual(sub.source_row_reference_count, 2)
        self.assertEqual(requirements.departments[0].source_value, "店舗")
        self.assertTrue(all(item.requires_user_confirmation for item in review.items))
        self.assertNotIn("secret", repr(review))
        self.assertNotIn("100", repr(review))

    def test_context_aware_subaccount_same_parent_is_one_requirement(self) -> None:
        entries = (
            self.entry("J001", debit_account="売掛金", debit_sub="カード", row=2),
            self.entry("J002", debit_account="売掛金", debit_sub="カード", row=3),
        )

        requirements = MappingRequirementExtractor().extract(entries)

        self.assertEqual(len(requirements.subaccounts), 1)
        self.assertEqual(requirements.subaccounts[0].occurrence_count, 2)

    def test_context_aware_subaccount_different_parent_is_separate_requirement(self) -> None:
        entries = (
            self.entry("J001", debit_account="売掛金", debit_sub="カード", row=2),
            self.entry("J002", debit_account="未収入金", debit_sub="カード", row=3),
        )

        requirements = MappingRequirementExtractor().extract(entries)

        self.assertEqual(len(requirements.subaccounts), 2)
        self.assertEqual(
            {item.parent_account for item in requirements.subaccounts},
            {"売掛金", "未収入金"},
        )

    def test_context_mapping_conflict_is_not_silently_resolved(self) -> None:
        key = MappingKey(MappingType.SUBACCOUNT, "カード", parent_account="売掛金", side="DEBIT")
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile(
                subaccount_context_mappings={
                    key: MappingValue(
                        "カード",
                        "JDLカード",
                        MappingStatus.USER_CONFIRMED,
                        parent_account="別科目",
                    )
                }
            )

            with self.assertRaises(ValueError):
                store.create(profile)

    def test_schema_version_two_is_not_reinterpreted(self) -> None:
        store = ConversionProfileStore(Path("/tmp/no-write-needed"))
        text = store.to_json_text(self.profile()).replace('"schema_version": "3"', '"schema_version": "2"')

        with self.assertRaises(UnsupportedProfileVersionError):
            store.from_json_text(text)

    def test_explicit_confirmation_becomes_user_confirmed_and_round_trips(self) -> None:
        key = MappingKey(MappingType.ACCOUNT, "現金")
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.profile(account_mappings={})
            store.create(profile)

            updated = MappingConfirmationService(store).confirm_mapping(
                profile.profile_id,
                key,
                "JDL現金",
            )
            loaded = store.get(profile.profile_id)

        self.assertEqual(updated.account_mappings["現金"].status, MappingStatus.USER_CONFIRMED)
        self.assertEqual(loaded.account_mappings["現金"].target_value, "JDL現金")

    def test_unresolved_remains_unresolved_until_explicit_confirmation(self) -> None:
        entries = (self.entry("J001", debit_account="現金"),)

        requirements = MappingRequirementExtractor().extract(entries, self.profile(account_mappings={}))

        self.assertEqual(requirements.accounts[0].current_mapping_status, MappingStatus.UNRESOLVED)
        self.assertTrue(requirements.accounts[0].requires_confirmation)

    def test_changed_mapping_requires_explicit_update(self) -> None:
        key = MappingKey(MappingType.ACCOUNT, "現金")
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            store.create(self.profile())
            service = MappingConfirmationService(store)

            service.confirm_mapping("profile-001", key, "JDL現金2")

            self.assertEqual(store.get("profile-001").account_mappings["現金"].target_value, "JDL現金2")

    def test_invalid_empty_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            store.create(self.profile())

            with self.assertRaises(ValueError):
                MappingConfirmationService(store).confirm_mapping(
                    "profile-001",
                    MappingKey(MappingType.ACCOUNT, "現金"),
                    " ",
                )

    def test_initial_then_next_month_profile_reuse_shows_only_new_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            store.create(self.profile(account_mappings={}))
            service = MappingConfirmationService(store)
            service.confirm_mapping("profile-001", MappingKey(MappingType.ACCOUNT, "現金"), "JDL現金")
            profile = store.get("profile-001")

            requirements = MappingRequirementExtractor().extract(
                (
                    self.entry("J001", debit_account="現金"),
                    self.entry("J002", debit_account="新科目"),
                ),
                profile,
            )

        self.assertFalse(self._find(requirements.accounts, "現金").requires_confirmation)
        self.assertTrue(self._find(requirements.accounts, "新科目").requires_confirmation)

    def test_preparation_no_profile_mapping_needed_requires_mapping(self) -> None:
        readiness = self.prepare(
            entries=(self.entry("J001", debit_account="現金"),),
            profile=None,
            registry=self.ready_registry(),
        )

        self.assertEqual(readiness.status, ConversionReadinessStatus.REQUIRES_MAPPING)

    def test_preparation_known_confirmed_mappings_pass_mapping_stage(self) -> None:
        readiness = self.prepare(
            entries=(self.entry("J001", debit_account="現金"),),
            profile=self.profile(),
            registry=self.ready_registry(),
        )

        self.assertEqual(readiness.profile_preflight_result.unknown_mapping_count, 0)

    def test_preparation_unknown_mapping_requires_mapping(self) -> None:
        readiness = self.prepare(
            entries=(self.entry("J001", debit_account="新科目"),),
            profile=self.profile(),
            registry=self.ready_registry(),
        )

        self.assertEqual(readiness.status, ConversionReadinessStatus.REQUIRES_MAPPING)

    def test_preparation_format_mismatch(self) -> None:
        source, target = self.schemas()
        mismatched_profile = self.profile(
            source_identity=FormatIdentity(
                vendor="Other",
                product="Other",
                format_name="Other",
                direction=FormatDirection.INPUT,
                evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
            )
        )

        readiness = ConversionPreparationService(adapter_registry=self.ready_registry()).prepare(
            source,
            target,
            (self.entry("J001", debit_account="現金"),),
            mismatched_profile,
        )

        self.assertEqual(readiness.status, ConversionReadinessStatus.FORMAT_MISMATCH)

    def test_preparation_lossy_requires_confirmation(self) -> None:
        source, target = self.lossy_schemas()

        readiness = ConversionPreparationService(adapter_registry=self.ready_registry()).prepare(
            source,
            target,
            (),
            self.profile(source_identity=source.identity, target_identity=target.identity),
        )

        self.assertEqual(readiness.status, ConversionReadinessStatus.LOSSY_CONFIRMATION_REQUIRED)

    def test_preparation_unsupported_step_blocks(self) -> None:
        step = TransformationStep(TransformationStepType.UNSUPPORTED, None, "unsupported")

        support = TransformationSupportEvaluator().evaluate(
            self.fake_plan(step),
            self.profile(),
        )

        self.assertEqual(support[0].status, TransformationSupportStatus.UNSUPPORTED)

    def test_preparation_no_adapter_is_unavailable(self) -> None:
        readiness = self.prepare(
            entries=(self.entry("J001", debit_account="現金"),),
            profile=self.profile(),
            registry=AdapterRegistry(),
        )

        self.assertEqual(readiness.status, ConversionReadinessStatus.ADAPTER_UNAVAILABLE)

    def test_adapter_registry_exact_registration_and_lookup(self) -> None:
        registry = AdapterRegistry()
        source, _ = self.schemas()
        registration = self.input_registration(source.identity)

        registry.register_input(registration)
        lookup = registry.get_exact_input(source.identity)

        self.assertEqual(lookup.status, AdapterAvailabilityStatus.EXACT)
        self.assertIs(lookup.registration, registration)

    def test_adapter_registry_exact_output_registration(self) -> None:
        registry = AdapterRegistry()
        _, target = self.schemas()
        registration = self.output_registration(target.identity)

        registry.register_output(registration)

        self.assertEqual(registry.get_exact_output(target.identity).status, AdapterAvailabilityStatus.EXACT)

    def test_adapter_registry_duplicate_registration_rejected(self) -> None:
        registry = AdapterRegistry()
        source, _ = self.schemas()
        registration = self.input_registration(source.identity)

        registry.register_input(registration)

        with self.assertRaises(ValueError):
            registry.register_input(registration)

    def test_adapter_registry_candidate_lookup_does_not_auto_select(self) -> None:
        registry = AdapterRegistry()
        source, _ = self.schemas()
        registry.register_input(self.input_registration(source.identity))
        other_version = FormatIdentity(
            vendor=source.identity.vendor,
            product=source.identity.product,
            format_name=source.identity.format_name,
            direction=FormatDirection.INPUT,
            evidence_level=source.identity.evidence_level,
            major_version="2",
        )

        lookup = registry.get_exact_input(other_version)

        self.assertEqual(lookup.status, AdapterAvailabilityStatus.CANDIDATE)
        self.assertIsNone(lookup.registration)

    def test_adapter_registry_unsupported_version_unavailable_as_exact_pair(self) -> None:
        registry = self.ready_registry()
        source, target = self.schemas()
        other_version = FormatIdentity(
            vendor=source.identity.vendor,
            product=source.identity.product,
            format_name=source.identity.format_name,
            direction=FormatDirection.INPUT,
            evidence_level=source.identity.evidence_level,
            major_version="999",
        )

        self.assertFalse(registry.has_conversion_pair(other_version, target.identity))

    def test_production_registry_does_not_include_demo_adapters(self) -> None:
        source, target = self.schemas()

        registry = production_adapter_registry()

        self.assertFalse(registry.has_conversion_pair(source.identity, target.identity))

    def test_observed_output_adapter_is_not_production_eligible(self) -> None:
        registry = AdapterRegistry()
        _, target = self.schemas()
        observed_target = FormatIdentity(
            vendor=target.identity.vendor,
            product=target.identity.product,
            format_name=target.identity.format_name,
            direction=FormatDirection.OUTPUT,
            evidence_level=EvidenceLevel.OBSERVED,
        )
        registry.register_output(
            AdapterRegistration(
                format_identity=observed_target,
                factory=DemoOutputAdapter,
                direction=FormatDirection.OUTPUT,
                evidence_level=EvidenceLevel.OBSERVED,
                production_enabled=True,
            )
        )

        self.assertEqual(
            registry.get_exact_output(observed_target).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def test_ready_executes_existing_conversion_service_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            output_path = Path(tmpdir) / "output.csv"
            self.write_demo_csv(input_path)
            service = self.demo_conversion_service()
            request = ConversionRequest(
                input_path=input_path,
                output_path=output_path,
                input_profile=self.demo_input_profile(),
                output_profile=self.demo_output_profile(),
            )
            readiness = self.prepare(
                entries=(self.entry("J001", debit_account="現金", credit_account="売上"),),
                profile=self.profile(),
                registry=self.ready_registry(),
            )

            result = ConversionExecutionService().execute(
                PreparedConversion(readiness, request, service)
            )

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertTrue(output_path.exists())

    def test_not_ready_does_not_call_conversion_service_or_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            output_path = Path(tmpdir) / "output.csv"
            input_path.write_text("secret input remains unchanged", encoding="utf-8")
            original = input_path.read_text(encoding="utf-8")
            service = self.demo_conversion_service()
            request = ConversionRequest(
                input_path=input_path,
                output_path=output_path,
                input_profile=self.demo_input_profile(),
                output_profile=self.demo_output_profile(),
            )
            readiness = self.prepare(
                entries=(self.entry("J001", debit_account="新科目"),),
                profile=self.profile(),
                registry=self.ready_registry(),
            )

            result = ConversionExecutionService().execute(
                PreparedConversion(readiness, request, service)
            )

            self.assertIsNone(result)
            self.assertFalse(output_path.exists())
            self.assertEqual(input_path.read_text(encoding="utf-8"), original)

    def test_context_mapping_reused_by_mapping_engine_and_decimal_precision_kept(self) -> None:
        key = MappingKey(MappingType.SUBACCOUNT, "カード", parent_account="売掛金", side="DEBIT")
        profile = self.profile(
            subaccount_context_mappings={
                key: MappingValue(
                    "カード",
                    "JDLカード",
                    MappingStatus.USER_CONFIRMED,
                    parent_account="売掛金",
                )
            }
        )
        entry = self.entry(
            "J001",
            debit_account="売掛金",
            debit_sub="カード",
            debit_amount=Decimal("100.01"),
            credit_amount=Decimal("100.01"),
        )

        result = MappingEngine(mapping_rule_set_from_profile(profile)).apply((entry,))

        self.assertEqual(result.unresolved_count, 0)
        self.assertEqual(result.entries[0].lines[0].sub_account, "JDLカード")
        self.assertEqual(result.entries[0].debit_total(), Decimal("100.01"))

    def test_output_overwrite_safety_still_maintained(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            output_path = Path(tmpdir) / "output.csv"
            self.write_demo_csv(input_path)
            output_path.write_text("existing", encoding="utf-8")

            result = self.demo_conversion_service().convert(
                ConversionRequest(
                    input_path=input_path,
                    output_path=output_path,
                    input_profile=self.demo_input_profile(),
                    output_profile=self.demo_output_profile(),
                )
            )

            self.assertEqual(result.status, ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing")

    def _find(self, requirements, source_value: str):
        return next(item for item in requirements if item.source_value == source_value)

    def entry(
        self,
        entry_id: str,
        debit_account: str = "現金",
        credit_account: str = "売上",
        debit_sub: str | None = None,
        debit_department: str | None = None,
        debit_tax: str | None = None,
        debit_amount: Decimal = Decimal("100"),
        credit_amount: Decimal = Decimal("100"),
        row: int = 2,
    ) -> JournalEntry:
        source = SourceReference("demo.csv", row, entry_id)
        return JournalEntry(
            id=entry_id,
            source_reference=source,
            date=date(2026, 9, 5),
            description="secret description",
            lines=[
                JournalLine(
                    Side.DEBIT,
                    debit_account,
                    debit_amount,
                    source,
                    sub_account=debit_sub,
                    department=debit_department,
                    tax_info=TaxInfo(category=debit_tax) if debit_tax else None,
                ),
                JournalLine(Side.CREDIT, credit_account, credit_amount, source),
            ],
        )

    def schemas(self) -> tuple[SchemaDefinition, SchemaDefinition]:
        source_identity = FormatIdentity(
            vendor="Demo",
            product="DemoSource",
            format_name="Demo CSV",
            direction=FormatDirection.INPUT,
            evidence_level=EvidenceLevel.OFFICIAL_DOCUMENTED,
            major_version="1",
        )
        target_identity = FormatIdentity(
            vendor="Demo",
            product="DemoTarget",
            format_name="Demo CSV",
            direction=FormatDirection.OUTPUT,
            evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
            major_version="1",
        )
        return self.schema(source_identity), self.schema(target_identity)

    def lossy_schemas(self) -> tuple[SchemaDefinition, SchemaDefinition]:
        source, target = self.schemas()
        target = SchemaDefinition(
            identity=target.identity,
            fields=tuple(
                field for field in target.fields if field.semantic_field is not SemanticField.DESCRIPTION
            ),
            capabilities=target.capabilities,
            delimiter=target.delimiter,
            encoding=target.encoding,
            has_header=target.has_header,
            column_count=target.column_count,
            date_formats=target.date_formats,
            numeric_format=target.numeric_format,
            blank_representation=target.blank_representation,
        )
        return source, target

    def schema(self, identity: FormatIdentity) -> SchemaDefinition:
        fields = (
            FieldDefinition("account", "account", SemanticField.DEBIT_ACCOUNT, 1, data_type=FieldDataType.TEXT),
            FieldDefinition("credit", "credit", SemanticField.CREDIT_ACCOUNT, 2, data_type=FieldDataType.TEXT),
            FieldDefinition("description", "description", SemanticField.DESCRIPTION, 3, data_type=FieldDataType.TEXT),
        )
        capabilities = FormatCapabilities(
            supports_subaccount=Capability(CapabilityStatus.SUPPORTED),
            supports_department=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_category=Capability(CapabilityStatus.SUPPORTED),
            supports_tax_amount=Capability(CapabilityStatus.SUPPORTED),
            supports_invoice_classification=Capability(CapabilityStatus.SUPPORTED),
            supports_description=Capability(CapabilityStatus.SUPPORTED),
            supports_voucher_number=Capability(CapabilityStatus.SUPPORTED),
            supports_compound_journal=Capability(CapabilityStatus.SUPPORTED),
            supports_multiple_debit_lines=Capability(CapabilityStatus.SUPPORTED),
            supports_multiple_credit_lines=Capability(CapabilityStatus.SUPPORTED),
            supports_header=Capability(CapabilityStatus.SUPPORTED),
            delimiter=",",
            encoding_candidates=("utf-8",),
        )
        return SchemaDefinition(
            identity=identity,
            fields=fields,
            capabilities=capabilities,
            delimiter=",",
            encoding="utf-8",
            has_header=CapabilityStatus.SUPPORTED,
            column_count=3,
            date_formats=("%Y-%m-%d",),
            numeric_format="decimal",
            blank_representation="empty",
        )

    def profile(
        self,
        account_mappings: dict[str, MappingValue] | None = None,
        subaccount_context_mappings: dict[MappingKey, MappingValue] | None = None,
        source_identity: FormatIdentity | None = None,
        target_identity: FormatIdentity | None = None,
    ) -> ConversionProfile:
        source, target = self.schemas()
        return ConversionProfile(
            profile_id="profile-001",
            profile_name="Preparation test profile",
            source_format_identity=source_identity or source.identity,
            target_format_identity=target_identity or target.identity,
            account_mappings=(
                account_mappings
                if account_mappings is not None
                else {
                    "現金": MappingValue("現金", "JDL現金", MappingStatus.USER_CONFIRMED),
                    "売掛金": MappingValue("売掛金", "JDL売掛金", MappingStatus.USER_CONFIRMED),
                    "売上": MappingValue("売上", "JDL売上", MappingStatus.USER_CONFIRMED),
                }
            ),
            subaccount_context_mappings=subaccount_context_mappings or {},
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

    def ready_registry(self) -> AdapterRegistry:
        source, target = self.schemas()
        registry = AdapterRegistry()
        registry.register_input(self.input_registration(source.identity))
        registry.register_output(self.output_registration(target.identity))
        return registry

    def input_registration(self, identity: FormatIdentity) -> AdapterRegistration:
        return AdapterRegistration(
            format_identity=identity,
            factory=DemoInputAdapter,
            direction=FormatDirection.INPUT,
            evidence_level=identity.evidence_level,
            production_enabled=True,
        )

    def output_registration(self, identity: FormatIdentity) -> AdapterRegistration:
        return AdapterRegistration(
            format_identity=identity,
            factory=DemoOutputAdapter,
            direction=FormatDirection.OUTPUT,
            evidence_level=EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
            verified_by_real_import=True,
            production_enabled=True,
        )

    def prepare(
        self,
        entries: tuple[JournalEntry, ...],
        profile: ConversionProfile | None,
        registry: AdapterRegistry,
    ):
        source, target = self.schemas()
        return ConversionPreparationService(adapter_registry=registry).prepare(
            source,
            target,
            entries,
            profile,
        )

    def fake_plan(self, step: TransformationStep):
        source, target = self.schemas()
        report = FormatCompatibilityAnalyzer().analyze(source, target)
        return FormatCompatibilityAnalyzer().build_transformation_plan(report).__class__(
            source_schema_id=source.identity.stable_key,
            target_schema_id=target.identity.stable_key,
            steps=(step,),
            lossiness=report.overall_lossiness,
            executable_without_confirmation=False,
        )

    def demo_input_profile(self) -> FormatProfile:
        return FormatProfile("DemoSource", "DemoInput", "test", "demo-input", "utf-8")

    def demo_output_profile(self) -> FormatProfile:
        return FormatProfile("DemoTarget", "DemoOutput", "test", "demo-output", "utf-8")

    def demo_conversion_service(self) -> ConversionService:
        return ConversionService(
            input_adapter=DemoInputAdapter(),
            structural_validator=DemoStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(self.profile())),
            business_validator=ValidationPipeline(
                [
                    BalanceRule(),
                    UnsupportedCompoundStructureRule(compound_supported=False),
                ]
            ),
            output_adapter=DemoOutputAdapter(),
            output_validator=DemoOutputValidator(),
        )

    def write_demo_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DEMO_HEADER)
            writer.writerow(
                (
                    "J001",
                    "2026-09-05",
                    "現金",
                    "100",
                    "売上",
                    "100",
                    "secret demo description",
                    "",
                )
            )


if __name__ == "__main__":
    unittest.main()

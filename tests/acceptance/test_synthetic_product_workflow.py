from __future__ import annotations

import csv
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.base import OutputAdapter
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
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import (
    MappingConfirmationService,
    MappingRequirement,
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
from accounting_converter.domain.validation import BalanceRule, Severity, UnsupportedCompoundStructureRule, ValidationResult
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    AdapterRegistration,
    AdapterRegistry,
)
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


SYNTHETIC_HEADER = (
    "id",
    "date",
    "debit_account",
    "debit_subaccount",
    "debit_department",
    "debit_tax",
    "debit_amount",
    "credit_account",
    "credit_subaccount",
    "credit_department",
    "credit_tax",
    "credit_amount",
    "description",
)


class SyntheticStructuralValidator:
    def validate(self, path: Path, profile: FormatProfile) -> list[ValidationResult]:
        _ = profile
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows or tuple(rows[0]) != SYNTHETIC_HEADER:
            return [
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="SYNTHETIC-HEADER",
                    message="Synthetic header mismatch.",
                    field="header",
                )
            ]
        return []


class SyntheticInputAdapter(InputAdapter):
    def supports(self, path: Path, profile: FormatProfile) -> bool:
        _ = profile
        return path.suffix.lower() == ".csv"

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        _ = profile
        with path.open("r", encoding="utf-8", newline="") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        _ = profile
        entries: list[JournalEntry] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                source = SourceReference(path.name, row_number, row["id"])
                entries.append(
                    JournalEntry(
                        id=row["id"],
                        source_reference=source,
                        date=date.fromisoformat(row["date"]),
                        description=row["description"],
                        lines=[
                            JournalLine(
                                side=Side.DEBIT,
                                account=row["debit_account"],
                                sub_account=row["debit_subaccount"] or None,
                                department=row["debit_department"] or None,
                                tax_info=(
                                    TaxInfo(category=row["debit_tax"])
                                    if row["debit_tax"]
                                    else None
                                ),
                                amount=Decimal(row["debit_amount"]),
                                source_reference=source,
                            ),
                            JournalLine(
                                side=Side.CREDIT,
                                account=row["credit_account"],
                                sub_account=row["credit_subaccount"] or None,
                                department=row["credit_department"] or None,
                                tax_info=(
                                    TaxInfo(category=row["credit_tax"])
                                    if row["credit_tax"]
                                    else None
                                ),
                                amount=Decimal(row["credit_amount"]),
                                source_reference=source,
                            ),
                        ],
                    )
                )
        return entries


class SyntheticOutputAdapter(OutputAdapter):
    def write(
        self,
        entries: Sequence[JournalEntry],
        destination: Path,
        profile: FormatProfile,
    ) -> None:
        _ = profile
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("id", "debit_total", "credit_total", "line_count"))
            for entry in entries:
                writer.writerow(
                    (
                        entry.id,
                        str(entry.debit_total()),
                        str(entry.credit_total()),
                        len(entry.lines),
                    )
                )


class SyntheticOutputValidator:
    def validate(
        self,
        path: Path,
        expected_entries: Sequence[JournalEntry],
        profile: FormatProfile,
    ) -> OutputValidationResult:
        _ = profile
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        success = len(rows) == len(expected_entries)
        return OutputValidationResult(
            success=success,
            record_count=len(rows),
            journal_count=len(rows),
            debit_total=sum((Decimal(row["debit_total"]) for row in rows), Decimal("0")),
            credit_total=sum((Decimal(row["credit_total"]) for row in rows), Decimal("0")),
            validation_results=() if success else (
                ValidationResult(
                    severity=Severity.ERROR,
                    rule_id="SYNTHETIC-OUTPUT-COUNT",
                    message="Output count mismatch.",
                ),
            ),
        )


@dataclass(frozen=True)
class WorkflowHarness:
    root: Path
    store: ConversionProfileStore
    source_schema: SchemaDefinition
    target_schema: SchemaDefinition
    registry: AdapterRegistry


class SyntheticProductWorkflowAcceptanceTests(unittest.TestCase):
    def test_scenario_a_first_use_requires_mapping_then_ready_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir))
            input_path = harness.root / "first_month.csv"
            output_path = harness.root / "first_month_output.csv"
            self.write_input(input_path, self.first_month_rows())
            original_input = input_path.read_bytes()
            entries = SyntheticInputAdapter().read(input_path, self.input_profile())

            first_readiness = self.prepare(harness, entries, None)
            self.assertEqual(first_readiness.status, ConversionReadinessStatus.REQUIRES_MAPPING)

            profile = self.create_empty_profile(harness)
            self.confirm_all(harness.store, profile.profile_id, first_readiness.mapping_requirements.all_requirements())
            restarted_store = ConversionProfileStore(harness.root / "profiles")
            loaded_profile = restarted_store.get(profile.profile_id)
            second_readiness = self.prepare(harness, entries, loaded_profile)
            result = self.execute(second_readiness, input_path, output_path, loaded_profile)

            self.assertEqual(second_readiness.status, ConversionReadinessStatus.READY)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.input_journal_count, 3)
            self.assertEqual(result.output_journal_count, 3)
            self.assertEqual(result.debit_total, Decimal("300.03"))
            self.assertEqual(result.credit_total, Decimal("300.03"))
            self.assertTrue(output_path.exists())
            self.assertEqual(input_path.read_bytes(), original_input)
            self.assertNotIn("secret", result.verification_report)
            self.assertIn("input journal count: 3", result.verification_report)
            self.assertIn("output journal count: 3", result.verification_report)
            saved_json = (harness.root / "profiles" / f"{profile.profile_id}.json").read_text(encoding="utf-8")
            self.assertNotIn("300.03", saved_json)
            self.assertNotIn("secret", saved_json)

    def test_scenario_b_next_month_reuses_persisted_profile_without_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir))
            first_path = harness.root / "first.csv"
            next_path = harness.root / "next.csv"
            output_path = harness.root / "next_output.csv"
            self.write_input(first_path, self.first_month_rows())
            self.write_input(next_path, self.next_month_rows())
            profile = self.create_and_confirm_from_file(harness, first_path)
            restarted_profile = ConversionProfileStore(harness.root / "profiles").get(profile.profile_id)
            entries = SyntheticInputAdapter().read(next_path, self.input_profile())

            readiness = self.prepare(harness, entries, restarted_profile)
            result = self.execute(readiness, next_path, output_path, restarted_profile)

            self.assertEqual(readiness.status, ConversionReadinessStatus.READY)
            self.assertEqual(readiness.mapping_requirements.unresolved_count, 0)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.input_journal_count, 2)

    def test_scenario_c_new_account_blocks_then_succeeds_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir))
            first_path = harness.root / "first.csv"
            new_path = harness.root / "new_account.csv"
            blocked_output = harness.root / "blocked.csv"
            final_output = harness.root / "final.csv"
            self.write_input(first_path, self.first_month_rows())
            self.write_input(new_path, self.new_account_rows())
            profile = self.create_and_confirm_from_file(harness, first_path)
            entries = SyntheticInputAdapter().read(new_path, self.input_profile())

            blocked = self.prepare(harness, entries, profile)
            blocked_result = ConversionExecutionService().execute(
                PreparedConversion(
                    blocked,
                    self.request(new_path, blocked_output),
                    self.conversion_service(profile),
                )
            )

            self.assertEqual(blocked.status, ConversionReadinessStatus.REQUIRES_MAPPING)
            self.assertIsNone(blocked_result)
            self.assertFalse(blocked_output.exists())

            service = MappingConfirmationService(harness.store)
            service.confirm_mapping(profile.profile_id, MappingKey(MappingType.ACCOUNT, "新科目"), "JDL新科目")
            updated_profile = harness.store.get(profile.profile_id)
            ready = self.prepare(harness, entries, updated_profile)
            result = self.execute(ready, new_path, final_output, updated_profile)

            self.assertEqual(ready.status, ConversionReadinessStatus.READY)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)

    def test_scenario_d_same_subaccount_different_parent_is_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir))
            path = harness.root / "sub_context.csv"
            self.write_input(path, self.same_sub_different_parent_rows())
            entries = SyntheticInputAdapter().read(path, self.input_profile())

            requirements = MappingRequirementExtractor().extract(entries)

            self.assertEqual(len(requirements.subaccounts), 2)
            self.assertEqual(
                {item.parent_account for item in requirements.subaccounts},
                {"売掛金", "未払金"},
            )

    def test_scenario_e_same_subaccount_both_sides_is_one_mapping_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir))
            path = harness.root / "both_sides.csv"
            self.write_input(path, self.same_sub_both_sides_rows())
            entries = SyntheticInputAdapter().read(path, self.input_profile())

            requirements = MappingRequirementExtractor().extract(entries)

            self.assertEqual(len(requirements.subaccounts), 1)
            self.assertEqual(requirements.subaccounts[0].source_value, "PayPay")
            self.assertEqual(requirements.subaccounts[0].parent_account, "売掛金")
            self.assertEqual(requirements.subaccounts[0].side, "CREDIT,DEBIT")

    def test_scenario_f_lossy_never_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = self.harness(Path(tmpdir), lossy=True)
            profile = self.create_empty_profile(harness)

            readiness = self.prepare(harness, (), profile)

            self.assertEqual(readiness.status, ConversionReadinessStatus.LOSSY_CONFIRMATION_REQUIRED)

    def test_scenario_g_adapter_unavailable_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness = self.harness(root, registry=AdapterRegistry())
            input_path = root / "input.csv"
            output_path = root / "output.csv"
            self.write_input(input_path, self.first_month_rows())
            profile = self.create_and_confirm_from_file(harness, input_path)
            entries = SyntheticInputAdapter().read(input_path, self.input_profile())

            readiness = self.prepare(harness, entries, profile)
            result = ConversionExecutionService().execute(
                PreparedConversion(
                    readiness,
                    self.request(input_path, output_path),
                    self.conversion_service(profile),
                )
            )

            self.assertEqual(readiness.status, ConversionReadinessStatus.ADAPTER_UNAVAILABLE)
            self.assertIsNone(result)
            self.assertFalse(output_path.exists())

    def test_scenario_h_output_adapter_evidence_controls_production_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            observed_registry = self.registry(output_evidence=EvidenceLevel.OBSERVED)
            observed = self.harness(root, registry=observed_registry)
            profile = self.create_empty_profile(observed)
            blocked = self.prepare(observed, (), profile)

            verified = self.harness(root, registry=self.registry())
            ready = self.prepare(verified, (), profile)

            self.assertEqual(blocked.adapter_availability.output_status, AdapterAvailabilityStatus.UNAVAILABLE)
            self.assertEqual(blocked.status, ConversionReadinessStatus.ADAPTER_UNAVAILABLE)
            self.assertEqual(ready.adapter_availability.output_status, AdapterAvailabilityStatus.EXACT)
            self.assertEqual(ready.status, ConversionReadinessStatus.READY)

    def test_context_mapping_serialization_round_trip_keeps_parent_not_side_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ConversionProfileStore(Path(tmpdir))
            profile = self.create_empty_profile(WorkflowHarness(Path(tmpdir), store, *self.schemas(), self.registry()))
            service = MappingConfirmationService(store)
            service.confirm_mapping(
                profile.profile_id,
                MappingKey(MappingType.SUBACCOUNT, "カード", parent_account="売掛金", side="DEBIT"),
                "JDLカード",
            )

            loaded = ConversionProfileStore(Path(tmpdir)).get(profile.profile_id)
            keys = tuple(loaded.subaccount_context_mappings.keys())

            self.assertEqual(len(keys), 1)
            self.assertEqual(keys[0].parent_account, "売掛金")
            self.assertIsNone(keys[0].side)

    def harness(
        self,
        root: Path,
        registry: AdapterRegistry | None = None,
        lossy: bool = False,
    ) -> WorkflowHarness:
        source, target = self.schemas(lossy=lossy)
        return WorkflowHarness(
            root=root,
            store=ConversionProfileStore(root / "profiles"),
            source_schema=source,
            target_schema=target,
            registry=registry or self.registry(),
        )

    def schemas(self, lossy: bool = False) -> tuple[SchemaDefinition, SchemaDefinition]:
        source = self.schema(self.identity("SyntheticSource", FormatDirection.INPUT, EvidenceLevel.OFFICIAL_DOCUMENTED))
        target_fields = tuple(
            field for field in source.fields if not (lossy and field.semantic_field is SemanticField.DESCRIPTION)
        )
        target = SchemaDefinition(
            identity=self.identity("SyntheticTarget", FormatDirection.OUTPUT, EvidenceLevel.VERIFIED_BY_REAL_IMPORT),
            fields=target_fields,
            capabilities=self.capabilities(),
            delimiter=",",
            encoding="utf-8",
            has_header=CapabilityStatus.SUPPORTED,
            column_count=len(target_fields),
            date_formats=("%Y-%m-%d",),
            numeric_format="decimal",
            blank_representation="empty",
        )
        return source, target

    def schema(self, identity: FormatIdentity) -> SchemaDefinition:
        fields = (
            FieldDefinition("debit_account", "debit_account", SemanticField.DEBIT_ACCOUNT, 1, data_type=FieldDataType.TEXT),
            FieldDefinition("debit_subaccount", "debit_subaccount", SemanticField.DEBIT_SUBACCOUNT, 2, data_type=FieldDataType.TEXT),
            FieldDefinition("debit_department", "debit_department", SemanticField.DEBIT_DEPARTMENT, 3, data_type=FieldDataType.TEXT),
            FieldDefinition("debit_tax", "debit_tax", SemanticField.DEBIT_TAX_CATEGORY, 4, data_type=FieldDataType.TEXT),
            FieldDefinition("credit_account", "credit_account", SemanticField.CREDIT_ACCOUNT, 5, data_type=FieldDataType.TEXT),
            FieldDefinition("credit_subaccount", "credit_subaccount", SemanticField.CREDIT_SUBACCOUNT, 6, data_type=FieldDataType.TEXT),
            FieldDefinition("credit_department", "credit_department", SemanticField.CREDIT_DEPARTMENT, 7, data_type=FieldDataType.TEXT),
            FieldDefinition("credit_tax", "credit_tax", SemanticField.CREDIT_TAX_CATEGORY, 8, data_type=FieldDataType.TEXT),
            FieldDefinition("description", "description", SemanticField.DESCRIPTION, 9, data_type=FieldDataType.TEXT),
        )
        return SchemaDefinition(
            identity=identity,
            fields=fields,
            capabilities=self.capabilities(),
            delimiter=",",
            encoding="utf-8",
            has_header=CapabilityStatus.SUPPORTED,
            column_count=len(fields),
            date_formats=("%Y-%m-%d",),
            numeric_format="decimal",
            blank_representation="empty",
        )

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
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

    def identity(
        self,
        product: str,
        direction: FormatDirection,
        evidence: EvidenceLevel,
    ) -> FormatIdentity:
        return FormatIdentity(
            vendor="Synthetic",
            product=product,
            format_name="Synthetic CSV",
            direction=direction,
            evidence_level=evidence,
            major_version="1",
        )

    def registry(
        self,
        output_evidence: EvidenceLevel = EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
    ) -> AdapterRegistry:
        source, target = self.schemas()
        registry = AdapterRegistry()
        registry.register_input(
            AdapterRegistration(
                format_identity=source.identity,
                factory=SyntheticInputAdapter,
                direction=FormatDirection.INPUT,
                evidence_level=source.identity.evidence_level,
                production_enabled=True,
            )
        )
        output_identity = target.identity
        if output_evidence is not EvidenceLevel.VERIFIED_BY_REAL_IMPORT:
            output_identity = self.identity("SyntheticTarget", FormatDirection.OUTPUT, output_evidence)
        registry.register_output(
            AdapterRegistration(
                format_identity=output_identity,
                factory=SyntheticOutputAdapter,
                direction=FormatDirection.OUTPUT,
                evidence_level=output_evidence,
                verified_by_real_import=output_evidence is EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
                production_enabled=True,
            )
        )
        return registry

    def create_empty_profile(self, harness: WorkflowHarness) -> ConversionProfile:
        profile = ConversionProfile(
            profile_id="profile-acceptance",
            profile_name="Synthetic acceptance",
            source_format_identity=harness.source_schema.identity,
            target_format_identity=harness.target_schema.identity,
            created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        harness.store.create(profile)
        return profile

    def create_and_confirm_from_file(
        self,
        harness: WorkflowHarness,
        input_path: Path,
    ) -> ConversionProfile:
        entries = SyntheticInputAdapter().read(input_path, self.input_profile())
        readiness = self.prepare(harness, entries, None)
        profile = self.create_empty_profile(harness)
        self.confirm_all(harness.store, profile.profile_id, readiness.mapping_requirements.all_requirements())
        return harness.store.get(profile.profile_id)

    def confirm_all(
        self,
        store: ConversionProfileStore,
        profile_id: str,
        requirements: tuple[MappingRequirement, ...],
    ) -> None:
        service = MappingConfirmationService(store)
        for requirement in requirements:
            service.confirm_mapping(
                profile_id,
                requirement.key,
                f"JDL-{requirement.source_value}",
            )

    def prepare(
        self,
        harness: WorkflowHarness,
        entries: Sequence[JournalEntry],
        profile: ConversionProfile | None,
    ):
        return ConversionPreparationService(adapter_registry=harness.registry).prepare(
            harness.source_schema,
            harness.target_schema,
            tuple(entries),
            profile,
        )

    def execute(
        self,
        readiness,
        input_path: Path,
        output_path: Path,
        profile: ConversionProfile,
    ):
        return ConversionExecutionService().execute(
            PreparedConversion(
                readiness,
                self.request(input_path, output_path),
                self.conversion_service(profile),
            )
        )

    def conversion_service(self, profile: ConversionProfile) -> ConversionService:
        return ConversionService(
            input_adapter=SyntheticInputAdapter(),
            structural_validator=SyntheticStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline(
                [
                    BalanceRule(),
                    UnsupportedCompoundStructureRule(compound_supported=True),
                ]
            ),
            output_adapter=SyntheticOutputAdapter(),
            output_validator=SyntheticOutputValidator(),
        )

    def request(self, input_path: Path, output_path: Path) -> ConversionRequest:
        return ConversionRequest(
            input_path=input_path,
            output_path=output_path,
            input_profile=self.input_profile(),
            output_profile=self.output_profile(),
        )

    def input_profile(self) -> FormatProfile:
        return FormatProfile("Synthetic", "SyntheticSource", "1", "synthetic", "utf-8")

    def output_profile(self) -> FormatProfile:
        return FormatProfile("Synthetic", "SyntheticTarget", "1", "synthetic", "utf-8")

    def write_input(self, path: Path, rows: list[tuple[str, ...]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(SYNTHETIC_HEADER)
            writer.writerows(rows)

    def first_month_rows(self) -> list[tuple[str, ...]]:
        return [
            ("J001", "2026-09-01", "売掛金", "PayPay", "店舗A", "課税", "100.01", "売上", "", "店舗A", "課税", "100.01", "secret alpha"),
            ("J002", "2026-09-02", "現金", "", "店舗A", "対象外", "100.01", "売掛金", "PayPay", "店舗A", "対象外", "100.01", "secret beta"),
            ("J003", "2026-09-02", "現金", "", "店舗A", "対象外", "100.01", "売掛金", "PayPay", "店舗A", "対象外", "100.01", "secret beta"),
        ]

    def next_month_rows(self) -> list[tuple[str, ...]]:
        return [
            ("J101", "2026-10-01", "売掛金", "PayPay", "店舗A", "課税", "200.02", "売上", "", "店舗A", "課税", "200.02", "secret next"),
            ("J102", "2026-10-02", "現金", "", "店舗A", "対象外", "50.05", "売掛金", "PayPay", "店舗A", "対象外", "50.05", "secret next"),
        ]

    def new_account_rows(self) -> list[tuple[str, ...]]:
        rows = self.next_month_rows()
        rows.append(("J103", "2026-10-03", "新科目", "", "店舗A", "対象外", "10.10", "現金", "", "店舗A", "対象外", "10.10", "secret new"))
        return rows

    def same_sub_different_parent_rows(self) -> list[tuple[str, ...]]:
        return [
            ("J201", "2026-09-01", "売掛金", "カード", "", "", "100", "売上", "", "", "", "100", "secret"),
            ("J202", "2026-09-02", "未払金", "カード", "", "", "100", "現金", "", "", "", "100", "secret"),
        ]

    def same_sub_both_sides_rows(self) -> list[tuple[str, ...]]:
        return [
            ("J301", "2026-09-01", "売掛金", "PayPay", "", "", "100", "売上", "", "", "", "100", "secret"),
            ("J302", "2026-09-02", "売上", "", "", "", "100", "売掛金", "PayPay", "", "", "100", "secret"),
        ]


if __name__ == "__main__":
    unittest.main()

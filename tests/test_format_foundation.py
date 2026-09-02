from __future__ import annotations

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.application.compatibility import (
    CompatibilityClassification,
    FormatCompatibilityAnalyzer,
    Lossiness,
    TransformationStepType,
)
from accounting_converter.domain.format_metadata import (
    CapabilityStatus,
    EvidenceLevel,
    FormatDirection,
    SemanticField,
)
from accounting_converter.domain.normalization import (
    NormalizationRule,
    NormalizationScope,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.profiles.known_formats import (
    default_format_schemas,
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_desktop_import_25_documented_schema,
    yayoi_next_documented_candidate_schema,
)
from accounting_converter.profiles.registry import FormatRegistry
from tests.support.adapter_contracts import (
    InputAdapterContractMixin,
    OutputAdapterContractMixin,
)
from tests.support.canonical_dataset import canonical_journal_entries
from tests.support.demo_adapters import (
    DEMO_HEADER,
    DemoInputAdapter,
    DemoOutputAdapter,
    DemoOutputValidator,
)


class FormatFoundationTests(unittest.TestCase):
    def test_format_identity_separates_official_observed_and_verified(self) -> None:
        yayoi = yayoi_desktop_import_25_documented_schema()
        jdl = jdl_ibex_cashbook_35_5_observed_schema_definition()

        self.assertEqual(yayoi.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(jdl.identity.evidence_level, EvidenceLevel.OBSERVED)
        self.assertNotEqual(yayoi.identity.stable_key, jdl.identity.stable_key)
        self.assertNotEqual(yayoi.identity.product, jdl.identity.product)

    def test_yayoi_next_25_and_27_can_coexist_without_assuming_yayoi_is_25(self) -> None:
        next_25 = yayoi_next_documented_candidate_schema(25)
        next_27 = yayoi_next_documented_candidate_schema(27)

        self.assertNotEqual(next_25.identity.stable_key, next_27.identity.stable_key)
        self.assertEqual(next_25.column_count, 25)
        self.assertEqual(next_27.column_count, 27)
        self.assertEqual(next_27.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)

    def test_capability_unknown_is_not_false(self) -> None:
        yayoi = yayoi_desktop_import_25_documented_schema()

        self.assertEqual(yayoi.capabilities.supports_header.status, CapabilityStatus.UNKNOWN)
        self.assertNotEqual(yayoi.capabilities.supports_header.status, CapabilityStatus.UNSUPPORTED)

    def test_registry_finds_candidates_without_auto_selecting(self) -> None:
        class Observation:
            dominant_column_count = 25
            delimiter = ","
            encoding = "utf-8"

        registry = FormatRegistry(default_format_schemas())

        candidates = registry.find_candidates(Observation())

        self.assertGreaterEqual(len(candidates), 1)
        self.assertLessEqual(candidates[0].confidence, 0.95)
        self.assertIn("column_count_match", candidates[0].reasons)

    def test_registry_filters_by_identity(self) -> None:
        registry = FormatRegistry(default_format_schemas())

        yayoi_inputs = registry.find(vendor="Yayoi", direction=FormatDirection.INPUT)

        self.assertTrue(yayoi_inputs)
        self.assertTrue(all(schema.identity.vendor == "Yayoi" for schema in yayoi_inputs))

    def test_compatibility_report_classifies_mapping_and_structure(self) -> None:
        source = yayoi_desktop_import_25_documented_schema()
        target = jdl_ibex_cashbook_35_5_observed_schema_definition()

        report = FormatCompatibilityAnalyzer().analyze(source, target)
        classes = {finding.classification for finding in report.findings}

        self.assertIn(CompatibilityClassification.MAPPING_REQUIRED, classes)
        self.assertIn(
            CompatibilityClassification.STRUCTURAL_TRANSFORMATION_REQUIRED,
            classes,
        )
        self.assertTrue(report.requires_human_confirmation)

    def test_transformation_plan_has_mapping_and_reorder_steps(self) -> None:
        analyzer = FormatCompatibilityAnalyzer()
        report = analyzer.analyze(
            yayoi_desktop_import_25_documented_schema(),
            jdl_ibex_cashbook_35_5_observed_schema_definition(),
        )

        plan = analyzer.build_transformation_plan(report)
        step_types = {step.step_type for step in plan.steps}

        self.assertIn(TransformationStepType.MASTER_MAPPING, step_types)
        self.assertIn(TransformationStepType.REORDER, step_types)
        self.assertFalse(plan.executable_without_confirmation)

    def test_lossy_when_source_field_has_no_target_field(self) -> None:
        source = yayoi_desktop_import_25_documented_schema()
        target = yayoi_next_documented_candidate_schema(25)

        report = FormatCompatibilityAnalyzer().analyze(source, target)

        self.assertEqual(report.overall_lossiness, Lossiness.LOSSY)
        self.assertTrue(
            any(
                finding.semantic_field is SemanticField.DESCRIPTION
                and finding.lossiness is Lossiness.LOSSY
                for finding in report.findings
            )
        )

    def test_safe_normalization_can_auto_apply_but_account_mapping_cannot(self) -> None:
        safe_rule = NormalizationRule(
            rule_id="NORM-UNICODE-NFKC",
            target_field=SemanticField.DESCRIPTION,
            scope=NormalizationScope.SAFE_TEXT_NORMALIZATION,
            deterministic=True,
            reversible=False,
            requires_confirmation=False,
            evidence=EvidenceLevel.OFFICIAL_DOCUMENTED,
            description="Unicode normalization configured by rule.",
        )
        account_rule = NormalizationRule(
            rule_id="MAP-ACCOUNT-NAME",
            target_field=SemanticField.DEBIT_ACCOUNT,
            scope=NormalizationScope.ACCOUNTING_SEMANTIC_MAPPING,
            deterministic=False,
            reversible=False,
            requires_confirmation=True,
            evidence=EvidenceLevel.INFERRED,
            description="Potential account mapping.",
        )

        self.assertTrue(safe_rule.can_auto_apply)
        self.assertFalse(account_rule.can_auto_apply)

    def test_canonical_dataset_preserves_invariants(self) -> None:
        entries = canonical_journal_entries()

        self.assertGreaterEqual(len(entries), 16)
        self.assertEqual(entries[-2].description, entries[-1].description)
        self.assertTrue(all(entry.source_reference.file_name for entry in entries))
        self.assertTrue(
            all(isinstance(line.amount, Decimal) for entry in entries for line in entry.lines)
        )

    def test_yayoi_official_profile_has_source_provenance(self) -> None:
        schema = yayoi_desktop_import_25_documented_schema()

        self.assertIsNotNone(schema.identity.source_reference)
        self.assertEqual(
            schema.identity.source_reference.evidence_level,
            EvidenceLevel.OFFICIAL_DOCUMENTED,
        )
        self.assertIsNotNone(schema.identity.source_reference.retrieved_at)


class DemoAdapterInputContractTests(InputAdapterContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.input_adapter = DemoInputAdapter()
        self.input_profile = FormatProfile(
            software="DemoSource",
            product="DemoInput",
            version="test",
            format_id="demo-input",
            encoding="utf-8",
        )

    def make_valid_input_file(self, directory: Path) -> Path:
        path = directory / "demo_input.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DEMO_HEADER)
            writer.writerow(("DUP-1", "2026-01-31", "現金", "100", "売上", "100", "same", ""))
            writer.writerow(("DUP-2", "2026-01-31", "現金", "100", "売上", "100", "same", ""))
        return path

    def make_invalid_input_file(self, directory: Path) -> Path:
        path = directory / "demo_invalid.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DEMO_HEADER)
            writer.writerow(("BAD", "2026-01-31", "現金", "not-number", "売上", "100", "", ""))
        return path


class DemoAdapterOutputContractTests(OutputAdapterContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.output_adapter = DemoOutputAdapter()
        self.output_validator = DemoOutputValidator()
        self.output_profile = FormatProfile(
            software="DemoTarget",
            product="DemoOutput",
            version="test",
            format_id="demo-output",
            encoding="utf-8",
        )

    def make_output_entries(self):
        return canonical_journal_entries()[:3]


if __name__ == "__main__":
    unittest.main()

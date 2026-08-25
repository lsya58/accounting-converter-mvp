from __future__ import annotations

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine, MappingRuleSet
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import (
    BalanceRule,
    UnsupportedCompoundStructureRule,
)

from tests.support.demo_adapters import (
    DEMO_HEADER,
    DemoInputAdapter,
    DemoOutputAdapter,
    DemoOutputValidator,
    DemoStructuralValidator,
    ExplodingDemoOutputAdapter,
)


class ConversionServiceE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.input_profile = FormatProfile(
            software="DemoSource",
            product="DemoInput",
            version="test",
            format_id="demo-input",
            encoding="utf-8",
        )
        self.output_profile = FormatProfile(
            software="DemoTarget",
            product="DemoOutput",
            version="test",
            format_id="demo-output",
            encoding="utf-8",
        )

    def make_service(
        self,
        rule_set: MappingRuleSet | None = None,
        output_validator: DemoOutputValidator | None = None,
        output_adapter: DemoOutputAdapter | None = None,
    ) -> ConversionService:
        return ConversionService(
            input_adapter=DemoInputAdapter(),
            structural_validator=DemoStructuralValidator(),
            mapping_engine=MappingEngine(rule_set or self.resolved_rule_set()),
            business_validator=ValidationPipeline(
                [
                    BalanceRule(),
                    UnsupportedCompoundStructureRule(compound_supported=False),
                ]
            ),
            output_adapter=output_adapter or DemoOutputAdapter(),
            output_validator=output_validator or DemoOutputValidator(),
        )

    def resolved_rule_set(self) -> MappingRuleSet:
        return MappingRuleSet(
            accounts={
                "売掛金": MappingValue("売掛金", "JDL売掛金", MappingStatus.RESOLVED),
                "現金": MappingValue("現金", "JDL現金", MappingStatus.USER_CONFIRMED),
                "売上": MappingValue("売上", "JDL売上", MappingStatus.RESOLVED),
                "旅費": MappingValue("旅費", "JDL旅費", MappingStatus.RESOLVED),
            },
            sub_accounts={},
            departments={},
            tax_categories={},
        )

    def unresolved_rule_set(self) -> MappingRuleSet:
        return MappingRuleSet(
            accounts={
                "現金": MappingValue("現金", "JDL現金", MappingStatus.RESOLVED),
                "売上": MappingValue("売上", "JDL売上", MappingStatus.RESOLVED),
            },
            sub_accounts={},
            departments={},
            tax_categories={},
        )

    def convert(
        self,
        tmpdir: str,
        rows: list[tuple[str, ...]],
        service=None,
        overwrite: bool = False,
    ):
        input_path = Path(tmpdir) / "input.csv"
        output_path = Path(tmpdir) / "output.csv"
        self.write_demo_csv(input_path, rows)
        original_input = input_path.read_bytes()
        result = (service or self.make_service()).convert(
            ConversionRequest(
                input_path=input_path,
                output_path=output_path,
                input_profile=self.input_profile,
                output_profile=self.output_profile,
                overwrite=overwrite,
            )
        )
        return result, input_path, output_path, original_input

    def write_demo_csv(self, path: Path, rows: list[tuple[str, ...]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DEMO_HEADER)
            writer.writerows(rows)

    def normal_rows(self, count: int = 10) -> list[tuple[str, ...]]:
        return [
            (
                f"J{i:03d}",
                "2026-08-24",
                "売掛金",
                "100",
                "売上",
                "100",
                f"secret memo {i}",
                "",
            )
            for i in range(1, count + 1)
        ]

    def test_success_10_journals_outputs_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result, input_path, output_path, original_input = self.convert(
                tmpdir,
                self.normal_rows(10),
            )

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(result.input_record_count, 10)
            self.assertEqual(result.input_journal_count, 10)
            self.assertEqual(result.output_record_count, 10)
            self.assertEqual(result.output_journal_count, 10)
            self.assertEqual(result.debit_total, Decimal("1000"))
            self.assertEqual(result.credit_total, Decimal("1000"))
            self.assertEqual(result.error_count, 0)
            self.assertEqual(result.unresolved_mapping_count, 0)
            self.assertEqual(result.output_path, output_path)
            self.assertTrue(output_path.exists())
            self.assertEqual(input_path.read_bytes(), original_input)
            self.assertIn("変換検証レポート", result.verification_report)
            self.assertIn("input record count: 10", result.verification_report)
            self.assertIn("Output Validation結果: success", result.verification_report)

    def test_structural_error_blocks_formal_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            output_path = Path(tmpdir) / "output.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(DEMO_HEADER)
                writer.writerow(("BROKEN", "2026-08-24"))

            result = self.make_service().convert(
                ConversionRequest(
                    input_path=input_path,
                    output_path=output_path,
                    input_profile=self.input_profile,
                    output_profile=self.output_profile,
                )
            )

            self.assertEqual(
                result.status,
                ConversionStatus.BLOCKED_BY_STRUCTURAL_VALIDATION,
            )
            self.assertFalse(output_path.exists())

    def test_unbalanced_journal_blocks_business_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                (
                    "J001",
                    "2026-08-24",
                    "売掛金",
                    "100",
                    "売上",
                    "90",
                    "secret unbalanced",
                    "",
                )
            ]
            result, _, output_path, _ = self.convert(tmpdir, rows)

            self.assertEqual(
                result.status,
                ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION,
            )
            self.assertTrue(any(item.rule_id == "VR-04" for item in result.validation_results))
            self.assertFalse(output_path.exists())

    def test_unresolved_mapping_blocks_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self.make_service(rule_set=self.unresolved_rule_set())
            result, _, output_path, _ = self.convert(
                tmpdir,
                self.normal_rows(1),
                service=service,
            )

            self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
            self.assertEqual(result.unresolved_mapping_count, 1)
            self.assertFalse(output_path.exists())

    def test_unsupported_compound_journal_blocks_with_vr15(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                (
                    "J001",
                    "2026-08-24",
                    "旅費",
                    "100",
                    "現金",
                    "100",
                    "secret compound",
                    "compound",
                )
            ]
            result, _, output_path, _ = self.convert(tmpdir, rows)

            self.assertEqual(
                result.status,
                ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION,
            )
            self.assertTrue(any(item.rule_id == "VR-15" for item in result.validation_results))
            self.assertFalse(output_path.exists())

    def test_one_error_in_10_does_not_partially_output_9(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = self.normal_rows(9)
            rows.append(
                (
                    "J010",
                    "2026-08-24",
                    "売掛金",
                    "100",
                    "売上",
                    "99",
                    "secret one bad",
                    "",
                )
            )
            result, _, output_path, _ = self.convert(tmpdir, rows)

            self.assertEqual(
                result.status,
                ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION,
            )
            self.assertFalse(output_path.exists())
            self.assertEqual(result.output_record_count, 0)

    def test_output_validation_failure_deletes_temp_and_blocks_formal_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self.make_service(
                output_validator=DemoOutputValidator(force_failure=True)
            )
            result, _, output_path, _ = self.convert(
                tmpdir,
                self.normal_rows(1),
                service=service,
            )

            self.assertEqual(result.status, ConversionStatus.OUTPUT_VALIDATION_FAILED)
            self.assertFalse(output_path.exists())
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_output_adapter_exception_is_system_error_without_formal_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self.make_service(output_adapter=ExplodingDemoOutputAdapter())
            result, _, output_path, _ = self.convert(
                tmpdir,
                self.normal_rows(1),
                service=service,
            )

            self.assertEqual(result.status, ConversionStatus.SYSTEM_ERROR)
            self.assertTrue(any(item.rule_id == "SYSTEM-ERROR" for item in result.validation_results))
            self.assertFalse(output_path.exists())
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_verification_report_has_required_fields_but_not_accounting_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _, _, _ = self.convert(tmpdir, self.normal_rows(1))

            report = result.verification_report
            self.assertIn("検証日時:", report)
            self.assertIn("システムバージョン:", report)
            self.assertIn("入力ファイル名: input.csv", report)
            self.assertIn("出力ファイル名: output.csv", report)
            self.assertIn("入力形式:", report)
            self.assertIn("出力形式:", report)
            self.assertIn("input journal count: 1", report)
            self.assertIn("output journal count: 1", report)
            self.assertIn("借方総額: 100", report)
            self.assertIn("貸方総額: 100", report)
            self.assertIn("Error件数: 0", report)
            self.assertIn("Warning件数: 0", report)
            self.assertIn("unresolved mapping件数: 0", report)
            self.assertNotIn("secret memo", report)
            self.assertNotIn("JDL売掛金", report)

    def test_input_file_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result, input_path, _, original_input = self.convert(
                tmpdir,
                self.normal_rows(3),
            )

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(input_path.read_bytes(), original_input)

    def test_existing_output_is_not_overwritten_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            output_path.write_text("existing output\n", encoding="utf-8")

            result, _, _, _ = self.convert(tmpdir, self.normal_rows(1))

            self.assertEqual(result.status, ConversionStatus.OUTPUT_PATH_ALREADY_EXISTS)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "existing output\n",
            )
            self.assertTrue(
                any(item.rule_id == "OUTPUT-PATH-EXISTS" for item in result.validation_results)
            )
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_existing_output_is_replaced_only_when_overwrite_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.csv"
            output_path.write_text("existing output\n", encoding="utf-8")

            result, _, _, _ = self.convert(
                tmpdir,
                self.normal_rows(1),
                overwrite=True,
            )

            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertNotEqual(
                output_path.read_text(encoding="utf-8"),
                "existing output\n",
            )
            self.assertIn("J001", output_path.read_text(encoding="utf-8"))

    def test_input_path_equal_output_path_is_rejected_and_input_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "same.csv"
            self.write_demo_csv(input_path, self.normal_rows(1))
            original_input = input_path.read_bytes()

            result = self.make_service().convert(
                ConversionRequest(
                    input_path=input_path,
                    output_path=input_path,
                    input_profile=self.input_profile,
                    output_profile=self.output_profile,
                    overwrite=True,
                )
            )

            self.assertEqual(result.status, ConversionStatus.INPUT_OUTPUT_PATH_CONFLICT)
            self.assertEqual(input_path.read_bytes(), original_input)
            self.assertTrue(
                any(
                    item.rule_id == "OUTPUT-INPUT-SAME-PATH"
                    for item in result.validation_results
                )
            )


if __name__ == "__main__":
    unittest.main()

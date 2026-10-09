from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import (
    MONEYFORWARD_OBSERVED_HEADER,
    MoneyForwardInputAdapter,
    MoneyForwardStructuralValidator,
)
from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlTargetContextBuilder,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.moneyforward_jdl_loss import (
    MoneyForwardToJdlLossRule,
)
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class MoneyForwardToJdlSyntheticE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.mf_schema = moneyforward_cloud_journal_export_observed_schema()
        self.mf_profile = FormatProfile(
            software="Money Forward",
            product="Money Forward クラウド会計",
            version="UNKNOWN",
            format_id=self.mf_schema.identity.stable_key,
            encoding="cp932",
        )
        self.jdl_profile = jdl_ibex_35_5_output_profile()
        self.codes = {
            "現金": "1001",
            "普通預金": "1002",
            "当座預金": "1003",
            "小口現金": "1004",
        }

    def test_simple_formal_pipeline_preserves_counts_totals_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", [self._row("1")])
            output = root / "jdl.csv"
            before = source.read_bytes()
            parsed = MoneyForwardInputAdapter().read(source, self.mf_profile)
            mapped = MappingEngine(
                mapping_rule_set_from_profile(self._conversion_profile())
            ).apply(parsed).entries
            result = self._convert(source, output, {"1": JdlEvidenceProfile.BASIC_1111})
            rows = self._output_rows(output)
            after = source.read_bytes()

        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertEqual((result.input_record_count, result.input_journal_count), (1, 1))
        self.assertEqual((result.output_record_count, result.output_journal_count), (1, 1))
        self.assertEqual((result.debit_total, result.credit_total), (Decimal("700"), Decimal("700")))
        self.assertEqual(before, after)
        self.assertEqual(rows[1][0], "1111")
        self.assertEqual(rows[1][2], "20261019")
        self.assertIn("入力ファイル名: mf.csv", result.verification_report)
        self.assertEqual(mapped[0].source_reference, parsed[0].source_reference)
        self.assertEqual(
            [line.source_reference for line in mapped[0].lines],
            [line.source_reference for line in parsed[0].lines],
        )
        self.assertEqual(mapped[0].metadata["evidence_id"], parsed[0].metadata["evidence_id"])

    def test_simple_pair_and_supported_1d3c_pass(self) -> None:
        cases = (
            (
                [self._row("1"), self._row("2", debit="当座預金", credit="小口現金", amount="900")],
                {"1": JdlEvidenceProfile.BASIC_1111, "2": JdlEvidenceProfile.BASIC_1111},
                (2, 2, Decimal("1600")),
            ),
            (
                [
                    self._row("3", debit_amount="1000", credit_amount="500"),
                    self._row("3", debit="", debit_amount="", credit="当座預金", credit_amount="300", description=""),
                    self._row("3", debit="", debit_amount="", credit="小口現金", credit_amount="200", description=""),
                ],
                {"3": JdlEvidenceProfile.COMPOUND_1D3C},
                (3, 1, Decimal("1000")),
            ),
        )
        for rows, routes, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", rows)
                output = root / "jdl.csv"
                result = self._convert(source, output, routes)
                self.assertEqual(result.status, ConversionStatus.SUCCESS)
                self.assertEqual(result.input_record_count, expected[0])
                self.assertEqual(result.input_journal_count, expected[1])
                self.assertEqual(result.debit_total, expected[2])
                self.assertTrue(output.exists())

    def test_unverified_compound_shapes_block_without_output(self) -> None:
        shapes = {
            "3D1C": [
                self._row("4", debit_amount="500", credit_amount="1000"),
                self._row("4", debit="当座預金", debit_amount="300", credit="", credit_amount="", description=""),
                self._row("4", debit="小口現金", debit_amount="200", credit="", credit_amount="", description=""),
            ],
            "2D2C": [
                self._row("5", debit_amount="600", credit_amount="700"),
                self._row("5", debit="当座預金", debit_amount="400", credit="小口現金", credit_amount="300", description=""),
            ],
            "3D3C": [
                self._row("6", debit_amount="500", credit_amount="400"),
                self._row("6", debit="当座預金", debit_amount="300", credit="小口現金", credit_amount="300", description=""),
                self._row("6", debit="小口現金", debit_amount="200", credit="普通預金", credit_amount="300", description=""),
            ],
        }
        for name, rows in shapes.items():
            with self.subTest(shape=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", rows)
                output = root / "blocked.csv"
                result = self._convert(source, output, {rows[0][0]: JdlEvidenceProfile.COMPOUND_1D3C})
                self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
                self.assertFalse(output.exists())

    def test_unknown_mapping_and_tax_mapping_block(self) -> None:
        cases = (
            (self._row("7", debit="未確認科目"), "account"),
            (self._row("8", debit_tax="対象外", credit_tax="対象外"), "tax_category"),
        )
        for row, field in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", [row])
                output = root / "blocked.csv"
                result = self._convert(source, output, {row[0]: JdlEvidenceProfile.BASIC_1111})
                self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
                self.assertTrue(any(item.field == field for item in result.validation_results))
                self.assertFalse(output.exists())

    def test_unconfirmed_subaccount_and_department_mapping_block(self) -> None:
        cases = (
            self._with_columns(self._row("12"), debit_sub="未確認補助"),
            self._with_columns(self._row("13"), debit_department="未確認部門"),
        )
        for row in cases:
            with self.subTest(transaction=row[0]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", [row])
                output = root / "blocked.csv"
                result = self._convert(source, output, {row[0]: JdlEvidenceProfile.BASIC_1111})
                self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
                self.assertFalse(output.exists())

    def test_lossy_moneyforward_fields_block_without_exposing_values(self) -> None:
        variants = (
            ("trade_partner", {"debit_partner": "架空取引先"}),
            ("tag", {"tags": "架空タグ"}),
            ("memo", {"memo": "架空メモ"}),
            ("invoice_classification", {"debit_invoice": "70%控除", "debit_tax": ""}),
        )
        for expected_field, changes in variants:
            with self.subTest(field=expected_field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", [self._row("9", **changes)])
                output = root / "blocked.csv"
                result = self._convert(source, output, {"9": JdlEvidenceProfile.BASIC_1111})
                self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION)
                matching = [item for item in result.validation_results if item.field == expected_field]
                self.assertEqual(len(matching), 1)
                self.assertIsNone(matching[0].input_value)
                self.assertFalse(output.exists())

    def test_conflicting_descriptions_are_losslessly_parsed_then_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(
                root / "mf.csv",
                [
                    self._row("14", debit_amount="350", credit_amount="350", description="架空A"),
                    self._row("14", debit_amount="350", credit_amount="350", description="架空B"),
                ],
            )
            output = root / "blocked.csv"
            result = self._convert(
                source, output, {"14": JdlEvidenceProfile.BASIC_1111}
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION)
        self.assertTrue(any(item.field == "description" for item in result.validation_results))
        self.assertFalse(output.exists())

    def test_invalid_target_context_blocks_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", [self._row("10")])
            output = root / "blocked.csv"
            result = self._convert(
                source,
                output,
                {"10": JdlEvidenceProfile.BASIC_1111},
                context=None,
                use_default_context=False,
            )
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_TARGET_CONTEXT)
        self.assertFalse(output.exists())

    def test_failure_does_not_replace_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", [self._row("11", tags="架空タグ")])
            output = root / "existing.csv"
            output.write_bytes(b"existing")
            result = self._convert(source, output, {"11": JdlEvidenceProfile.BASIC_1111}, overwrite=True)
            self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION)
            self.assertEqual(output.read_bytes(), b"existing")

    def test_production_registry_remains_unavailable_for_moneyforward(self) -> None:
        registry = production_adapter_registry()
        self.assertEqual(
            registry.get_exact_input(self.mf_schema.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )
        self.assertFalse(
            registry.has_conversion_pair(
                self.mf_schema.identity,
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            )
        )

    def _convert(self, source, output, assignments, *, context="DEFAULT", use_default_context=True, overwrite=False):
        profile = self._conversion_profile()
        target = jdl_ibex_cashbook_official_journal_import_schema_definition()
        registration = production_adapter_registry().get_exact_output(target.identity).registration
        assert registration is not None and registration.runtime_factory is not None
        service = ConversionService(
            input_adapter=MoneyForwardInputAdapter(),
            structural_validator=MoneyForwardStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), MoneyForwardToJdlLossRule())),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=ExplicitJdlEvidenceRoutePolicy(
                {f"moneyforward:{source.name}:{key}": value for key, value in assignments.items()},
                route_id="MF-TO-JDL-SYNTHETIC-E2E-V0",
            ),
            runtime_output_factory=registration.runtime_factory,
        )
        runtime_context = self._target_context() if use_default_context else context
        return service.convert(
            ConversionRequest(
                source,
                output,
                self.mf_profile,
                self.jdl_profile,
                overwrite=overwrite,
                conversion_profile=profile,
                target_runtime_context=runtime_context,
            )
        )

    def _conversion_profile(self) -> ConversionProfile:
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        return ConversionProfile(
            profile_id="mf-to-jdl-synthetic-e2e-v0",
            profile_name="Synthetic MF to JDL E2E",
            source_format_identity=self.mf_schema.identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings={
                name: MappingValue(
                    source_value=name,
                    target_value=name,
                    status=MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": code, "target_formal_name": name},
                )
                for name, code in self.codes.items()
            },
            created_at=now,
            updated_at=now,
            notes="Synthetic test-only explicit mappings; not a production profile.",
        )

    def _target_context(self):
        result = JdlTargetContextBuilder().build(
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            product="JDL IBEX 出納帳",
            version="35.5",
            account_master=tuple(
                JdlAccountIdentity(name, code, name, name) for name, code in self.codes.items()
            ),
            subaccounts=(),
            departments=(),
            tax_processing_mode=JdlTaxProcessingMode.EXEMPT,
            department_processing_enabled=False,
            standard_taxation_confirmed=False,
            individual_credit_method_confirmed=False,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
        self.assertTrue(result.success, result.validation_results)
        return result.context

    @staticmethod
    def _write(path: Path, rows: list[tuple[str, ...]]) -> Path:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        writer.writerows(rows)
        path.write_bytes(output.getvalue().encode("cp932"))
        return path

    @staticmethod
    def _output_rows(path: Path) -> list[list[str]]:
        return list(csv.reader(io.StringIO(path.read_text(encoding="cp932"), newline="")))

    @staticmethod
    def _row(
        transaction_number: str,
        *,
        debit="現金",
        debit_amount="700",
        credit="普通預金",
        credit_amount=None,
        amount=None,
        description="MF-JDL-SYNTHETIC",
        debit_tax="",
        credit_tax="",
        debit_partner="",
        debit_invoice="",
        tags="",
        memo="",
    ) -> tuple[str, ...]:
        if amount is not None:
            debit_amount = amount
            credit_amount = amount
        if credit_amount is None:
            credit_amount = debit_amount
        return (
            transaction_number, "2026/10/19",
            debit, "", "", debit_partner, debit_tax, debit_invoice, debit_amount,
            credit, "", "", "", credit_tax, "", credit_amount,
            description, tags, memo,
        )

    @staticmethod
    def _with_columns(row: tuple[str, ...], *, debit_sub="", debit_department=""):
        values = list(row)
        values[3] = debit_sub
        values[4] = debit_department
        return tuple(values)


if __name__ == "__main__":
    unittest.main()

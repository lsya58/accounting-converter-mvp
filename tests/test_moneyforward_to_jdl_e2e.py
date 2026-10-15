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
    JdlSubaccountIdentity,
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
from accounting_converter.application.moneyforward_conversion_workflow import (
    MoneyForwardConversionWorkflow,
)
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
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

    def test_verified_1d3c_preserves_each_source_row_description_in_order(self) -> None:
        descriptions = ("架空摘要A", "架空摘要B", "架空摘要C")
        rows = [
            self._row("15", debit_amount="1000", credit_amount="500", description=descriptions[0]),
            self._row(
                "15", debit="", debit_amount="", credit="当座預金",
                credit_amount="300", description=descriptions[1],
            ),
            self._row(
                "15", debit="", debit_amount="", credit="小口現金",
                credit_amount="200", description=descriptions[2],
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", rows)
            parsed = MoneyForwardInputAdapter().read(source, self.mf_profile)
            credit = [line for line in parsed[0].lines if line.side.value == "CREDIT"]
            self.assertEqual(
                tuple(line.metadata["moneyforward_description"] for line in credit),
                descriptions,
            )
            output = root / "jdl.csv"
            result = self._convert(
                source,
                output,
                {"15": JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS},
            )
            output_rows = self._output_rows(output)

        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertEqual([row[0] for row in output_rows[1:]], ["1110", "1100", "1101"])
        self.assertEqual([row[23] for row in output_rows[1:]], list(descriptions))

    def test_verified_1d3c_description_is_not_silently_truncated(self) -> None:
        rows = [
            self._row("16", debit_amount="1000", credit_amount="500", description="A" * 33),
            self._row(
                "16", debit="", debit_amount="", credit="当座預金",
                credit_amount="300", description="架空B",
            ),
            self._row(
                "16", debit="", debit_amount="", credit="小口現金",
                credit_amount="200", description="架空C",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", rows)
            output = root / "blocked.csv"
            result = self._convert(
                source,
                output,
                {"16": JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS},
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertTrue(
            any(item.rule_id == "JDL-OUT-DESCRIPTION-LENGTH" for item in result.validation_results)
        )
        self.assertFalse(output.exists())

    def test_multiple_descriptions_with_wrong_evidence_profile_remain_blocked(self) -> None:
        rows = [
            self._row("17", debit_amount="600", credit_amount="700", description="架空A"),
            self._row(
                "17", debit="当座預金", debit_amount="400", credit="小口現金",
                credit_amount="300", description="架空B",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", rows)
            output = root / "blocked.csv"
            result = self._convert(
                source,
                output,
                {"17": JdlEvidenceProfile.COMPOUND_1D3C_LINE_DESCRIPTIONS},
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertTrue(any(item.field == "journal_structure" for item in result.validation_results))
        self.assertFalse(output.exists())

    def test_verified_additional_compound_shapes_preserve_row_descriptions(self) -> None:
        cases = (
            (
                "2D2C",
                [
                    self._row("18", debit_amount="600", credit_amount="700", description="架空A"),
                    self._row("18", debit="当座預金", debit_amount="400", credit="小口現金", credit_amount="300", description="架空B"),
                ],
                JdlEvidenceProfile.COMPOUND_2D2C_LINE_DESCRIPTIONS,
                ["1110", "1101"],
            ),
            (
                "2D1C",
                [
                    self._row("19", debit_amount="600", credit_amount="1000", description="架空A"),
                    self._row("19", debit="当座預金", debit_amount="400", credit="", credit_amount="", description="架空B"),
                ],
                JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS,
                ["1110", "1101"],
            ),
            (
                "2D3C",
                [
                    self._row("20", debit_amount="600", credit_amount="500", description="架空A"),
                    self._row("20", debit="当座預金", debit_amount="400", credit="普通預金", credit_amount="300", description="架空B"),
                    self._row("20", debit="", debit_amount="", credit="小口現金", credit_amount="200", description="架空C"),
                ],
                JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS,
                ["1110", "1100", "1101"],
            ),
        )
        large_cases = []
        for name, debit_count, credit_count, evidence in (
            (
                "4D6C",
                4,
                6,
                JdlEvidenceProfile.COMPOUND_4D6C_LINE_DESCRIPTIONS,
            ),
            (
                "5D7C",
                5,
                7,
                JdlEvidenceProfile.COMPOUND_5D7C_LINE_DESCRIPTIONS,
            ),
            (
                "5D8C",
                5,
                8,
                JdlEvidenceProfile.COMPOUND_5D8C_LINE_DESCRIPTIONS,
            ),
        ):
            total = credit_count * 100
            debit_amount = total // debit_count
            rows = [
                self._row(
                    f"large-{name}",
                    debit="現金" if index < debit_count else "",
                    debit_amount=(str(debit_amount) if index < debit_count else ""),
                    credit="小口現金" if index < credit_count else "",
                    credit_amount=("100" if index < credit_count else ""),
                    description=f"架空{name}-{index + 1}",
                )
                for index in range(max(debit_count, credit_count))
            ]
            large_cases.append(
                (
                    name,
                    rows,
                    evidence,
                    ["1110"] + ["1100"] * (len(rows) - 2) + ["1101"],
                )
            )
        cases += tuple(large_cases)
        for name, rows, evidence, flags in cases:
            with self.subTest(shape=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", rows)
                output = root / "jdl.csv"
                result = self._convert(source, output, {rows[0][0]: evidence})
                output_rows = self._output_rows(output)

                self.assertEqual(result.status, ConversionStatus.SUCCESS)
                self.assertEqual([row[0] for row in output_rows[1:]], flags)
                self.assertEqual(
                    [row[23] for row in output_rows[1:]],
                    [row[16] for row in rows],
                )

    def test_compound_description_profile_shape_mismatch_blocks(self) -> None:
        rows = [
            self._row("21", debit_amount="600", credit_amount="700", description="架空A"),
            self._row("21", debit="当座預金", debit_amount="400", credit="小口現金", credit_amount="300", description="架空B"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", rows)
            output = root / "blocked.csv"
            result = self._convert(
                source,
                output,
                {"21": JdlEvidenceProfile.COMPOUND_2D1C_LINE_DESCRIPTIONS},
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertFalse(output.exists())

    def test_unverified_compound_shape_with_multiple_descriptions_blocks_losslessly(self) -> None:
        rows = [
            self._row("22", debit_amount="500", credit_amount="1000", description="架空A"),
            self._row("22", debit="当座預金", debit_amount="300", credit="", credit_amount="", description="架空B"),
            self._row("22", debit="小口現金", debit_amount="200", credit="", credit_amount="", description="架空C"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", rows)
            output = root / "blocked.csv"
            result = self._convert(
                source,
                output,
                {"22": JdlEvidenceProfile.COMPOUND_2D3C_LINE_DESCRIPTIONS},
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_BUSINESS_VALIDATION)
        self.assertTrue(any(item.field == "description" for item in result.validation_results))
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

    def test_multiple_descriptions_require_matching_compound_evidence_profile(self) -> None:
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

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertTrue(any(item.field == "journal_structure" for item in result.validation_results))
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

    def test_exact_company_workflow_converts_confirmed_tax_and_parent_subaccount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self._with_columns(
                self._row("31", debit_tax="課税仕入 10%", amount="1100"),
                debit_sub="補助甲",
            )
            source = self._write(root / "mf.csv", [row])
            output = root / "jdl.csv"
            before = source.read_bytes()
            profile = self._tax_subaccount_profile()
            context = self._tax_subaccount_context()

            prepared = MoneyForwardConversionWorkflow().prepare(
                input_path=source,
                output_path=output,
                profile=profile,
                context=context,
                company_setting_validated=True,
            )
            result = MoneyForwardConversionWorkflow.execute(prepared)

            self.assertEqual(prepared.summary.readiness, FirstReleaseReadiness.READY)
            self.assertIsNotNone(result)
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            self.assertTrue(output.exists())
            self.assertEqual(source.read_bytes(), before)

    def test_exact_company_workflow_supports_verified_compound_and_blocks_unknown_shape(self) -> None:
        supported = [
            self._row("32", debit_amount="600", credit_amount="700", description="架空A"),
            self._row("32", debit="当座預金", debit_amount="400", credit="小口現金", credit_amount="300", description="架空B"),
        ]
        unsupported = [
            self._row("33", debit_amount="500", credit_amount="1000", description="架空A"),
            self._row("33", debit="当座預金", debit_amount="300", credit="", credit_amount="", description="架空B"),
            self._row("33", debit="小口現金", debit_amount="200", credit="", credit_amount="", description="架空C"),
        ]
        for rows, expected in ((supported, FirstReleaseReadiness.READY), (unsupported, FirstReleaseReadiness.BLOCKED)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self._write(root / "mf.csv", rows)
                output = root / "jdl.csv"
                prepared = MoneyForwardConversionWorkflow().prepare(
                    input_path=source,
                    output_path=output,
                    profile=self._conversion_profile(),
                    context=self._target_context(),
                    company_setting_validated=True,
                )
                self.assertEqual(prepared.summary.readiness, expected)
                if expected is FirstReleaseReadiness.BLOCKED:
                    self.assertEqual(prepared.summary.unsupported_shape_count, 1)
                    self.assertFalse(output.exists())

    def test_exact_company_workflow_blocks_without_company_unresolved_or_trade_partner(self) -> None:
        cases = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            normal = self._write(root / "normal.csv", [self._row("34")])
            partner = self._write(
                root / "partner.csv", [self._row("35", debit_partner="架空取引先")]
            )
            unresolved = self._conversion_profile()
            unresolved.account_mappings["現金"] = MappingValue(
                "現金", status=MappingStatus.UNRESOLVED
            )
            cases.extend(
                (
                    (normal, self._conversion_profile(), False, "会社設定"),
                    (normal, unresolved, True, "科目の確認"),
                    (partner, self._conversion_profile(), True, "取引先情報"),
                )
            )
            for index, (source, profile, validated, message) in enumerate(cases):
                output = root / f"blocked-{index}.csv"
                prepared = MoneyForwardConversionWorkflow().prepare(
                    input_path=source,
                    output_path=output,
                    profile=profile,
                    context=self._target_context(),
                    company_setting_validated=validated,
                )
                self.assertEqual(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
                self.assertTrue(any(message in item for item in prepared.summary.blocking_reasons))
                if message == "取引先情報":
                    self.assertEqual(
                        prepared.summary.optional_field_blocker_count, 1
                    )
                self.assertFalse(output.exists())

    def test_exact_company_workflow_does_not_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write(root / "mf.csv", [self._row("36")])
            output = root / "existing.csv"
            output.write_bytes(b"existing")
            prepared = MoneyForwardConversionWorkflow().prepare(
                input_path=source,
                output_path=output,
                profile=self._conversion_profile(),
                context=self._target_context(),
                company_setting_validated=True,
            )
            self.assertEqual(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            self.assertEqual(output.read_bytes(), b"existing")

    def _tax_subaccount_profile(self) -> ConversionProfile:
        profile = self._conversion_profile()
        key = MappingKey(MappingType.SUBACCOUNT, "補助甲", "現金")
        profile.subaccount_context_mappings[key] = MappingValue(
            "補助甲",
            "補助甲",
            MappingStatus.USER_CONFIRMED,
            "現金",
            {"target_code": "1", "output_code": "1", "output_name": "補助甲"},
        )
        profile.tax_mappings["課税仕入 10%"] = MappingValue(
            "課税仕入 10%",
            "10%",
            MappingStatus.USER_CONFIRMED,
            metadata={
                "jdl_tax_scope": "仕　入",
                "jdl_evidence_id": "EVID-JDL-MF-TAX-PURCHASE-10-SUBACCOUNT-ROUNDTRIP-001",
            },
        )
        return profile

    def _tax_subaccount_context(self):
        result = JdlTargetContextBuilder().build(
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            product="JDL IBEX 出納帳",
            version="35.5",
            account_master=tuple(
                JdlAccountIdentity(name, code, name, name) for name, code in self.codes.items()
            ),
            subaccounts=(JdlSubaccountIdentity("現金", "補助甲", "1", "1", "補助甲", True, "1001", "補助甲"),),
            departments=(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            department_processing_enabled=False,
            standard_taxation_confirmed=True,
            individual_credit_method_confirmed=True,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )
        self.assertTrue(result.success, result.validation_results)
        return result.context

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

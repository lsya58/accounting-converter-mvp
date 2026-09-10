from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.yayoi import (
    YayoiInputAdapter,
    YayoiInputAdapterError,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.conversion_preparation import (
    ConversionPreparationService,
    ConversionReadinessStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine, MappingRuleSet
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
    yayoi_desktop_import_25_documented_schema,
)
from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)
from tests.support.demo_adapters import (
    DemoOutputAdapter,
    DemoOutputValidator,
)


class NoopStructuralValidator:
    def validate(self, path: Path, profile: FormatProfile) -> list:
        _ = path
        _ = profile
        return []


class YayoiInputAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = YayoiInputAdapter()
        self.schema = yayoi_ae19_direct_export_observed_schema()
        self.spec = yayoi_accounting_05_official_import_spec()
        self.profile = FormatProfile(
            software="Yayoi",
            product="Yayoi Accounting AE 19",
            version="19",
            format_id=self.schema.identity.stable_key,
            encoding="cp932",
        )

    def test_read_2000_single_preserves_observed_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rows(
                Path(tmpdir) / "yayoi.txt",
                [
                    self._row(
                        "2000",
                        debit_sub_account="架空借方補助",
                        debit_department="架空借方部門",
                        description='架空摘要, "quoted"',
                    )
                ],
            )

            entries = self.adapter.read(path, self.profile)
            record_count = self.adapter.record_count(path, self.profile)

        self.assertEqual(len(entries), 1)
        self.assertEqual(record_count, 1)
        entry = entries[0]
        debit, credit = entry.lines
        self.assertEqual(entry.metadata["identifier_flags"], ("2000",))
        self.assertEqual(entry.metadata["production_adapter"], True)
        self.assertEqual(entry.metadata["evidence_level"], "OBSERVED")
        self.assertEqual(debit.sub_account, "架空借方補助")
        self.assertEqual(debit.department, "架空借方部門")
        self.assertEqual(debit.tax_info.category, "架空借方税区分")
        self.assertEqual(str(debit.tax_info.tax_amount), "74")
        self.assertEqual(credit.tax_info.category, "架空貸方税区分")
        self.assertEqual(str(credit.tax_info.tax_amount), "0")
        self.assertIn(",", entry.description)
        self.assertIn('"', entry.description)

    def test_read_2111_single_voucher(self) -> None:
        entries = self._read_rows([self._row("2111")])

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata["identifier_flags"], ("2111",))
        self.assertFalse(entries[0].is_compound())
        self.assertTrue(entries[0].is_balanced())

    def test_read_two_record_voucher_sequence(self) -> None:
        entries = self._read_rows(
            [
                self._row(
                    "2110",
                    voucher="20",
                    debit_amount="1000",
                    credit_account="",
                    credit_amount="0",
                    description="",
                ),
                self._row(
                    "2101",
                    voucher="20",
                    debit_account="",
                    debit_amount="0",
                    debit_tax_amount="0",
                    credit_amount="1000",
                ),
            ]
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].metadata["identifier_flags"], ("2110", "2101"))
        self.assertFalse(entries[0].is_compound())
        self.assertEqual(len(entries[0].lines), 2)

    def test_read_multi_record_voucher_with_one_middle(self) -> None:
        entries = self._read_rows(
            [
                self._row("2110", voucher="30", debit_amount="1000", credit_account="", credit_amount="0", description=""),
                self._row("2100", voucher="30", debit_amount="2000", credit_account="", credit_amount="0", description=""),
                self._row("2101", voucher="30", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="3000"),
            ]
        )

        self.assertEqual(entries[0].metadata["identifier_flags"], ("2110", "2100", "2101"))
        self.assertTrue(entries[0].is_compound())
        self.assertEqual(len(entries[0].lines), 3)

    def test_read_multi_record_voucher_with_multiple_middle_rows(self) -> None:
        entries = self._read_rows(
            [
                self._row("2110", voucher="40", debit_amount="1000", credit_account="", credit_amount="0", description=""),
                self._row("2100", voucher="40", debit_amount="1000", credit_account="", credit_amount="0", description=""),
                self._row("2100", voucher="40", debit_amount="1000", credit_account="", credit_amount="0", description=""),
                self._row("2101", voucher="40", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="3000"),
            ]
        )

        self.assertEqual(
            entries[0].metadata["identifier_flags"],
            ("2110", "2100", "2100", "2101"),
        )
        self.assertTrue(entries[0].is_compound())
        self.assertEqual(len(entries[0].lines), 4)

    def test_subaccount_department_and_tax_fields_are_not_lost(self) -> None:
        entries = self._read_rows(
            [
                self._row(
                    "2000",
                    debit_sub_account="架空借方補助",
                    debit_department="架空借方部門",
                    credit_sub_account="架空貸方補助",
                    credit_department="架空貸方部門",
                )
            ]
        )

        debit, credit = entries[0].lines
        self.assertEqual(debit.sub_account, "架空借方補助")
        self.assertEqual(debit.department, "架空借方部門")
        self.assertEqual(credit.sub_account, "架空貸方補助")
        self.assertEqual(credit.department, "架空貸方部門")
        self.assertEqual(str(debit.tax_info.tax_amount), "74")
        self.assertEqual(str(credit.tax_info.tax_amount), "0")

    def test_malformed_sequence_blocks(self) -> None:
        rows = [
            self._row("2110", debit_amount="1000", credit_account="", credit_amount="0"),
            self._row("2111", debit_amount="1000", credit_account="", credit_amount="0"),
            self._row("2101", debit_account="", debit_amount="0", credit_amount="2000"),
        ]

        with self.assertRaisesRegex(YayoiInputAdapterError, "unexpected flag"):
            self._read_rows(rows)

    def test_voucher_mismatch_blocks(self) -> None:
        rows = [
            self._row("2110", voucher="50", debit_amount="1000", credit_account="", credit_amount="0"),
            self._row("2101", voucher="51", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="1000"),
        ]

        with self.assertRaisesRegex(YayoiInputAdapterError, "inconsistent voucher"):
            self._read_rows(rows)

    def test_date_mismatch_blocks(self) -> None:
        rows = [
            self._row("2110", voucher="60", date_value="H.31/01/15", debit_amount="1000", credit_account="", credit_amount="0"),
            self._row("2101", voucher="60", date_value="H.31/01/16", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="1000"),
        ]

        with self.assertRaisesRegex(YayoiInputAdapterError, "inconsistent date"):
            self._read_rows(rows)

    def test_unbalanced_group_blocks(self) -> None:
        rows = [
            self._row("2110", debit_amount="1000", credit_account="", credit_amount="0"),
            self._row("2101", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="999"),
        ]

        with self.assertRaisesRegex(YayoiInputAdapterError, "not balanced"):
            self._read_rows(rows)

    def test_unknown_flag_blocks(self) -> None:
        with self.assertRaisesRegex(YayoiInputAdapterError, "unsupported identifier flag"):
            self._read_rows([self._row("2999")])

    def test_malformed_csv_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.txt"
            path.write_bytes(b'2000,"unterminated\r\n')

            with self.assertRaisesRegex(YayoiInputAdapterError, "CSV parse failed"):
                self.adapter.read(path, self.profile)

    def test_unparseable_date_blocks(self) -> None:
        with self.assertRaisesRegex(YayoiInputAdapterError, "unsupported date format"):
            self._read_rows([self._row("2000", date_value="31/01/15")])

    def test_unparseable_amount_blocks(self) -> None:
        with self.assertRaisesRegex(YayoiInputAdapterError, "invalid DEBIT_amount"):
            self._read_rows([self._row("2000", debit_amount="not-amount")])

    def test_wrong_field_count_blocks(self) -> None:
        with self.assertRaisesRegex(YayoiInputAdapterError, "expected 25"):
            self._read_rows([self._row("2000")[:-1]])

    def test_ambiguous_blank_account_side_blocks(self) -> None:
        row = list(
            self._row(
                "2110",
                credit_account="",
                credit_sub_account="架空補助",
                credit_amount="0",
            )
        )

        with self.assertRaisesRegex(YayoiInputAdapterError, "ambiguous CREDIT"):
            self._read_rows([tuple(row), self._row("2101", debit_account="", debit_amount="0")])

    def test_supports_only_exact_observed_profile(self) -> None:
        official = yayoi_desktop_import_25_documented_schema()
        official_profile = FormatProfile(
            software="Yayoi",
            product=official.identity.product,
            version="05+",
            format_id=official.identity.stable_key,
            encoding="cp932",
        )

        self.assertTrue(self.adapter.supports(Path("sample.txt"), self.profile))
        self.assertFalse(self.adapter.supports(Path("sample.txt"), official_profile))
        self.assertFalse(self.adapter.supports(Path("sample.xlsx"), self.profile))

    def test_conversion_service_can_use_yayoi_input_adapter_without_partial_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = self._write_rows(
                root / "yayoi.txt",
                [
                    self._row("2110", voucher="70", debit_amount="1000", credit_account="", credit_amount="0", description=""),
                    self._row("2101", voucher="70", debit_account="", debit_amount="0", debit_tax_amount="0", credit_amount="1000"),
                ],
            )
            output_path = root / "out.csv"

            result = ConversionService(
                input_adapter=self.adapter,
                structural_validator=NoopStructuralValidator(),
                mapping_engine=MappingEngine(self._identity_mapping_rules()),
                business_validator=ValidationPipeline([BalanceRule()]),
                output_adapter=DemoOutputAdapter(),
                output_validator=DemoOutputValidator(),
            ).convert(
                ConversionRequest(
                    input_path=input_path,
                    output_path=output_path,
                    input_profile=self.profile,
                    output_profile=FormatProfile("Demo", "Demo", "test", "demo", "utf-8"),
                )
            )

        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertEqual(result.input_record_count, 2)
        self.assertEqual(result.input_journal_count, 1)
        self.assertEqual(result.output_journal_count, 1)

    def test_production_registry_selects_yayoi_input_but_not_unverified_jdl_output(self) -> None:
        registry = production_adapter_registry()
        jdl_schema = jdl_ibex_cashbook_35_5_observed_schema_definition()

        input_lookup = registry.get_exact_input(self.schema.identity)
        output_lookup = registry.get_exact_output(jdl_schema.identity)

        self.assertEqual(input_lookup.status, AdapterAvailabilityStatus.EXACT)
        self.assertEqual(output_lookup.status, AdapterAvailabilityStatus.UNAVAILABLE)
        self.assertFalse(registry.has_conversion_pair(self.schema.identity, jdl_schema.identity))

    def test_preparation_does_not_mark_yayoi_to_unverified_jdl_as_ready(self) -> None:
        registry = production_adapter_registry()
        jdl_schema = jdl_ibex_cashbook_35_5_observed_schema_definition()
        entries = tuple(self._read_rows([self._row("2000")]))

        readiness = ConversionPreparationService(adapter_registry=registry).prepare(
            self.schema,
            jdl_schema,
            entries,
            saved_profile=None,
        )

        self.assertNotEqual(readiness.status, ConversionReadinessStatus.READY)
        self.assertEqual(readiness.adapter_availability.input_status, AdapterAvailabilityStatus.EXACT)
        self.assertEqual(
            readiness.adapter_availability.output_status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def _read_rows(self, rows: list[tuple[str, ...]]) -> list:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_rows(Path(tmpdir) / "yayoi.txt", rows)
            return self.adapter.read(path, self.profile)

    def _write_rows(self, path: Path, rows: list[tuple[str, ...]]) -> Path:
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerows(rows)
        return path

    def _row(
        self,
        flag: str,
        voucher: str = "1",
        date_value: str = "H.31/01/15",
        debit_account: str = "架空借方科目",
        debit_sub_account: str = "",
        debit_department: str = "",
        debit_tax_category: str = "架空借方税区分",
        debit_amount: str = "1000",
        debit_tax_amount: str = "74",
        credit_account: str = "架空貸方科目",
        credit_sub_account: str = "",
        credit_department: str = "",
        credit_tax_category: str = "架空貸方税区分",
        credit_amount: str = "1000",
        credit_tax_amount: str = "0",
        description: str = "架空摘要",
    ) -> tuple[str, ...]:
        row = [""] * self.spec.column_count
        row[0] = flag
        row[1] = voucher
        row[3] = date_value
        row[4] = debit_account
        row[5] = debit_sub_account
        row[6] = debit_department
        row[7] = debit_tax_category
        row[8] = debit_amount
        row[9] = debit_tax_amount
        row[10] = credit_account
        row[11] = credit_sub_account
        row[12] = credit_department
        row[13] = credit_tax_category
        row[14] = credit_amount
        row[15] = credit_tax_amount
        row[16] = description
        row[19] = "0"
        row[22] = "0"
        row[23] = "0"
        row[24] = "no"
        return tuple(row)

    def _identity_mapping_rules(self) -> MappingRuleSet:
        values = [
            "架空借方科目",
            "架空貸方科目",
            "架空借方税区分",
            "架空貸方税区分",
            "架空借方補助",
            "架空借方部門",
            "架空貸方補助",
            "架空貸方部門",
        ]
        mappings = {
            value: MappingValue(value, value, MappingStatus.USER_CONFIRMED)
            for value in values
        }
        return MappingRuleSet(
            accounts=mappings,
            sub_accounts=mappings,
            departments=mappings,
            tax_categories=mappings,
        )

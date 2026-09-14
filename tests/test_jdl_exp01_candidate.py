from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application.conversion_preparation import (
    ConversionPreparationService,
    ConversionReadinessStatus,
)
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.domain.format_metadata import EvidenceLevel
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from experiments.jdl_import.exp01_candidate import (
    EXPERIMENT_STATUS,
    OFFICIAL_HEADER,
    JdlExp01CandidateConfig,
    JdlExp01CandidateError,
    build_exp01_common_journal,
    config_column_plan,
    generate_exp01_candidate,
    validate_generated_candidate,
)


class JdlExp01CandidateTests(unittest.TestCase):
    def test_valid_explicit_config_generates_candidate_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "data" / "private" / "experiments"
            result = generate_exp01_candidate(self.config(), output_dir)

            self.assertTrue(result.csv_path.exists())
            self.assertTrue(result.report_path.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertTrue(result.validation_report.success)
            self.assertEqual(result.validation_report.record_count, 1)
            self.assertEqual(result.validation_report.column_count, 30)
            self.assertEqual(dict(result.validation_report.identifier_flags), {"1000": 1})
            self.assertTrue(result.validation_report.balanced)
            self.assertTrue(result.validation_report.target_master_validation_confirmed)
            self.assertEqual(result.validation_report.status, EXPERIMENT_STATUS)

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], EXPERIMENT_STATUS)
            self.assertEqual(manifest["actual_result"], "UNTESTED")
            self.assertIn("column_plan", manifest)

    def test_generated_csv_is_cp932_crlf_bomless_header_and_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_exp01_candidate(
                self.config(),
                Path(tmpdir) / "data" / "private" / "experiments",
            )

            raw = result.csv_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            raw.decode("cp932")

            rows = list(csv.reader(result.csv_path.read_text(encoding="cp932").splitlines()))
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]), 30)
            self.assertEqual(len(rows[1]), 30)
            self.assertEqual(rows[0][0], "//識別フラグ")
            self.assertEqual(rows[1][0], "1000")

    def test_common_journal_model_is_built_from_explicit_config(self) -> None:
        entry = build_exp01_common_journal(self.config())

        self.assertEqual(len(entry.lines), 2)
        self.assertTrue(entry.is_balanced())
        self.assertFalse(entry.is_compound())
        self.assertEqual(entry.metadata["status"], EXPERIMENT_STATUS)
        self.assertEqual(entry.metadata["schema_evidence_level"], "OFFICIAL_DOCUMENTED")
        self.assertEqual(entry.metadata["serialization_evidence_level"], "OBSERVED")
        self.assertFalse(entry.metadata["production_adapter"])

    def test_overwrite_is_blocked_by_default_and_existing_file_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "data" / "private" / "experiments"
            first = generate_exp01_candidate(self.config(), output_dir)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(JdlExp01CandidateError, "output already exists"):
                generate_exp01_candidate(self.config(), output_dir)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def test_overwrite_true_replaces_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "data" / "private" / "experiments"
            first = generate_exp01_candidate(self.config(), output_dir)
            config = self.config()
            config.jdl_columns["伝番"] = "9002"
            second = generate_exp01_candidate(config, output_dir, overwrite=True)

            self.assertEqual(first.csv_path, second.csv_path)
            rows = list(csv.reader(second.csv_path.read_text(encoding="cp932").splitlines()))
            self.assertEqual(rows[1][1], "9002")

    def test_config_output_path_conflict_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            config_path = output_dir / "EXP-01_jdl_import_candidate.csv"

            with self.assertRaisesRegex(JdlExp01CandidateError, "must differ"):
                generate_exp01_candidate(
                    self.config(),
                    output_dir,
                    config_path=config_path,
                )

    def test_non_private_output_path_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(JdlExp01CandidateError, "data/private/experiments"):
                generate_exp01_candidate(self.config(), Path(tmpdir) / "public")

    def test_missing_account_mapping_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["借方科目"] = ""
        config.jdl_columns["借方科目名称"] = ""
        config.jdl_columns["借方科目正式名称"] = ""

        with self.assertRaisesRegex(JdlExp01CandidateError, "debit account"):
            build_exp01_common_journal(config)

    def test_account_code_only_identifier_is_allowed_by_manual_rule(self) -> None:
        config = self.config()
        config.jdl_columns["借方科目名称"] = ""
        config.jdl_columns["借方科目正式名称"] = ""
        config.jdl_columns["貸方科目名称"] = ""
        config.jdl_columns["貸方科目正式名称"] = ""

        entry = build_exp01_common_journal(config)

        self.assertTrue(entry.is_balanced())

    def test_subaccount_code_or_name_alternative_is_allowed(self) -> None:
        config = self.config()
        config.jdl_columns["借方補助"] = "0101"

        entry = build_exp01_common_journal(config)

        self.assertTrue(entry.is_balanced())

    def test_optional_documented_columns_can_be_omitted_and_remain_columns(self) -> None:
        config = self.config()
        del config.jdl_columns["借方補助"]
        del config.jdl_columns["借方補助名称"]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_exp01_candidate(
                config,
                Path(tmpdir) / "data" / "private" / "experiments",
            )

            rows = list(csv.reader(result.csv_path.read_text(encoding="cp932").splitlines()))

        self.assertEqual(len(rows[1]), 30)
        self.assertEqual(rows[1][OFFICIAL_HEADER.index("借方補助")], "")
        self.assertGreater(result.validation_report.implicit_default_count, 0)

    def test_unknown_jdl_field_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["未確認列"] = ""

        with self.assertRaisesRegex(JdlExp01CandidateError, "unknown JDL columns"):
            build_exp01_common_journal(config)

    def test_amount_parse_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["借方金額"] = "not-amount"

        with self.assertRaisesRegex(JdlExp01CandidateError, "integer amount"):
            build_exp01_common_journal(config)

    def test_debit_credit_imbalance_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["貸方金額"] = "999"

        with self.assertRaisesRegex(JdlExp01CandidateError, "must match"):
            build_exp01_common_journal(config)

    def test_generated_candidate_self_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "data" / "private" / "experiments"
            result = generate_exp01_candidate(self.config(), output_dir)

            report = validate_generated_candidate(result.csv_path, self.config())

        self.assertTrue(report.success)
        self.assertEqual(report.implicit_default_count, 0)
        self.assertTrue(report.required_mapping_complete)

    def test_privacy_safe_report_omits_accounting_body_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "data" / "private" / "experiments"
            result = generate_exp01_candidate(self.config(), output_dir)

            payload = result.validation_report.to_privacy_safe_dict()
            text = result.validation_report.to_privacy_safe_text()
            serialized = json.dumps(payload, ensure_ascii=False) + text

        self.assertNotIn("架空現金", serialized)
        self.assertNotIn("架空普通預金", serialized)
        self.assertNotIn("取込テスト", serialized)
        self.assertNotIn("D001", serialized)
        self.assertNotIn("C001", serialized)
        self.assertNotIn("9001", serialized)
        self.assertNotIn("20260910", serialized)
        self.assertEqual(payload["status"], EXPERIMENT_STATUS)

    def test_column_plan_separates_required_conditional_and_blankable_columns(self) -> None:
        plan = config_column_plan()

        self.assertEqual(len(plan), 30)
        self.assertTrue(
            any(item["source"] == "blank_allowed_when_unneeded_official_documented" for item in plan)
        )
        self.assertTrue(
            any(item["source"] == "conditional_tax_field_official_documented" for item in plan)
        )

    def test_missing_target_master_validation_blocks(self) -> None:
        config = self.config()
        config.target_master_validation["debit_account_exists_in_target_master"] = False

        with self.assertRaisesRegex(JdlExp01CandidateError, "target master validation"):
            build_exp01_common_journal(config)

    def test_production_registry_does_not_register_jdl_output(self) -> None:
        registry = production_adapter_registry()
        jdl_schema = jdl_ibex_cashbook_35_5_observed_schema_definition()

        self.assertEqual(jdl_schema.identity.evidence_level, EvidenceLevel.OBSERVED)
        self.assertNotEqual(
            jdl_schema.identity.evidence_level,
            EvidenceLevel.VERIFIED_BY_REAL_IMPORT,
        )
        self.assertEqual(
            registry.get_exact_output(jdl_schema.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def test_import_route_ui_evidence_does_not_make_exp01_production(self) -> None:
        entry = build_exp01_common_journal(self.config())
        jdl_schema = jdl_ibex_cashbook_35_5_observed_schema_definition()
        official_schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(entry.metadata["status"], EXPERIMENT_STATUS)
        self.assertFalse(entry.metadata["production_adapter"])
        self.assertEqual(jdl_schema.identity.evidence_level, EvidenceLevel.OBSERVED)
        self.assertEqual(official_schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertIn("Not verified by successful import", jdl_schema.identity.notes)

    def test_yayoi_to_jdl_readiness_is_not_ready(self) -> None:
        registry = production_adapter_registry()
        source = yayoi_ae19_direct_export_observed_schema()
        target = jdl_ibex_cashbook_35_5_observed_schema_definition()

        readiness = ConversionPreparationService(adapter_registry=registry).prepare(
            source,
            target,
            journal_entries=(),
            saved_profile=None,
        )

        self.assertNotEqual(readiness.status, ConversionReadinessStatus.READY)
        self.assertEqual(
            readiness.adapter_availability.output_status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def test_yayoi_to_official_jdl_readiness_is_not_ready(self) -> None:
        registry = production_adapter_registry()
        source = yayoi_ae19_direct_export_observed_schema()
        target = jdl_ibex_cashbook_official_journal_import_schema_definition()

        readiness = ConversionPreparationService(adapter_registry=registry).prepare(
            source,
            target,
            journal_entries=(),
            saved_profile=None,
        )

        self.assertNotEqual(readiness.status, ConversionReadinessStatus.READY)
        self.assertEqual(
            readiness.adapter_availability.output_status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def test_exempt_tax_processing_blocks_unnecessary_tax_fields(self) -> None:
        config = self.config()
        config.jdl_columns["借方課区"] = "仕入"

        with self.assertRaisesRegex(JdlExp01CandidateError, "unnecessary tax field"):
            build_exp01_common_journal(config)

    def test_tax_inclusive_processing_requires_scope_and_category(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
            tax_validation_confirmed=True,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"

        entry = build_exp01_common_journal(config)

        self.assertTrue(entry.is_balanced())

    def test_tax_values_without_confirmed_abbreviations_block(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"

        with self.assertRaisesRegex(JdlExp01CandidateError, "tax abbreviations"):
            build_exp01_common_journal(config)

    def test_tax_inclusive_processing_blocks_tax_amount(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
            tax_validation_confirmed=True,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"
        config.jdl_columns["借方消費税"] = "100"

        with self.assertRaisesRegex(JdlExp01CandidateError, "tax-inclusive"):
            build_exp01_common_journal(config)

    def test_tax_exclusive_processing_requires_tax_method_and_amount(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value,
            tax_validation_confirmed=True,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["借方税入力方法"] = "別記"
        config.jdl_columns["借方消費税"] = "100"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"
        config.jdl_columns["貸方税入力方法"] = "別記"
        config.jdl_columns["貸方消費税"] = "100"

        entry = build_exp01_common_journal(config)

        self.assertTrue(entry.is_balanced())

    def test_tax_exclusive_processing_blocks_missing_tax_amount(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value,
            tax_validation_confirmed=True,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["借方税入力方法"] = "別記"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"
        config.jdl_columns["貸方税入力方法"] = "別記"

        with self.assertRaisesRegex(JdlExp01CandidateError, "tax amount is required"):
            build_exp01_common_journal(config)

    def test_transaction_account_requires_explicit_tax_semantics_confirmation(self) -> None:
        config = self.config(
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED.value,
            tax_validation_confirmed=True,
            transaction_account_confirmed=False,
        )
        config.jdl_columns["借方課区"] = "仕入"
        config.jdl_columns["借方税区"] = "10%"
        config.jdl_columns["借方税入力方法"] = "別記"
        config.jdl_columns["借方消費税"] = "100"
        config.jdl_columns["貸方課区"] = "売上"
        config.jdl_columns["貸方税区"] = "10%"
        config.jdl_columns["貸方税入力方法"] = "別記"
        config.jdl_columns["貸方消費税"] = "100"
        config.jdl_columns["借方取引科目"] = "1001"

        with self.assertRaisesRegex(JdlExp01CandidateError, "transaction account"):
            build_exp01_common_journal(config)

    def test_date_must_be_yyyymmdd_and_match_iso_date(self) -> None:
        config = self.config()
        config.jdl_columns["日付"] = "2026/09/10"

        with self.assertRaisesRegex(JdlExp01CandidateError, "YYYYMMDD"):
            build_exp01_common_journal(config)

    def test_summary_length_limit_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["摘要"] = "あ" * 33

        with self.assertRaisesRegex(JdlExp01CandidateError, "摘要"):
            build_exp01_common_journal(config)

    def config(
        self,
        company_tax_processing: str = JdlTaxProcessingMode.EXEMPT.value,
        tax_validation_confirmed: bool = False,
        transaction_account_confirmed: bool = True,
    ) -> JdlExp01CandidateConfig:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        columns = {field.display_name: "" for field in schema.fields}
        columns.update(
            {
                "//識別フラグ": "1000",
                "伝番": "9001",
                "日付": "20260910",
                "借方科目": "1001",
                "借方科目名称": "現金",
                "借方科目正式名称": "架空現金",
                "借方金額": "1000",
                "貸方科目": "1002",
                "貸方科目名称": "預金",
                "貸方科目正式名称": "架空普通預金",
                "貸方金額": "1000",
                "摘要": "取込テスト",
            }
        )
        return JdlExp01CandidateConfig(
            jdl_columns=columns,
            journal_date_iso="2026-09-10",
            target_master_validation={
                "debit_account_exists_in_target_master": True,
                "credit_account_exists_in_target_master": True,
                "debit_subaccount_blank_or_exists_under_parent": True,
                "credit_subaccount_blank_or_exists_under_parent": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            company_tax_processing=company_tax_processing,
            tax_validation={
                "company_tax_processing_confirmed": True,
                "tax_category_abbreviations_confirmed_when_used": (
                    tax_validation_confirmed
                ),
                "tax_scope_tax_category_combination_confirmed_when_used": (
                    tax_validation_confirmed
                ),
                "transaction_account_confirmed_when_used": (
                    transaction_account_confirmed
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()

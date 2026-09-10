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
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
)
from experiments.jdl_import.exp01_candidate import (
    EXPERIMENT_STATUS,
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

        with self.assertRaisesRegex(JdlExp01CandidateError, "借方科目"):
            build_exp01_common_journal(config)

    def test_ambiguous_mapping_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["借方補助"] = "S001"
        config.jdl_columns["借方補助名称"] = ""

        with self.assertRaisesRegex(JdlExp01CandidateError, "ambiguous explicit mapping"):
            build_exp01_common_journal(config)

    def test_unknown_required_jdl_field_blocks(self) -> None:
        config = self.config()
        del config.jdl_columns["借方課区"]

        with self.assertRaisesRegex(JdlExp01CandidateError, "missing explicit JDL columns"):
            build_exp01_common_journal(config)

    def test_amount_parse_blocks(self) -> None:
        config = self.config()
        config.jdl_columns["借方金額"] = "not-amount"

        with self.assertRaisesRegex(JdlExp01CandidateError, "parseable amount"):
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
        self.assertNotIn("2026/09/10", serialized)
        self.assertEqual(payload["status"], EXPERIMENT_STATUS)

    def test_column_plan_requires_explicit_config_for_all_30_columns(self) -> None:
        plan = config_column_plan()

        self.assertEqual(len(plan), 30)
        self.assertTrue(
            all(item["source"].startswith("explicit_experiment_config") for item in plan)
        )

    def test_production_registry_does_not_register_jdl_output(self) -> None:
        registry = production_adapter_registry()
        jdl_schema = jdl_ibex_cashbook_35_5_observed_schema_definition()

        self.assertEqual(
            registry.get_exact_output(jdl_schema.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

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

    def config(self) -> JdlExp01CandidateConfig:
        schema = jdl_ibex_cashbook_35_5_observed_schema_definition()
        columns = {field.display_name: "" for field in schema.fields}
        columns.update(
            {
                "//識別フラグ": "1000",
                "伝番": "9001",
                "日付": "2026/09/10",
                "借方科目": "D001",
                "借方科目名称": "架空現金",
                "借方科目正式名称": "架空現金",
                "借方金額": "1000",
                "貸方科目": "C001",
                "貸方科目名称": "架空普通預金",
                "貸方科目正式名称": "架空普通預金",
                "貸方金額": "1000",
                "摘要": "取込テスト",
            }
        )
        return JdlExp01CandidateConfig(
            jdl_columns=columns,
            journal_date_iso="2026-09-10",
        )


if __name__ == "__main__":
    unittest.main()

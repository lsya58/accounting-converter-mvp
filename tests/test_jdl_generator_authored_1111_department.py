from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.domain.format_metadata import EvidenceLevel
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)
from experiments.jdl_import.generator_authored_1111 import OFFICIAL_HEADER
from experiments.jdl_import.generator_authored_1111_department import (
    EXPERIMENT_STATUS,
    JdlGeneratorAuthored1111DepartmentConfig,
    JdlGeneratorAuthored1111DepartmentError,
    TargetAccountEvidence,
    TargetDepartmentEvidence,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    DEPARTMENT_1000_EXPERIMENT_STATUS,
    EVIDENCE_ID_1111_DEPARTMENT,
    EVIDENCE_ID_DEPARTMENT_HAND_1111,
    RuntimeReexportFieldStatus,
    compare_generator_1111_department_runtime,
    department_hand_entry_1111_observed_evidence,
    generator_authored_1111_department_real_import_evidence,
)


class JdlGeneratorAuthored1111DepartmentTests(unittest.TestCase):
    def test_generates_both_side_department_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/department_1111",
            )
            raw = result.csv_path.read_bytes()
            rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertFalse(raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")))
        self.assertEqual(raw.count(b"\r\n"), 2)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), 30)
        self.assertEqual(rows[1][0], "1111")
        for side in ("借方", "貸方"):
            self.assertEqual(
                rows[1][OFFICIAL_HEADER.index(f"{side}部門コード")],
                config.target_department_evidence.department_code,
            )
            self.assertEqual(
                rows[1][OFFICIAL_HEADER.index(f"{side}部門名称")],
                config.target_department_evidence.short_name,
            )
        for field in ("借方補助", "借方補助名称", "貸方補助", "貸方補助名称"):
            self.assertEqual(rows[1][OFFICIAL_HEADER.index(field)], "")
        self.assertTrue(report["success"])
        self.assertEqual(report["status"], EXPERIMENT_STATUS)
        self.assertEqual(report["department_sides"], ["DEBIT", "CREDIT"])
        self.assertFalse(report["source_row_byte_identical"])
        self.assertFalse(report["production_ready"])
        self.assertEqual(manifest["actual_result"], "UNTESTED")
        self.assertFalse(manifest["source_jdl_row_used_for_construction"])
        self.assertFalse(manifest["production_ready"])

    def test_missing_one_department_side_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["貸方部門コード"] = ""
        config.jdl_columns["貸方部門名称"] = ""

        self.assert_blocked(config, "both department sides")

    def test_department_master_mismatch_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["借方部門名称"] = "別部門"

        self.assert_blocked(config, "both department sides")

    def test_unconfirmed_target_master_is_blocked(self) -> None:
        config = self.config()
        config.target_master_validation["department_code_exact_match"] = False

        self.assert_blocked(config, "validation incomplete")

    def test_subaccount_and_tax_population_are_blocked(self) -> None:
        subaccount = self.config()
        subaccount.jdl_columns["貸方補助"] = "1"
        self.assert_blocked(subaccount, "subaccount fields must remain blank")

        tax = self.config()
        tax.jdl_columns["借方税区"] = "架空税"
        self.assert_blocked(tax, "exempt tax fields must remain blank")

    def test_observed_source_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            rows = list(csv.reader(source.read_text(encoding="cp932").splitlines()))
            rows[-1][OFFICIAL_HEADER.index("貸方部門コード")] = "9"
            with source.open("w", encoding="cp932", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\r\n")
                writer.writerows(rows)

            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111DepartmentError,
                "observed source does not confirm",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/test",
                )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            output = root / "data/private/experiments/jdl_import/test"
            first = generate_candidate(config, source, output)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111DepartmentError,
                "already exists",
            ):
                generate_candidate(config, source, output)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def test_report_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/test",
            )
            serialized = (
                result.report_path.read_text(encoding="utf-8")
                + result.manifest_path.read_text(encoding="utf-8")
            )

        for private_value in (
            "架空旅費",
            "架空現金",
            "架空部門",
            "架空短",
            "架空摘要",
            "20261005",
            "1700",
        ):
            self.assertNotIn(private_value, serialized)

    def test_hand_entry_evidence_remains_observed_only(self) -> None:
        evidence = department_hand_entry_1111_observed_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_DEPARTMENT_HAND_1111)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.OBSERVED)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn("generator-authored department import", evidence.not_verified)

    def test_real_import_evidence_is_scoped_and_separate_from_hand_entry(self) -> None:
        evidence = generator_authored_1111_department_real_import_evidence()
        hand_entry = department_hand_entry_1111_observed_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_1111_DEPARTMENT)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertEqual(hand_entry.evidence_level, EvidenceLevel.OBSERVED)
        self.assertNotEqual(evidence.evidence_id, hand_entry.evidence_id)
        self.assertIn(
            "all four department fields preserved in the raw re-export",
            evidence.verified_scope,
        )
        self.assertIn(
            "whether department fields must always be populated on both sides",
            evidence.not_verified,
        )
        self.assertFalse(evidence.production_output_enabled)

    def test_runtime_comparison_preserves_department_without_making_a_default(self) -> None:
        config = self.config()
        candidate_row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        reexport_row = list(candidate_row)
        for index, field in enumerate(
            (
                "伝番",
                "借方科目",
                "借方科目正式名称",
                "借方消費税",
                "貸方科目",
                "貸方科目正式名称",
                "貸方消費税",
            ),
            start=1,
        ):
            reexport_row[OFFICIAL_HEADER.index(field)] = str(index)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = self.write_csv(root / "candidate.csv", candidate_row)
            reexport = self.write_csv(
                root / "reexport.csv",
                reexport_row,
                include_preamble=True,
            )
            comparison = compare_generator_1111_department_runtime(
                candidate,
                reexport,
            )
            serialized = json.dumps(
                comparison.to_privacy_safe_dict(), ensure_ascii=False
            )

        statuses = {
            item.field_name: item.status for item in comparison.candidate_fields
        }
        for field in ("借方部門コード", "借方部門名称", "貸方部門コード", "貸方部門名称"):
            self.assertIs(statuses[field], RuntimeReexportFieldStatus.INPUT_PRESERVED)
        self.assertEqual(
            sum(
                status is RuntimeReexportFieldStatus.INPUT_PRESERVED
                for status in statuses.values()
            ),
            23,
        )
        self.assertIn("not generator defaults", serialized)
        for private_value in ("架空部門", "架空短", "架空旅費", "架空摘要"):
            self.assertNotIn(private_value, serialized)

    def test_1000_department_remains_inconclusive_while_registry_is_available(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(DEPARTMENT_1000_EXPERIMENT_STATUS, "INCONCLUSIVE_NOT_VERIFIED")
        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def assert_blocked(
        self,
        config: JdlGeneratorAuthored1111DepartmentConfig,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline = self.config()
            source = self.write_observed_source(root, baseline)
            with self.assertRaisesRegex(JdlGeneratorAuthored1111DepartmentError, message):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/test",
                )

    def config(self) -> JdlGeneratorAuthored1111DepartmentConfig:
        columns = {name: "" for name in OFFICIAL_HEADER}
        columns.update(
            {
                "//識別フラグ": "1111",
                "日付": "20261005",
                "借方科目名称": "架空旅費",
                "借方金額": "1700",
                "貸方科目名称": "架空現金",
                "貸方金額": "1700",
                "摘要": "架空摘要",
                "借方部門コード": "7",
                "借方部門名称": "架空短",
                "貸方部門コード": "7",
                "貸方部門名称": "架空短",
            }
        )
        decisions = {
            name: "EXPLICIT_EXPERIMENT_CONDITION_BLANK" for name in OFFICIAL_HEADER
        }
        decisions.update(
            {
                "//識別フラグ": "EXPLICIT_EXPERIMENT_INPUT",
                "伝番": "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
                "日付": "EXPLICIT_EXPERIMENT_INPUT",
                "借方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "借方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
                "借方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
                "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "摘要": "EXPLICIT_EXPERIMENT_INPUT",
                "借方部門コード": "TARGET_MASTER_CONFIRMED_DEPARTMENT_CODE",
                "借方部門名称": "OBSERVED_RUNTIME_CONFIRMED_DEPARTMENT_SHORT_NAME",
                "貸方部門コード": "TARGET_MASTER_CONFIRMED_DEPARTMENT_CODE",
                "貸方部門名称": "OBSERVED_RUNTIME_CONFIRMED_DEPARTMENT_SHORT_NAME",
            }
        )
        for name in (
            "借方課区",
            "借方税区",
            "借方税入力方法",
            "借方消費税",
            "貸方課区",
            "貸方税区",
            "貸方税入力方法",
            "貸方消費税",
            "借方取引科目",
            "貸方取引科目",
        ):
            decisions[name] = "OFFICIAL_DOCUMENTED_EXEMPT_BLANK"
        return JdlGeneratorAuthored1111DepartmentConfig(
            jdl_columns=columns,
            field_decisions=decisions,
            journal_date_iso="2026-10-05",
            target_master_validation={
                "debit_account_name_exists_in_target_master": True,
                "credit_account_name_exists_in_target_master": True,
                "department_processing_enabled": True,
                "department_code_exact_match": True,
                "department_short_name_exact_match": True,
                "both_department_sides_intentionally_populated": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            tax_validation={
                "company_tax_processing_confirmed_exempt": True,
                "tax_fields_intentionally_blank": True,
            },
            target_account_evidence=TargetAccountEvidence(
                debit_code="8001",
                debit_name="架空旅費",
                debit_formal_name="架空旅費正式",
                credit_code="1001",
                credit_name="架空現金",
                credit_formal_name="架空現金正式",
            ),
            target_department_evidence=TargetDepartmentEvidence(
                department_code="7",
                formal_name="架空部門",
                short_name="架空短",
                department_processing_enabled=True,
                confirmed_registered=True,
                no_fuzzy_matching=True,
                no_automatic_replacement=True,
            ),
            company_tax_processing=JdlTaxProcessingMode.EXEMPT.value,
        )

    def write_observed_source(
        self,
        root: Path,
        config: JdlGeneratorAuthored1111DepartmentConfig,
    ) -> Path:
        path = root / "data/private/observed_department.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = ["" for _ in OFFICIAL_HEADER]
        values = {
            "//識別フラグ": "1111",
            "伝番": "1",
            "日付": "20261004",
            "借方科目": config.target_account_evidence.debit_code,
            "借方科目名称": config.target_account_evidence.debit_name,
            "借方科目正式名称": config.target_account_evidence.debit_formal_name,
            "借方金額": "1700",
            "貸方科目": config.target_account_evidence.credit_code,
            "貸方科目名称": config.target_account_evidence.credit_name,
            "貸方科目正式名称": config.target_account_evidence.credit_formal_name,
            "貸方金額": "1700",
            "摘要": "観測元摘要",
            "借方部門コード": config.target_department_evidence.department_code,
            "借方部門名称": config.target_department_evidence.short_name,
            "貸方部門コード": config.target_department_evidence.department_code,
            "貸方部門名称": config.target_department_evidence.short_name,
        }
        for name, value in values.items():
            row[OFFICIAL_HEADER.index(name)] = value
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(["// 架空preamble"])
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path

    def write_csv(
        self,
        path: Path,
        row: list[str],
        *,
        include_preamble: bool = False,
    ) -> Path:
        with path.open("w", encoding="cp932", newline="") as handle:
            if include_preamble:
                handle.write("// synthetic metadata\r\n")
                handle.write("// synthetic period\r\n")
                handle.write("\r\n")
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from experiments.jdl_import.exp01_candidate import (
    OFFICIAL_HEADER,
    JdlExp01CandidateError,
)
from experiments.jdl_import.generator_authored_1000_department import (
    DEPARTMENT_SIDE,
    EXPERIMENT_STATUS,
    JdlGeneratorAuthored1000DepartmentConfig,
    JdlGeneratorAuthored1000DepartmentError,
    TargetDepartmentEvidence,
    generate_candidate,
)


class JdlGeneratorAuthored1000DepartmentTests(unittest.TestCase):
    def test_generates_debit_department_only_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/department",
            )
            raw = result.csv_path.read_bytes()
            rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 2)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual(len(rows[1]), 30)
        self.assertEqual(
            rows[1][OFFICIAL_HEADER.index("借方部門コード")],
            config.target_department_evidence.department_code,
        )
        self.assertEqual(
            rows[1][OFFICIAL_HEADER.index("借方部門名称")],
            config.target_department_evidence.short_name,
        )
        self.assertEqual(rows[1][OFFICIAL_HEADER.index("貸方部門コード")], "")
        self.assertEqual(rows[1][OFFICIAL_HEADER.index("貸方部門名称")], "")
        for field in ("借方補助", "借方補助名称", "貸方補助", "貸方補助名称"):
            self.assertEqual(rows[1][OFFICIAL_HEADER.index(field)], "")
        self.assertEqual(report["status"], EXPERIMENT_STATUS)
        self.assertEqual(report["department_master_validation"]["side"], DEPARTMENT_SIDE)
        self.assertTrue(
            report["department_master_validation"]["csv_name_uses_confirmed_short_name"]
        )
        self.assertEqual(manifest["actual_result"], "UNTESTED")
        self.assertEqual(
            manifest["changed_from_successful_1000_fields"],
            ["借方部門コード", "借方部門名称"],
        )
        self.assertEqual(manifest["validation"]["implicit_default_count"], 0)
        self.assertFalse(manifest["source_jdl_row_used_for_construction"])
        self.assertFalse(manifest["production_ready"])

    def test_department_processing_disabled_is_blocked(self) -> None:
        config = self.config()
        evidence = replace(
            config.target_department_evidence,
            department_processing_enabled=False,
        )
        config = replace(config, target_department_evidence=evidence)

        self.assert_blocked(config, "must be explicitly confirmed")

    def test_department_code_or_name_mismatch_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["借方部門コード"] = "8"

        self.assert_blocked(config, "do not exactly match")

    def test_full_name_is_not_truncated_or_substituted_for_short_name(self) -> None:
        config = self.config()
        config.jdl_columns["借方部門名称"] = config.target_department_evidence.department_name

        self.assert_blocked(config, "confirmed target code and short-name")

    def test_department_validation_confirmation_false_is_blocked(self) -> None:
        config = self.config()
        config.target_master_validation["department_processing_enabled"] = False

        self.assert_blocked(config, "confirmations must all be true")

    def test_credit_department_population_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["貸方部門コード"] = "7"
        config.jdl_columns["貸方部門名称"] = "架空部"

        self.assert_blocked(config, "credit department fields must remain blank")

    def test_subaccount_population_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["貸方補助"] = "7"
        config.jdl_columns["貸方補助名称"] = "架空補"

        self.assert_blocked(config, "all subaccount fields must remain blank")

    def test_any_change_beyond_debit_department_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["摘要"] = "変更摘要"

        self.assert_blocked(config, "only debit department")

    def test_report_and_manifest_are_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/test",
            )
            serialized = (
                result.report_path.read_text(encoding="utf-8")
                + result.manifest_path.read_text(encoding="utf-8")
            )

        for value in ("架空部門", "架空", "架空現", "架空預", "架空摘要", "1300"):
            self.assertNotIn(value, serialized)

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            output = root / "data/private/experiments/test"
            first = generate_candidate(config, source, output)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(JdlExp01CandidateError, "already exists"):
                generate_candidate(config, source, output)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def assert_blocked(
        self,
        config: JdlGeneratorAuthored1000DepartmentConfig,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_base_candidate(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1000DepartmentError,
                message,
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def config(self) -> JdlGeneratorAuthored1000DepartmentConfig:
        columns = {name: "" for name in OFFICIAL_HEADER}
        columns.update(
            {
                "//識別フラグ": "1000",
                "日付": "20261003",
                "借方科目名称": "架空現",
                "借方金額": "1300",
                "貸方科目名称": "架空預",
                "貸方金額": "1300",
                "摘要": "架空摘要",
                "借方部門コード": "7",
                "借方部門名称": "架空",
            }
        )
        return JdlGeneratorAuthored1000DepartmentConfig(
            jdl_columns=columns,
            journal_date_iso="2026-10-03",
            target_master_validation={
                "debit_account_exists_in_target_master": True,
                "credit_account_exists_in_target_master": True,
                "debit_subaccount_blank_or_exists_under_parent": True,
                "credit_subaccount_blank_or_exists_under_parent": True,
                "no_fuzzy_matching_or_auto_replacement": True,
                "department_processing_enabled": True,
                "debit_department_exists_in_target_master": True,
                "credit_department_blank_or_exists_in_target_master": True,
            },
            tax_validation={
                "company_tax_processing_confirmed": True,
                "tax_category_abbreviations_confirmed_when_used": False,
                "tax_scope_tax_category_combination_confirmed_when_used": False,
                "transaction_account_confirmed_when_used": False,
            },
            target_department_evidence=TargetDepartmentEvidence(
                department_code="7",
                department_name="架空部門",
                short_name="架空",
                department_processing_enabled=True,
                confirmed_registered=True,
                no_fuzzy_matching=True,
                no_automatic_replacement=True,
            ),
            company_tax_processing=JdlTaxProcessingMode.EXEMPT.value,
        )

    def write_base_candidate(
        self,
        root: Path,
        config: JdlGeneratorAuthored1000DepartmentConfig,
    ) -> Path:
        path = root / "data/private/base_candidate.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        row[OFFICIAL_HEADER.index("借方部門コード")] = ""
        row[OFFICIAL_HEADER.index("借方部門名称")] = ""
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path


if __name__ == "__main__":
    unittest.main()

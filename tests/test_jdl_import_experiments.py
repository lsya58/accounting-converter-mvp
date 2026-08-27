from __future__ import annotations

import csv
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.diagnostics.jdl_csv import JdlCsvStructuralAnalyzer
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)

from experiments.jdl_import.generate_cases import (
    EXPERIMENT_IDS,
    JdlImportExperimentConfig,
    generate_all_cases,
)


class JdlImportExperimentGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = jdl_ibex_cashbook_35_5_observed_schema()
        self.config = JdlImportExperimentConfig(
            debit_account_code="D001",
            debit_account_name="架空借方科目",
            credit_account_code="C001",
            credit_account_name="架空貸方科目",
            amount="1000",
            tax_category="架空税区分",
            tax_amount="100",
            existing_subaccount_code="S001",
            existing_subaccount_name="事前登録架空補助",
            nonexistent_subaccount_code="S999",
            nonexistent_subaccount_name="存在しない架空補助",
        )

    def test_generate_all_experiment_cases_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = generate_all_cases(self.config, Path(tmpdir))

            self.assertEqual(
                [case.experiment_id for case in cases],
                list(EXPERIMENT_IDS),
            )
            for case in cases:
                self.assertTrue(case.csv_path.exists())
            manifest = json.loads(
                (Path(tmpdir) / "experiment_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["schema_status"], "OBSERVED_ONLY")
            self.assertEqual(manifest["encoding"], "cp932")
            self.assertEqual(manifest["line_ending"], "CRLF")
            self.assertFalse(manifest["bom"])
            self.assertEqual(manifest["journal_column_count"], 30)
            self.assertEqual(
                {item["actual_result"] for item in manifest["experiments"]},
                {"UNTESTED"},
            )
            self.assertEqual(
                set(manifest["result_status_values"]),
                {"PASS", "REJECTED", "UNTESTED"},
            )

    def test_generated_csv_is_cp932_crlf_bomless_and_structurally_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = generate_all_cases(self.config, Path(tmpdir))
            analyzer = JdlCsvStructuralAnalyzer(observed_schema=self.schema)

            for case in cases:
                raw = case.csv_path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                self.assertIn(b"\r\n", raw)
                self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
                raw.decode("cp932")

                result = analyzer.analyze_path(case.csv_path)
                self.assertEqual(result.encoding, "cp932")
                self.assertEqual(result.line_ending, "CRLF")
                self.assertFalse(result.has_bom)
                self.assertEqual(result.header_columns, self.schema.observed_header)
                self.assertEqual(result.header_column_count, 30)
                self.assertEqual(result.analysis_errors, ())
                self.assertTrue(
                    all(line.column_count == 30 for line in result.journal_record_lines)
                )

    def test_generated_cases_are_balanced_without_asserting_jdl_import_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = generate_all_cases(self.config, Path(tmpdir))

            for case in cases:
                rows = self._journal_rows(case.csv_path)
                debit_total = sum(
                    (self._amount(row, "借方金額") for row in rows),
                    Decimal("0"),
                )
                credit_total = sum(
                    (self._amount(row, "貸方金額") for row in rows),
                    Decimal("0"),
                )
                self.assertEqual(debit_total, credit_total)

    def test_case_variables_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_all_cases(self.config, Path(tmpdir))

            minimal = self._journal_rows(Path(tmpdir) / "EXP-01_minimal_simple.csv")
            description = self._journal_rows(Path(tmpdir) / "EXP-02_with_description.csv")
            tax = self._journal_rows(Path(tmpdir) / "EXP-03_with_tax.csv")
            existing_sub = self._journal_rows(Path(tmpdir) / "EXP-04_existing_subaccount.csv")
            nonexistent_sub = self._journal_rows(Path(tmpdir) / "EXP-05_nonexistent_subaccount.csv")
            multi = self._journal_rows(Path(tmpdir) / "EXP-06_observed_multi_record_sequence.csv")

            self.assertEqual(minimal[0]["借方補助名称"], "")
            self.assertNotEqual(minimal[0]["摘要"], description[0]["摘要"])
            self.assertEqual(tax[0]["借方税区"], "架空税区分")
            self.assertEqual(tax[0]["借方消費税"], "100")
            self.assertEqual(existing_sub[0]["借方補助名称"], "事前登録架空補助")
            self.assertEqual(nonexistent_sub[0]["借方補助名称"], "存在しない架空補助")
            self.assertEqual(
                [row["//識別フラグ"] for row in multi],
                ["1110", "1100", "1101"],
            )

    def test_config_requires_account_values_from_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "明示指定"):
                generate_all_cases(
                    JdlImportExperimentConfig(
                        debit_account_code="",
                        debit_account_name="",
                        credit_account_code="",
                        credit_account_name="",
                    ),
                    Path(tmpdir),
                )

    def _journal_rows(self, path: Path) -> list[dict[str, str]]:
        lines = path.read_text(encoding="cp932").splitlines()
        header_index = lines.index(",".join(self.schema.observed_header))
        reader = csv.DictReader(lines[header_index:])
        return list(reader)

    def _amount(self, row: dict[str, str], key: str) -> Decimal:
        value = row[key]
        if value == "":
            return Decimal("0")
        return Decimal(value)


if __name__ == "__main__":
    unittest.main()

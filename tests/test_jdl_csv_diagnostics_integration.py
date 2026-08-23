import json
import subprocess
import sys
import unittest
from pathlib import Path

from accounting_converter.diagnostics.jdl_csv import (
    AccountingSide,
    DiagnosticAssociationStatus,
    FieldResolutionStatus,
    JdlCsvDiagnosticReportGenerator,
    JdlCsvStructuralAnalyzer,
    JdlMasterType,
    analysis_to_dict,
)
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "jdl"


class JdlCsvDiagnosticsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = JdlCsvStructuralAnalyzer(
            observed_schema=jdl_ibex_cashbook_35_5_observed_schema()
        )

    def analyze_fixture(self, name: str):
        return self.analyzer.analyze_path(FIXTURE_DIR / name)

    def test_valid_simple_fixture(self) -> None:
        result = self.analyze_fixture("valid_simple.csv")

        self.assertEqual(result.encoding, "cp932")
        self.assertFalse(result.has_bom)
        self.assertEqual(result.line_ending, "CRLF")
        self.assertEqual(result.data_line_count, 2)
        self.assertEqual(len(result.diagnostic_message_lines), 0)
        self.assertEqual(len(result.analysis_errors), 0)
        self.assertEqual(len(result.analysis_warnings), 0)
        self.assertEqual(result.schema_fingerprint.record_column_counts, ((30, 2),))
        self.assertEqual(
            result.observed_grouping_summary.total_candidate_count,
            2,
        )
        self.assertEqual(
            result.observed_grouping_summary.single_record_candidate_count,
            2,
        )

    def test_subaccount_mismatch_fixture(self) -> None:
        result = self.analyze_fixture("subaccount_mismatch.csv")

        self.assertEqual(result.data_line_count, 2)
        self.assertEqual(len(result.diagnostic_message_lines), 2)
        self.assertEqual(result.master_mismatch_summary.total_count, 2)
        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.master_type, JdlMasterType.SUB_ACCOUNT)
        self.assertEqual(issue.side, AccountingSide.DEBIT)
        self.assertEqual(issue.source_value, "PayPay")
        self.assertEqual(issue.account_value, "売掛金")
        self.assertEqual(
            issue.association_status,
            DiagnosticAssociationStatus.LINKED_TO_PREVIOUS_RECORD,
        )
        self.assertEqual(
            issue.field_resolution_status,
            FieldResolutionStatus.FROM_OBSERVED_SCHEMA,
        )

    def test_account_mismatch_fixture(self) -> None:
        result = self.analyze_fixture("account_mismatch.csv")

        self.assertEqual(result.data_line_count, 1)
        self.assertEqual(len(result.diagnostic_message_lines), 1)
        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.master_type, JdlMasterType.ACCOUNT)
        self.assertEqual(issue.side, AccountingSide.DEBIT)
        self.assertEqual(issue.source_value, "999 架空科目A")

    def test_padded_diagnostic_fixture(self) -> None:
        result = self.analyze_fixture("padded_diagnostic.csv")

        self.assertEqual(result.data_line_count, 1)
        self.assertEqual(len(result.diagnostic_message_lines), 1)
        self.assertEqual(result.diagnostic_message_lines[0].column_count, 30)
        self.assertEqual(result.master_mismatch_summary.total_count, 1)
        self.assertEqual(result.schema_fingerprint.record_column_counts, ((30, 1),))

    def test_malformed_columns_fixture(self) -> None:
        result = self.analyze_fixture("malformed_columns.csv")

        self.assertEqual(result.data_line_count, 1)
        self.assertTrue(
            any(error.rule_id == "JDLCSV-COLUMN-COUNT" for error in result.analysis_errors)
        )
        self.assertEqual(result.schema_fingerprint.record_column_counts, ((29, 1),))

    def test_mixed_errors_fixture(self) -> None:
        result = self.analyze_fixture("mixed_errors.csv")

        self.assertEqual(result.data_line_count, 4)
        self.assertEqual(len(result.diagnostic_message_lines), 4)
        self.assertEqual(result.master_mismatch_summary.total_count, 4)
        self.assertIn(("ACCOUNT", 2), result.master_mismatch_summary.counts_by_master_type)
        self.assertIn(
            ("SUB_ACCOUNT", 2),
            result.master_mismatch_summary.counts_by_master_type,
        )
        sides = {(issue.master_type, issue.side) for issue in result.diagnostic_issues}
        self.assertIn((JdlMasterType.ACCOUNT, AccountingSide.DEBIT), sides)
        self.assertIn((JdlMasterType.ACCOUNT, AccountingSide.CREDIT), sides)
        self.assertIn((JdlMasterType.SUB_ACCOUNT, AccountingSide.DEBIT), sides)
        self.assertIn((JdlMasterType.SUB_ACCOUNT, AccountingSide.CREDIT), sides)

    def test_report_and_json_are_generated_from_fixture(self) -> None:
        result = self.analyze_fixture("subaccount_mismatch.csv")

        report = JdlCsvDiagnosticReportGenerator().generate_text(result)
        data = analysis_to_dict(result)

        self.assertIn("JDL CSV 診断結果", report)
        self.assertIn("正式なJDL取込可否を断定しません", report)
        self.assertEqual(data["data_record_count"], 2)
        self.assertIsNone(data["journal_count"])
        self.assertEqual(data["diagnostic_count"], 2)
        self.assertEqual(data["observed_schema"]["is_formal_format_profile"], False)
        self.assertEqual(data["schema_fingerprint"]["column_count"], 30)

    def test_cli_text_output(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "accounting_converter.cli",
                "diagnose",
                str(FIXTURE_DIR / "subaccount_mismatch.csv"),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("JDL CSV 診断結果", completed.stdout)
        self.assertIn("仕訳件数", completed.stdout)
        self.assertIn("補助科目不一致", completed.stdout)

    def test_cli_json_output(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "accounting_converter.cli",
                "diagnose",
                str(FIXTURE_DIR / "mixed_errors.csv"),
                "--format",
                "json",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        data = json.loads(completed.stdout)
        self.assertEqual(data["data_record_count"], 4)
        self.assertIsNone(data["journal_count"])
        self.assertEqual(data["diagnostic_count"], 4)
        self.assertEqual(data["master_mismatch_summary"]["total_count"], 4)
        self.assertEqual(
            data["observed_grouping_summary"]["total_candidate_count"],
            4,
        )
        self.assertIsNone(data["journal_count"])


if __name__ == "__main__":
    unittest.main()

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
    analysis_to_privacy_safe_dict,
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
                "--compare-observed",
                "jdl-ibex-cashbook-35.5",
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
                "--compare-observed",
                "jdl-ibex-cashbook-35.5",
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

    def test_synthetic_preamble_export_fixture_preserves_structural_observations(self) -> None:
        result = self.analyze_fixture("synthetic_preamble_export.csv")

        self.assertEqual(result.encoding, "cp932")
        self.assertEqual(result.line_ending, "CRLF")
        self.assertFalse(result.has_bom)
        self.assertEqual(result.metadata_line_count, 2)
        self.assertEqual(len(result.empty_lines), 1)
        self.assertEqual(result.header_row_number, 4)
        self.assertEqual(result.header_column_count, 30)
        self.assertEqual(result.data_record_count, 5)
        self.assertEqual(result.schema_fingerprint.record_column_counts, ((30, 5),))
        self.assertEqual(
            dict(result.identifier_flag_counts),
            {"1000": 1, "1100": 1, "1101": 1, "1110": 1, "1111": 1},
        )
        grouping = result.observed_grouping_summary
        self.assertEqual(grouping.total_candidate_count, 3)
        self.assertEqual(grouping.single_record_candidate_count, 2)
        self.assertEqual(grouping.multi_record_candidate_count, 1)
        self.assertEqual(grouping.valid_multi_record_sequence_count, 1)
        self.assertEqual(grouping.same_voucher_number_count, 1)
        self.assertEqual(grouping.same_date_count, 1)
        self.assertEqual(grouping.balanced_multi_record_candidate_count, 1)

    def test_schema_independent_diagnose_does_not_label_unknown_version_as_35_5(self) -> None:
        result = JdlCsvStructuralAnalyzer().analyze_path(
            FIXTURE_DIR / "synthetic_preamble_export.csv"
        )

        self.assertEqual(result.header_row_number, 4)
        self.assertEqual(result.header_column_count, 30)
        self.assertEqual(result.data_record_count, 5)
        self.assertIsNone(result.observed_schema)
        self.assertEqual(
            result.observed_grouping_summary.total_candidate_count,
            0,
        )

    def test_explicit_observed_schema_comparison_enables_grouping(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "accounting_converter.cli",
                "diagnose-jdl",
                str(FIXTURE_DIR / "synthetic_preamble_export.csv"),
                "--compare-observed",
                "jdl-ibex-cashbook-35.5",
                "--format",
                "json",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        data = json.loads(completed.stdout)
        self.assertEqual(data["observed_schema"]["observed_version"], "35.5")
        self.assertEqual(
            data["observed_grouping_summary"]["total_candidate_count"],
            3,
        )
        self.assertFalse(data["observed_schema"]["is_formal_format_profile"])

    def test_privacy_safe_serialization_omits_journal_body_values(self) -> None:
        result = self.analyze_fixture("synthetic_preamble_export.csv")

        data = analysis_to_privacy_safe_dict(result)
        serialized = json.dumps(data, ensure_ascii=False)

        self.assertIsNone(data["file_name"])
        self.assertEqual(data["header_column_count"], 30)
        self.assertEqual(data["data_record_count"], 5)
        self.assertEqual(
            data["observed_grouping_summary"]["total_candidate_count"],
            3,
        )
        self.assertNotIn("9001", serialized)
        self.assertNotIn("2099/01/01", serialized)
        self.assertNotIn("1000.0", serialized)
        self.assertNotIn("架空摘要", serialized)
        self.assertNotIn("架空借方科目", serialized)

    def test_compare_jdl_cli_reports_schema_differences_only(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "accounting_converter.cli",
                "compare-jdl",
                str(FIXTURE_DIR / "valid_simple.csv"),
                str(FIXTURE_DIR / "synthetic_preamble_export.csv"),
                "--format",
                "json",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        data = json.loads(completed.stdout)
        self.assertTrue(data["has_differences"])
        fields = {difference["field"] for difference in data["differences"]}
        self.assertIn("metadata_pattern", fields)
        self.assertIn("record_column_counts", fields)
        self.assertIn("構造差分のみ", data["judgment"])


if __name__ == "__main__":
    unittest.main()

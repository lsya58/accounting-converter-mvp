from __future__ import annotations

import csv
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from accounting_converter.cli import main
from accounting_converter.diagnostics.yayoi_csv import (
    YayoiCsvAnalyzer,
    YayoiCsvDiagnosticReportGenerator,
    yayoi_analysis_to_dict,
    yayoi_analysis_to_privacy_safe_dict,
)
from accounting_converter.diagnostics.yayoi_csv.models import (
    YayoiGroupCandidateStatus,
    YayoiStructuralMatchStatus,
)
from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)


class YayoiCsvDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = yayoi_accounting_05_official_import_spec()
        self.analyzer = YayoiCsvAnalyzer(self.spec)

    def test_25_column_candidate_with_official_header(self) -> None:
        text = self._csv_text([self.spec.column_names, self._row("2000")])

        analysis = self.analyzer.analyze_text(text)

        self.assertTrue(analysis.header_observation.detected)
        self.assertEqual(analysis.data_record_count, 1)
        self.assertEqual(analysis.dominant_column_count, 25)
        self.assertEqual(
            analysis.official_comparison.structural_match_status,
            YayoiStructuralMatchStatus.MATCH_CANDIDATE,
        )
        self.assertFalse(analysis.official_comparison.formal_profile_ready)

    def test_header_absent_does_not_make_first_data_row_header(self) -> None:
        text = self._csv_text([self._row("2000")])

        analysis = self.analyzer.analyze_text(text)

        self.assertFalse(analysis.header_observation.detected)
        self.assertEqual(analysis.data_record_count, 1)
        self.assertEqual(analysis.line_observations[0].classification.value, "DATA_RECORD")

    def test_invalid_column_count_is_structural_difference(self) -> None:
        text = self._csv_text([self._row("2000")[:-1]])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.dominant_column_count, 24)
        self.assertEqual(
            analysis.official_comparison.structural_match_status,
            YayoiStructuralMatchStatus.STRUCTURAL_DIFFERENCE,
        )
        self.assertEqual(analysis.official_comparison.missing_column_count, 1)

    def test_unknown_flag_is_reported_as_unknown_observed_flag(self) -> None:
        text = self._csv_text([self._row("9999")])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(dict(analysis.flag_observation.unknown_flag_counts), {"9999": 1})
        self.assertTrue(
            any(result.rule_id == "UNKNOWN_OBSERVED_FLAG" for result in analysis.validation_results)
        )

    def test_malformed_multi_sequence_is_not_silently_repaired(self) -> None:
        text = self._csv_text([self._row("2110"), self._row("2000")])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.malformed_group_candidate_count, 1)
        self.assertEqual(
            analysis.group_candidates[0].status,
            YayoiGroupCandidateStatus.MALFORMED_SEQUENCE,
        )
        self.assertEqual(analysis.group_candidates[1].status, YayoiGroupCandidateStatus.OBSERVED_SINGLE_RECORD)

    def test_unclosed_multi_sequence_is_preserved_as_unclosed(self) -> None:
        text = self._csv_text([self._row("2110"), self._row("2100")])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.group_candidates[0].status, YayoiGroupCandidateStatus.UNCLOSED_SEQUENCE)
        self.assertEqual(analysis.group_candidates[0].record_count, 2)

    def test_valid_multi_sequence_counts_candidate(self) -> None:
        text = self._csv_text(
            [self._row("2110", debit=300), self._row("2100", debit=700), self._row("2101", credit=1000)]
        )

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.group_candidate_count, 1)
        self.assertEqual(analysis.multi_record_candidate_count, 1)
        self.assertEqual(analysis.group_candidates[0].middle_2100_count, 1)

    def test_amount_parse_error_is_not_converted_to_zero(self) -> None:
        row = list(self._row("2000"))
        row[8] = "not-an-amount"
        text = self._csv_text([tuple(row)])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.amount_observation.amount_parse_error_count, 1)
        self.assertIsNone(analysis.amount_observation.balanced)

    def test_quoted_comma_description_does_not_leak_to_report_or_json(self) -> None:
        row = self._row("2000", description='架空摘要, "引用符"あり')
        text = self._csv_text([row])

        analysis = self.analyzer.analyze_text(text)
        report = YayoiCsvDiagnosticReportGenerator().generate_text(analysis)
        payload = json.dumps(yayoi_analysis_to_dict(analysis), ensure_ascii=False)

        self.assertTrue(analysis.csv_parseable)
        self.assertNotIn("架空摘要", report)
        self.assertNotIn("架空摘要", payload)
        self.assertNotIn("引用符", report)
        self.assertNotIn("引用符", payload)

    def test_blank_non_amount_fields_are_allowed(self) -> None:
        row = self._row("2000", sub_account="", department="", tax_category="")
        text = self._csv_text([row])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.amount_observation.amount_parse_error_count, 0)
        self.assertEqual(analysis.amount_observation.amount_unknown_count, 0)

    def test_blank_amount_is_unknown_not_zero(self) -> None:
        row = list(self._row("2000"))
        row[8] = ""
        text = self._csv_text([tuple(row)])

        analysis = self.analyzer.analyze_text(text)

        self.assertEqual(analysis.amount_observation.amount_unknown_count, 1)
        self.assertIsNone(analysis.amount_observation.balanced)

    def test_crlf_cp932_without_bom_is_observed(self) -> None:
        text = self._csv_text([self._row("2000")], newline="\r\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yayoi_demo.csv"
            path.write_bytes(text.encode("cp932"))

            analysis = self.analyzer.analyze_path(path)

        self.assertEqual(analysis.encoding, "cp932")
        self.assertEqual(analysis.line_ending, "CRLF")
        self.assertFalse(analysis.has_bom)

    def test_utf8_bom_is_observed(self) -> None:
        text = self._csv_text([self._row("2000")], newline="\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yayoi_demo.csv"
            path.write_bytes(("\ufeff" + text).encode("utf-8"))

            analysis = self.analyzer.analyze_path(path)

        self.assertEqual(analysis.encoding, "utf-8-sig")
        self.assertTrue(analysis.has_bom)

    def test_cli_diagnose_yayoi_json(self) -> None:
        text = self._csv_text([self._row("2000")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yayoi_demo.csv"
            path.write_text(text, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                result = main(["diagnose-yayoi", str(path), "--format", "json"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["data_record_count"], 1)

    def test_japanese_era_date_candidate_is_observed_without_formal_conversion(self) -> None:
        row = list(self._row("2000"))
        row[3] = "H.31/01/15"
        text = self._csv_text([tuple(row)])

        analysis = self.analyzer.analyze_text(text)

        self.assertIn(
            "JAPANESE_ERA_DOT_SLASH",
            analysis.amount_observation.date_format_candidates,
        )
        self.assertEqual(
            analysis.amount_observation.date_parse_candidate_error_count,
            0,
        )
        self.assertFalse(analysis.official_comparison.formal_profile_ready)

    def test_field_population_observes_tax_and_trailing_empty_fields_without_values(self) -> None:
        row = self._row("2000", tax_category="架空税区分")
        text = self._csv_text([row])

        analysis = self.analyzer.analyze_text(text)
        population = analysis.field_population_observation

        self.assertEqual(dict(population.tax_field_nonempty_counts)["debit_tax_category"], 1)
        self.assertEqual(dict(population.tax_field_nonempty_counts)["credit_tax_category"], 1)
        self.assertIn((8, 1), population.nonempty_field_counts_by_position)
        self.assertIn((18, 1), population.empty_field_counts_by_position)
        self.assertEqual(
            dict(population.trailing_empty_field_count_distribution),
            {8: 1},
        )

    def test_ae19_observed_synthetic_fixture_matches_25_field_raw_export_shape(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt")
        raw = path.read_bytes()

        analysis = self.analyzer.analyze_path(path)

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(analysis.encoding, "cp932")
        self.assertEqual(analysis.line_ending, "CRLF")
        self.assertEqual(analysis.total_physical_lines, 1)
        self.assertEqual(analysis.data_record_count, 1)
        self.assertEqual(analysis.dominant_column_count, 25)
        self.assertEqual(analysis.row_column_count_distribution, ((25, 1),))
        self.assertEqual(dict(analysis.flag_observation.official_flag_counts), {"2000": 1})
        self.assertEqual(analysis.single_record_candidate_count, 1)
        self.assertTrue(analysis.amount_observation.balanced)
        self.assertEqual(
            dict(
                analysis.field_population_observation.trailing_empty_field_count_distribution
            ),
            {0: 1},
        )
        self.assertIn(
            (20, 1),
            analysis.field_population_observation.nonempty_field_counts_by_position,
        )
        self.assertIn(
            (25, 1),
            analysis.field_population_observation.nonempty_field_counts_by_position,
        )
        self.assertIn(
            "JAPANESE_ERA_DOT_SLASH",
            analysis.amount_observation.date_format_candidates,
        )
        self.assertEqual(
            analysis.official_comparison.structural_match_status,
            YayoiStructuralMatchStatus.MATCH_CANDIDATE,
        )
        self.assertFalse(analysis.official_comparison.formal_profile_ready)

    def test_yayoi_privacy_safe_serialization_omits_accounting_body_values(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt")
        analysis = self.analyzer.analyze_path(path)

        payload = yayoi_analysis_to_privacy_safe_dict(analysis)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertIsNone(payload["file_name"])
        self.assertEqual(payload["dominant_column_count"], 25)
        self.assertEqual(payload["flags"]["official_flag_counts"], {"2000": 1})
        self.assertNotIn("架空観測摘要", serialized)
        self.assertNotIn("架空費用科目", serialized)
        self.assertNotIn("H.31/01/15", serialized)
        self.assertNotIn("1234", serialized)

    def test_yayoi_text_report_redacts_totals_for_single_record_files(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt")
        analysis = self.analyzer.analyze_path(path)

        report = YayoiCsvDiagnosticReportGenerator().generate_text(analysis)

        self.assertIn("debit total: redacted", report)
        self.assertNotIn("1234", report)
        self.assertNotIn("架空観測摘要", report)

    def test_ae19_observed_multi_synthetic_fixture_preserves_multi_record_shape(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_multi_synthetic.txt")
        raw = path.read_bytes()

        analysis = self.analyzer.analyze_path(path)

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(analysis.encoding, "cp932")
        self.assertEqual(analysis.line_ending, "CRLF")
        self.assertEqual(analysis.total_physical_lines, 4)
        self.assertTrue(analysis.csv_parseable)
        self.assertEqual(analysis.data_record_count, 4)
        self.assertEqual(analysis.group_candidate_count, 4)
        self.assertEqual(analysis.single_record_candidate_count, 4)
        self.assertEqual(analysis.dominant_column_count, 25)
        self.assertEqual(analysis.row_column_count_distribution, ((25, 4),))
        self.assertEqual(dict(analysis.flag_observation.official_flag_counts), {"2000": 4})
        self.assertEqual(
            dict(
                analysis.field_population_observation.trailing_empty_field_count_distribution
            ),
            {0: 4},
        )
        self.assertIn(
            (17, 1),
            analysis.field_population_observation.empty_field_counts_by_position,
        )
        self.assertEqual(
            dict(analysis.field_population_observation.tax_field_nonempty_counts),
            {
                "credit_tax_amount": 4,
                "credit_tax_category": 4,
                "debit_tax_amount": 4,
                "debit_tax_category": 4,
            },
        )
        self.assertTrue(analysis.amount_observation.balanced)
        self.assertEqual(analysis.validation_results, ())

    def test_sub_account_population_is_observed_without_values(self) -> None:
        rows = [
            self._row("2000", sub_account=""),
            self._row("2000", sub_account="架空補助科目"),
        ]

        analysis = self.analyzer.analyze_text(self._csv_text(rows))
        population = dict(
            analysis.field_population_observation.sub_account_field_population_counts
        )

        self.assertEqual(
            population,
            {
                "credit_sub_account": {"blank": 2, "nonempty": 0},
                "debit_sub_account": {"blank": 1, "nonempty": 1},
            },
        )
        serialized = json.dumps(
            yayoi_analysis_to_privacy_safe_dict(analysis),
            ensure_ascii=False,
        )
        self.assertIn("debit_sub_account", serialized)
        self.assertNotIn("架空補助科目", serialized)

    def test_ae19_observed_subaccount_synthetic_fixture_preserves_subaccount_shape(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_subaccount_synthetic.txt")
        raw = path.read_bytes()

        analysis = self.analyzer.analyze_path(path)
        population = dict(
            analysis.field_population_observation.sub_account_field_population_counts
        )

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(analysis.encoding, "cp932")
        self.assertEqual(analysis.line_ending, "CRLF")
        self.assertEqual(analysis.data_record_count, 1)
        self.assertEqual(analysis.dominant_column_count, 25)
        self.assertEqual(dict(analysis.flag_observation.official_flag_counts), {"2000": 1})
        self.assertEqual(
            population,
            {
                "credit_sub_account": {"blank": 1, "nonempty": 0},
                "debit_sub_account": {"blank": 0, "nonempty": 1},
            },
        )
        self.assertTrue(analysis.amount_observation.balanced)
        self.assertFalse(analysis.official_comparison.formal_profile_ready)

    def test_department_population_is_observed_without_values(self) -> None:
        rows = [
            self._row("2000", department=""),
            self._row("2000", department="架空部門"),
        ]

        analysis = self.analyzer.analyze_text(self._csv_text(rows))
        population = dict(
            analysis.field_population_observation.department_field_population_counts
        )

        self.assertEqual(
            population,
            {
                "credit_department": {"blank": 1, "nonempty": 1},
                "debit_department": {"blank": 1, "nonempty": 1},
            },
        )
        serialized = json.dumps(
            yayoi_analysis_to_privacy_safe_dict(analysis),
            ensure_ascii=False,
        )
        self.assertIn("debit_department", serialized)
        self.assertNotIn("架空部門", serialized)

    def test_ae19_observed_department_synthetic_fixture_preserves_department_shape(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_department_synthetic.txt")
        raw = path.read_bytes()

        analysis = self.analyzer.analyze_path(path)
        population = dict(
            analysis.field_population_observation.department_field_population_counts
        )

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(analysis.encoding, "cp932")
        self.assertEqual(analysis.line_ending, "CRLF")
        self.assertEqual(analysis.data_record_count, 1)
        self.assertEqual(analysis.dominant_column_count, 25)
        self.assertEqual(dict(analysis.flag_observation.official_flag_counts), {"2000": 1})
        self.assertEqual(
            population,
            {
                "credit_department": {"blank": 1, "nonempty": 0},
                "debit_department": {"blank": 0, "nonempty": 1},
            },
        )
        self.assertTrue(analysis.amount_observation.balanced)
        self.assertFalse(analysis.official_comparison.formal_profile_ready)

    def test_credit_field_population_is_observed_without_values(self) -> None:
        blank_row = list(self._row("2000", sub_account="", department=""))
        credit_row = list(self._row("2000", sub_account="", department=""))
        credit_row[11] = "架空貸方補助科目"
        credit_row[12] = "架空貸方部門"

        analysis = self.analyzer.analyze_text(
            self._csv_text([tuple(blank_row), tuple(credit_row)])
        )
        sub_account_population = dict(
            analysis.field_population_observation.sub_account_field_population_counts
        )
        department_population = dict(
            analysis.field_population_observation.department_field_population_counts
        )

        self.assertEqual(
            sub_account_population,
            {
                "credit_sub_account": {"blank": 1, "nonempty": 1},
                "debit_sub_account": {"blank": 2, "nonempty": 0},
            },
        )
        self.assertEqual(
            department_population,
            {
                "credit_department": {"blank": 1, "nonempty": 1},
                "debit_department": {"blank": 2, "nonempty": 0},
            },
        )
        serialized = json.dumps(
            yayoi_analysis_to_privacy_safe_dict(analysis),
            ensure_ascii=False,
        )
        self.assertIn("credit_sub_account", serialized)
        self.assertIn("credit_department", serialized)
        self.assertNotIn("架空貸方補助科目", serialized)
        self.assertNotIn("架空貸方部門", serialized)

    def test_ae19_multi_privacy_safe_serialization_omits_description_and_amounts(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_multi_synthetic.txt")
        analysis = self.analyzer.analyze_path(path)

        serialized = json.dumps(
            yayoi_analysis_to_privacy_safe_dict(analysis),
            ensure_ascii=False,
        )

        self.assertIn('"data_record_count": 4', serialized)
        self.assertNotIn("架空,摘要", serialized)
        self.assertNotIn("架空借方科目", serialized)
        self.assertNotIn("1100", serialized)
        self.assertNotIn("H.31/02", serialized)

    def test_cli_diagnose_yayoi_privacy_json(self) -> None:
        path = Path("tests/fixtures/yayoi/ae19_observed_single_synthetic.txt")
        output = StringIO()
        with redirect_stdout(output):
            result = main(["diagnose-yayoi", str(path), "--format", "privacy-json"])

        data = json.loads(output.getvalue())

        self.assertEqual(result, 0)
        self.assertEqual(data["data_record_count"], 1)
        self.assertEqual(data["flags"]["official_flag_counts"], {"2000": 1})
        self.assertNotIn("架空観測摘要", output.getvalue())

    def _row(
        self,
        flag: str,
        debit: int = 1000,
        credit: int = 1000,
        description: str = "架空取引",
        sub_account: str = "架空補助",
        department: str = "架空部門",
        tax_category: str = "対象外",
    ) -> tuple[str, ...]:
        row = [""] * self.spec.column_count
        row[0] = flag
        row[1] = "1"
        row[3] = "2026/01/31"
        row[4] = "架空借方科目"
        row[5] = sub_account
        row[6] = department
        row[7] = tax_category
        row[8] = str(debit)
        row[9] = "0"
        row[10] = "架空貸方科目"
        row[11] = ""
        row[12] = department
        row[13] = tax_category
        row[14] = str(credit)
        row[15] = "0"
        row[16] = description
        return tuple(row)

    def _csv_text(
        self,
        rows: list[tuple[str, ...]],
        newline: str = "\n",
    ) -> str:
        handle = StringIO()
        writer = csv.writer(handle, lineterminator=newline)
        writer.writerows(rows)
        return handle.getvalue()


if __name__ == "__main__":
    unittest.main()

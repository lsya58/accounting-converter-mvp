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

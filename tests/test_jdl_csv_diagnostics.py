import unittest

from accounting_converter.diagnostics.jdl_csv import (
    AccountingSide,
    CsvLineClassification,
    DiagnosticAssociationStatus,
    DiagnosticIssueCategory,
    FieldResolutionStatus,
    JdlCsvDiagnosticReportGenerator,
    JdlCsvFingerprintComparator,
    JdlMasterType,
    JdlCsvStructuralAnalyzer,
)


class JdlCsvDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = JdlCsvStructuralAnalyzer()

    def test_valid_csv_syntax(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,借方補助,金額\n2026/08/21,補助A,100\n",
            file_name="valid.csv",
            encoding="cp932",
        )

        self.assertEqual(result.header_columns, ("日付", "借方補助", "金額"))
        self.assertEqual(result.data_line_count, 1)
        self.assertEqual(result.analysis_errors, ())

    def test_quoted_comma_is_kept_as_one_field(self) -> None:
        result = self.analyzer.analyze_text(
            '日付,摘要,金額\n2026/08/21,"カンマ,を含む摘要",100\n'
        )

        self.assertEqual(result.line_observations[1].column_count, 3)
        self.assertEqual(result.line_observations[1].columns[1], "カンマ,を含む摘要")
        self.assertEqual(result.analysis_errors, ())

    def test_empty_field_is_reported_but_not_removed(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,借方補助,金額\n2026/08/21,,100\n"
        )

        self.assertEqual(result.line_observations[1].columns, ("2026/08/21", "", "100"))
        self.assertTrue(
            any(
                warning.rule_id == "JDLCSV-EMPTY-FIELD"
                for warning in result.analysis_warnings
            )
        )

    def test_column_count_mismatch(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,借方補助,金額\n2026/08/21,補助A\n",
            file_name="mismatch.csv",
        )

        self.assertTrue(
            any(error.rule_id == "JDLCSV-COLUMN-COUNT" for error in result.analysis_errors)
        )
        self.assertEqual(result.line_observations[1].column_count, 2)

    def test_unbalanced_quote(self) -> None:
        result = self.analyzer.analyze_text(
            '日付,摘要,金額\n2026/08/21,"未終了,100\n',
            file_name="quote.csv",
        )

        self.assertEqual(
            result.line_observations[1].classification,
            CsvLineClassification.INVALID_CSV,
        )
        self.assertTrue(
            any(error.rule_id == "JDLCSV-CSV-SYNTAX" for error in result.analysis_errors)
        )

    def test_slash_metadata_line(self) -> None:
        result = self.analyzer.analyze_text(
            "// JDL export metadata\n日付,借方補助,金額\n2026/08/21,補助A,100\n"
        )

        self.assertEqual(
            result.line_observations[0].classification,
            CsvLineClassification.METADATA,
        )
        self.assertEqual(result.metadata_line_count, 1)

    def test_slash_diagnostic_message_line(self) -> None:
        result = self.analyzer.analyze_text(
            "// 【借方補助】に一致する補助が見つかりません\n日付,借方補助,金額\n"
        )

        self.assertEqual(
            result.line_observations[0].classification,
            CsvLineClassification.DIAGNOSTIC_MESSAGE,
        )
        self.assertTrue(
            any(warning.rule_id == "JDLCSV-DIAGNOSTIC-MESSAGE" for warning in result.analysis_warnings)
        )

    def test_sub_account_master_reference_message(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,借方補助,金額\n【借方補助】に一致する補助が見つかりません\n"
        )

        message_line = result.diagnostic_message_lines[0]
        self.assertIsNotNone(message_line.master_reference_issue)
        self.assertEqual(
            message_line.master_reference_issue.field,
            "debit_sub_account",
        )
        self.assertTrue(
            any(warning.rule_id == "JDLCSV-MASTER-REFERENCE" for warning in result.analysis_warnings)
        )

    def test_debit_sub_account_mismatch_is_structured(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "売掛金,PayPay,100\n"
            "【借方補助】に一致する補助が見つかりません\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.category, DiagnosticIssueCategory.MASTER_MISMATCH)
        self.assertEqual(issue.side, AccountingSide.DEBIT)
        self.assertEqual(issue.master_type, JdlMasterType.SUB_ACCOUNT)
        self.assertIsNone(issue.source_value)
        self.assertEqual(issue.related_record_row, 2)
        self.assertIsNone(issue.account_value)
        self.assertEqual(
            issue.association_status,
            DiagnosticAssociationStatus.LINKED_TO_PREVIOUS_RECORD,
        )
        self.assertEqual(
            issue.field_resolution_status,
            FieldResolutionStatus.FIELD_UNRESOLVED,
        )

    def test_credit_sub_account_mismatch_is_structured(self) -> None:
        result = self.analyzer.analyze_text(
            "貸方勘定科目,貸方補助,金額\n"
            "売掛金,auPay,100\n"
            "【貸方補助】に一致する補助が見つかりません\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.side, AccountingSide.CREDIT)
        self.assertEqual(issue.master_type, JdlMasterType.SUB_ACCOUNT)
        self.assertIsNone(issue.source_value)
        self.assertIsNone(issue.account_value)

    def test_account_mismatch_is_structured(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "仮科目,PayPay,100\n"
            "【借方勘定科目】に一致する勘定科目が見つかりません\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.side, AccountingSide.DEBIT)
        self.assertEqual(issue.master_type, JdlMasterType.ACCOUNT)
        self.assertIsNone(issue.source_value)

    def test_department_mismatch_is_structured(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方部門,金額\n"
            "売掛金,営業部,100\n"
            "【借方部門】に一致する部門が見つかりません\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.side, AccountingSide.DEBIT)
        self.assertEqual(issue.master_type, JdlMasterType.DEPARTMENT)
        self.assertIsNone(issue.source_value)

    def test_repeated_mismatch_values_are_summarized(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "売掛金,PayPay,100\n"
            "【借方補助】に一致する補助が見つかりません\n"
            "売掛金,PayPay,200\n"
            "【借方補助】に一致する補助が見つかりません\n"
            "売掛金,auPay,300\n"
            "【借方補助】に一致する補助が見つかりません\n"
        )

        summary = result.master_mismatch_summary
        self.assertEqual(summary.total_count, 3)
        self.assertIsNone(summary.items[0].source_value)
        self.assertEqual(summary.items[0].count, 3)
        self.assertEqual(summary.items[0].first_row, 3)
        self.assertIsNone(summary.items[0].account_value)

    def test_unknown_jdl_message_is_kept_as_unknown_issue(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,金額\n"
            "2026/08/21,100\n"
            "項目その他に相違があるため取り込むことができません。\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.category, DiagnosticIssueCategory.UNKNOWN_JDL_MESSAGE)
        self.assertEqual(issue.master_type, JdlMasterType.UNKNOWN)
        self.assertIsNone(issue.source_value)

    def test_unresolved_when_no_related_record(self) -> None:
        result = self.analyzer.analyze_text(
            "【借方補助】に一致する補助が見つかりません\n"
            "借方勘定科目,借方補助,金額\n"
        )

        issue = result.diagnostic_issues[0]
        self.assertIsNone(issue.source_value)
        self.assertIsNone(issue.related_record_row)
        self.assertEqual(
            issue.association_status,
            DiagnosticAssociationStatus.UNRESOLVED,
        )

    def test_message_embedded_value_can_be_mapping_candidate_but_not_auto_corrected(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "売掛金,PayPay,100\n"
            "【借方補助】PayPayに一致する補助が見つかりません\n"
        )

        candidate = result.master_mismatch_summary.mapping_candidates[0]
        self.assertEqual(candidate.source_value, "PayPay")
        self.assertEqual(candidate.mapping_value.source_value, "PayPay")
        self.assertIsNone(candidate.mapping_value.target_value)
        self.assertFalse(candidate.mapping_value.is_resolved)
        self.assertEqual(
            result.diagnostic_issues[0].field_resolution_status,
            FieldResolutionStatus.FROM_MESSAGE,
        )

    def test_record_columns_do_not_create_mapping_candidate_without_profile(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "売掛金,PayPay,100\n"
            "【借方補助】に一致する補助が見つかりません\n"
        )

        self.assertEqual(result.master_mismatch_summary.mapping_candidates, ())

    def test_unknown_line_is_kept(self) -> None:
        result = self.analyzer.analyze_text("日付,借方補助,金額\nこれは不明な行\n")

        self.assertEqual(
            result.line_observations[1].classification,
            CsvLineClassification.UNKNOWN,
        )
        self.assertEqual(len(result.line_observations), 2)
        self.assertTrue(
            any(warning.rule_id == "JDLCSV-UNKNOWN-LINE" for warning in result.analysis_warnings)
        )

    def test_schema_fingerprint_generation(self) -> None:
        result = self.analyzer.analyze_text(
            "// metadata\n日付,借方補助,金額\n2026/08/21,補助A,100\n",
            encoding="cp932",
            has_bom=False,
        )

        fingerprint = result.schema_fingerprint
        self.assertIsNotNone(fingerprint)
        self.assertEqual(fingerprint.encoding, "cp932")
        self.assertEqual(fingerprint.header_names, ("日付", "借方補助", "金額"))
        self.assertEqual(fingerprint.record_column_counts, ((3, 1),))
        self.assertIn("metadata_present", fingerprint.metadata_pattern)

    def test_compare_two_fingerprints(self) -> None:
        baseline = self.analyzer.analyze_text(
            "日付,借方補助,金額\n2026/08/21,補助A,100\n",
            encoding="cp932",
        ).schema_fingerprint
        target = self.analyzer.analyze_text(
            "日付,金額,借方補助\n2026/08/21,100,補助A\n",
            encoding="utf-8",
        ).schema_fingerprint

        comparison = JdlCsvFingerprintComparator().compare(baseline, target)

        self.assertTrue(comparison.has_differences)
        self.assertTrue(
            any(diff.rule_id == "JDLCSV-CMP-ENCODING" for diff in comparison.differences)
        )
        self.assertTrue(
            any(diff.rule_id == "JDLCSV-CMP-HEADER" for diff in comparison.differences)
        )

    def test_errors_do_not_silently_delete_rows(self) -> None:
        text = (
            "// metadata\n"
            "日付,借方補助,金額\n"
            "2026/08/21,補助A,100\n"
            "2026/08/22,補助B\n"
            "意味不明\n"
            "【借方補助】に一致する補助が見つかりません\n"
        )
        result = self.analyzer.analyze_text(text)

        self.assertEqual(result.total_physical_lines, 6)
        self.assertEqual(len(result.line_observations), 6)
        self.assertTrue(result.analysis_errors)
        self.assertEqual(result.data_line_count, 2)

    def test_diagnostic_report(self) -> None:
        result = self.analyzer.analyze_text(
            "日付,借方補助,金額\n2026/08/21,補助A\n",
            file_name="failed.csv",
            encoding="CP932",
        )

        report = JdlCsvDiagnosticReportGenerator().generate_text(result)

        self.assertIn("JDL CSV 診断結果", report)
        self.assertIn("failed.csv", report)
        self.assertIn("JDL取込可能とは判定できません。", report)

    def test_import_diagnostic_report_includes_master_mismatch_summary(self) -> None:
        result = self.analyzer.analyze_text(
            "借方勘定科目,借方補助,金額\n"
            "売掛金,PayPay,100\n"
            "【借方補助】に一致する補助が見つかりません\n"
            "売掛金,auPay,200\n"
            "【借方補助】に一致する補助が見つかりません\n"
        )

        report = JdlCsvDiagnosticReportGenerator().generate_text(result)

        self.assertIn("JDL取込診断", report)
        self.assertIn("借方補助: 2件", report)
        self.assertIn("(値未特定): 2件", report)
        self.assertIn("JDL自体の障害を断定するものではありません。", report)


if __name__ == "__main__":
    unittest.main()

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
    ObservedJournalGroupStatus,
    ObservedJdlSchema,
    analysis_to_dict,
)
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    jdl_ibex_cashbook_35_5_observed_schema,
)


class JdlCsvDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = JdlCsvStructuralAnalyzer()

    def observed_jdl_ibex_schema(self) -> ObservedJdlSchema:
        return jdl_ibex_cashbook_35_5_observed_schema()

    def record30(
        self,
        identifier: str = "1000",
        debit_code: str = "",
        debit_account: str = "売掛金",
        debit_sub: str = "",
        credit_code: str = "",
        credit_account: str = "現金",
        credit_sub: str = "",
        amount: str = "100",
        voucher: str = "0",
        date: str = "20260821",
        debit_amount: str | None = None,
        credit_amount: str | None = None,
    ) -> str:
        columns = [""] * 30
        columns[0] = identifier
        columns[1] = voucher
        columns[2] = date
        columns[3] = debit_code
        columns[4] = debit_account
        columns[6] = "1" if debit_sub else ""
        columns[7] = debit_sub
        columns[11] = debit_amount if debit_amount is not None else amount
        columns[13] = credit_code
        columns[14] = credit_account
        columns[16] = "1" if credit_sub else ""
        columns[17] = credit_sub
        columns[21] = credit_amount if credit_amount is not None else amount
        columns[23] = "架空摘要"
        return ",".join(columns)

    def padded_diagnostic30(self, label: str, tail: tuple[str, ...] = ()) -> str:
        columns = [f"// [{label}]に一致する補助が見つかりません"] + [""] * 29
        for index, value in enumerate(tail, start=1):
            columns[index] = value
        return ",".join(columns)

    def observed_analyzer(self) -> JdlCsvStructuralAnalyzer:
        return JdlCsvStructuralAnalyzer(observed_schema=self.observed_jdl_ibex_schema())

    def analyze_observed_records(self, records: list[str]):
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        return self.observed_analyzer().analyze_text("\r\n".join([header] + records))

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

    def test_padded_30_column_diagnostic_message_is_detected_by_first_cell(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join(
            [
                header,
                self.record30(debit_sub="PayPay"),
                self.padded_diagnostic30("借方補助"),
            ]
        )

        result = self.observed_analyzer().analyze_text(
            text,
            encoding="cp932",
            has_bom=False,
        )

        self.assertEqual(result.data_line_count, 1)
        self.assertEqual(len(result.diagnostic_message_lines), 1)
        self.assertEqual(result.diagnostic_message_lines[0].column_count, 30)
        self.assertEqual(
            result.diagnostic_issues[0].field_resolution_status,
            FieldResolutionStatus.FROM_OBSERVED_SCHEMA,
        )
        self.assertEqual(result.diagnostic_issues[0].source_value, "PayPay")

    def test_slash_identifier_flag_observed_header_is_header_not_metadata(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join([header, self.record30(debit_sub="PayPay")])

        result = self.observed_analyzer().analyze_text(text)

        self.assertEqual(result.header_row_number, 1)
        self.assertEqual(
            result.line_observations[0].classification,
            CsvLineClassification.HEADER,
        )
        self.assertEqual(result.metadata_line_count, 0)
        self.assertEqual(result.data_record_count, 1)
        self.assertEqual(
            result.line_observations[1].classification,
            CsvLineClassification.JOURNAL_RECORD,
        )

    def test_identifier_flags_are_counted_but_meaning_is_not_confirmed(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        records = [
            self.record30(identifier="1000"),
            self.record30(identifier="1100"),
            self.record30(identifier="1110"),
            self.record30(identifier="1101"),
            self.record30(identifier="1111"),
        ]

        result = self.observed_analyzer().analyze_text("\r\n".join([header] + records))

        self.assertEqual(
            dict(result.identifier_flag_counts),
            {"1000": 1, "1100": 1, "1110": 1, "1101": 1, "1111": 1},
        )
        self.assertEqual(
            result.observed_schema.identifier_flag_meaning_status.value,
            "OBSERVED_ONLY",
        )
        self.assertFalse(result.observed_schema.is_formal_format_profile)

    def test_one_column_diagnostic_message_is_detected(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join(
            [
                header,
                self.record30(debit_sub="PayPay"),
                "// [借方補助]に一致する補助が見つかりません",
            ]
        )

        result = self.observed_analyzer().analyze_text(text, encoding="cp932")

        self.assertEqual(result.data_line_count, 1)
        self.assertEqual(result.diagnostic_message_lines[0].column_count, 1)
        self.assertEqual(
            result.diagnostic_issues[0].association_status,
            DiagnosticAssociationStatus.LINKED_TO_PREVIOUS_RECORD,
        )

    def test_padded_diagnostic_with_nonempty_tail_warns(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join(
            [
                header,
                self.record30(debit_sub="PayPay"),
                self.padded_diagnostic30("借方補助", tail=("unexpected",)),
            ]
        )

        result = self.observed_analyzer().analyze_text(text)

        self.assertTrue(
            any(
                warning.rule_id == "JDLCSV-DIAGNOSTIC-NONEMPTY-TAIL"
                for warning in result.analysis_warnings
            )
        )
        self.assertEqual(len(result.line_observations), 3)

    def test_diagnostic_links_to_previous_journal_record_as_observed_behavior(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join(
            [
                header,
                self.record30(debit_sub="クレジット"),
                "// [借方補助]に一致する補助が見つかりません",
            ]
        )

        result = self.observed_analyzer().analyze_text(text)

        issue = result.diagnostic_issues[0]
        self.assertEqual(issue.related_record_row, 2)
        self.assertEqual(issue.source_value, "クレジット")
        self.assertIn(
            "diagnostic_message_follows_journal_record",
            result.observed_schema.observed_behavior,
        )

    def test_1271_journal_count_is_tracked(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        records = [self.record30(amount=str(index)) for index in range(1271)]
        text = "\r\n".join([header] + records)

        result = self.observed_analyzer().analyze_text(
            text,
            encoding="cp932",
            has_bom=False,
        )

        self.assertEqual(result.data_line_count, 1271)
        self.assertEqual(result.schema_fingerprint.record_column_counts, ((30, 1271),))
        self.assertEqual(result.observed_schema.journal_count, 1271)
        self.assertEqual(result.observed_schema.journal_column_count, 30)
        self.assertEqual(result.observed_schema.encoding, "cp932")
        self.assertFalse(result.observed_schema.has_bom)
        self.assertEqual(result.observed_schema.line_ending, "CRLF")

    def test_observed_sub_account_mismatch_summary(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        rows = [
            header,
            self.record30(debit_sub="クレジット"),
            "// [借方補助]に一致する補助が見つかりません",
            self.record30(debit_sub="クレジット"),
            "// [借方補助]に一致する補助が見つかりません",
            self.record30(credit_sub="PayPay"),
            "// [貸方補助]に一致する補助が見つかりません",
        ]

        result = self.observed_analyzer().analyze_text("\r\n".join(rows))
        report = JdlCsvDiagnosticReportGenerator().generate_text(result)

        self.assertEqual(result.master_mismatch_summary.total_count, 3)
        self.assertIn(("SUB_ACCOUNT", 3), result.master_mismatch_summary.counts_by_master_type)
        self.assertTrue(
            any(
                item.account_value == "売掛金"
                and item.source_value == "クレジット"
                and item.count == 2
                and item.side is AccountingSide.DEBIT
                for item in result.master_mismatch_summary.items
            )
        )
        self.assertIn("補助科目不一致: 3件", report)
        self.assertIn("売掛金:", report)
        self.assertIn("クレジット: 2件 (借方)", report)
        self.assertIn("PayPay: 1件 (貸方)", report)

    def test_observed_account_mismatch_summary(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        rows = [
            header,
            self.record30(debit_code="863", debit_account="顧問料"),
            "// [借方科目]に一致する科目が見つかりません",
            self.record30(debit_code="863", debit_account="顧問料"),
            "// [借方科目]に一致する科目が見つかりません",
            self.record30(credit_code="185", credit_account="未収入金"),
            "// [貸方科目]に一致する科目が見つかりません",
        ]

        result = self.observed_analyzer().analyze_text("\r\n".join(rows))
        report = JdlCsvDiagnosticReportGenerator().generate_text(result)

        self.assertIn(("ACCOUNT", 3), result.master_mismatch_summary.counts_by_master_type)
        self.assertTrue(
            any(
                item.source_value == "863 顧問料"
                and item.count == 2
                and item.side is AccountingSide.DEBIT
                for item in result.master_mismatch_summary.items
            )
        )
        self.assertTrue(
            any(
                item.source_value == "185 未収入金"
                and item.count == 1
                and item.side is AccountingSide.CREDIT
                for item in result.master_mismatch_summary.items
            )
        )
        self.assertIn("科目不一致: 3件", report)
        self.assertIn("863 顧問料: 2件 (借方)", report)
        self.assertIn("185 未収入金: 1件 (貸方)", report)

    def test_all_nonempty_sub_accounts_become_mismatches_in_observed_case(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        rows = [header]
        nonempty_subs = ("クレジット", "PayPay", "リクルート", "auPay①")
        for sub_account in nonempty_subs:
            rows.append(self.record30(debit_sub=sub_account))
            rows.append("// [借方補助]に一致する補助が見つかりません")

        result = self.observed_analyzer().analyze_text("\r\n".join(rows))

        nonempty_count = sum(1 for line in result.journal_record_lines if line.columns[7])
        self.assertEqual(nonempty_count, 4)
        self.assertEqual(result.master_mismatch_summary.total_count, nonempty_count)

    def test_observed_schema_is_not_formal_format_profile(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        result = self.observed_analyzer().analyze_text(
            "\r\n".join([header, self.record30()]),
            encoding="cp932",
            has_bom=False,
        )

        self.assertIsNotNone(result.observed_schema)
        self.assertEqual(result.observed_schema.product, "JDL IBEX 出納帳")
        self.assertEqual(result.observed_schema.observed_version, "35.5")
        self.assertFalse(result.observed_schema.is_formal_format_profile)

    def test_diagnostic_rows_are_not_counted_as_journals_and_not_silently_deleted(self) -> None:
        header = ",".join(self.observed_jdl_ibex_schema().observed_header)
        text = "\r\n".join(
            [
                header,
                self.record30(debit_sub="PayPay"),
                self.padded_diagnostic30("借方補助"),
                self.record30(debit_sub="auPay①"),
                "// [借方補助]に一致する補助が見つかりません",
            ]
        )

        result = self.observed_analyzer().analyze_text(text)

        self.assertEqual(result.data_line_count, 2)
        self.assertEqual(len(result.diagnostic_message_lines), 2)
        self.assertEqual(len(result.line_observations), 5)

    def test_observed_grouping_1000_single_candidate(self) -> None:
        result = self.analyze_observed_records([self.record30(identifier="1000")])

        grouping = result.observed_grouping_summary
        self.assertEqual(grouping.total_candidate_count, 1)
        self.assertEqual(grouping.single_record_candidate_count, 1)
        candidate = grouping.candidates[0]
        self.assertEqual(
            candidate.status,
            ObservedJournalGroupStatus.OBSERVED_SINGLE_RECORD,
        )
        self.assertEqual(candidate.identifier_flags, ("1000",))
        self.assertTrue(candidate.balanced)
        self.assertIn("observed_identifier_flag:1000", candidate.grouping_basis)

    def test_observed_grouping_1110_to_1101_candidate(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="10", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1101", voucher="10", debit_amount="0", credit_amount="100"),
            ]
        )

        grouping = result.observed_grouping_summary
        self.assertEqual(grouping.total_candidate_count, 1)
        self.assertEqual(grouping.multi_record_candidate_count, 1)
        self.assertEqual(grouping.valid_multi_record_sequence_count, 1)
        self.assertEqual(grouping.same_voucher_number_count, 1)
        self.assertEqual(grouping.same_date_count, 1)
        self.assertEqual(grouping.balanced_multi_record_candidate_count, 1)
        self.assertEqual(
            grouping.candidates[0].status,
            ObservedJournalGroupStatus.OBSERVED_MULTI_RECORD_SEQUENCE,
        )

    def test_observed_grouping_1110_1100_1101_candidate(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="11", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1100", voucher="11", debit_amount="50", credit_amount="0"),
                self.record30(identifier="1101", voucher="11", debit_amount="0", credit_amount="150"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.record_count, 3)
        self.assertEqual(candidate.identifier_flags, ("1110", "1100", "1101"))
        self.assertEqual(candidate.debit_total, candidate.credit_total)

    def test_observed_grouping_allows_multiple_1100_records(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="12", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1100", voucher="12", debit_amount="25", credit_amount="0"),
                self.record30(identifier="1100", voucher="12", debit_amount="25", credit_amount="0"),
                self.record30(identifier="1101", voucher="12", debit_amount="0", credit_amount="150"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.record_count, 4)
        self.assertEqual(
            candidate.status,
            ObservedJournalGroupStatus.OBSERVED_MULTI_RECORD_SEQUENCE,
        )

    def test_observed_grouping_missing_1101_is_unresolved(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="13", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1100", voucher="13", debit_amount="0", credit_amount="100"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.status, ObservedJournalGroupStatus.UNRESOLVED)
        self.assertFalse(candidate.valid_sequence)
        self.assertIn("invalid_observed_identifier_sequence", candidate.warnings)

    def test_observed_grouping_unexpected_flag_inside_sequence_is_unresolved(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="14", debit_amount="100", credit_amount="0"),
                self.record30(identifier="9999", voucher="14", debit_amount="0", credit_amount="0"),
                self.record30(identifier="1101", voucher="14", debit_amount="0", credit_amount="100"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.identifier_flags, ("1110", "9999", "1101"))
        self.assertEqual(candidate.status, ObservedJournalGroupStatus.UNRESOLVED)
        self.assertFalse(candidate.valid_sequence)

    def test_observed_grouping_voucher_mismatch_is_unresolved(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="15", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1101", voucher="16", debit_amount="0", credit_amount="100"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.status, ObservedJournalGroupStatus.UNRESOLVED)
        self.assertFalse(candidate.same_voucher_number)
        self.assertIn("voucher_number_not_consistent", candidate.warnings)

    def test_observed_grouping_date_mismatch_is_unresolved(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="17", date="20260821", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1101", voucher="17", date="20260822", debit_amount="0", credit_amount="100"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.status, ObservedJournalGroupStatus.UNRESOLVED)
        self.assertFalse(candidate.same_date)
        self.assertIn("date_not_consistent", candidate.warnings)

    def test_observed_grouping_unbalanced_candidate_is_unresolved(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1110", voucher="18", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1101", voucher="18", debit_amount="0", credit_amount="99"),
            ]
        )

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(candidate.status, ObservedJournalGroupStatus.UNRESOLVED)
        self.assertFalse(candidate.balanced)
        self.assertIn("debit_credit_not_balanced", candidate.warnings)

    def test_observed_grouping_1111_single_candidate(self) -> None:
        result = self.analyze_observed_records([self.record30(identifier="1111")])

        candidate = result.observed_grouping_summary.candidates[0]
        self.assertEqual(
            candidate.status,
            ObservedJournalGroupStatus.OBSERVED_SINGLE_RECORD,
        )
        self.assertEqual(candidate.identifier_flags, ("1111",))
        self.assertIn("observed_identifier_flag:1111", candidate.grouping_basis)

    def test_observed_grouping_candidate_count(self) -> None:
        result = self.analyze_observed_records(
            [
                self.record30(identifier="1000"),
                self.record30(identifier="1110", voucher="19", debit_amount="100", credit_amount="0"),
                self.record30(identifier="1100", voucher="19", debit_amount="20", credit_amount="0"),
                self.record30(identifier="1101", voucher="19", debit_amount="0", credit_amount="120"),
                self.record30(identifier="1111"),
            ]
        )

        grouping = result.observed_grouping_summary
        self.assertEqual(result.data_record_count, 5)
        self.assertEqual(grouping.total_candidate_count, 3)
        self.assertEqual(grouping.single_record_candidate_count, 2)
        self.assertEqual(grouping.multi_record_candidate_count, 1)

    def test_observed_grouping_is_not_promoted_to_formal_journal_entry(self) -> None:
        result = self.analyze_observed_records([self.record30(identifier="1000")])

        self.assertIsNone(getattr(result, "journal_entries", None))
        self.assertIsNotNone(result.observed_grouping_summary)
        self.assertIsNone(analysis_to_dict(result)["journal_count"])
        self.assertFalse(result.observed_schema.is_formal_format_profile)


if __name__ == "__main__":
    unittest.main()

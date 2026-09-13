from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.application.conversion_preparation import (
    ConversionPreparationService,
    ConversionReadinessStatus,
)
from accounting_converter.diagnostics.jdl_accounting_journal_list import (
    JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER,
    JdlAccountingJournalListAnalyzer,
    JdlAccountingJournalListComparison,
    JdlAccountingJournalListReadiness,
    JdlAccountingPostImportVerifier,
    PostImportVerificationStatus,
    analysis_to_privacy_safe_dict,
    verification_to_privacy_safe_dict,
)
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
)
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    yayoi_ae19_direct_export_observed_schema,
)


class JdlAccountingJournalListTests(unittest.TestCase):
    def test_21_column_structural_detection(self) -> None:
        result = self.analyze(self.csv_text())

        self.assertEqual(result.encoding, "cp932")
        self.assertFalse(result.has_bom)
        self.assertEqual(result.line_ending, "CRLF")
        self.assertEqual(result.header_row_number, 3)
        self.assertEqual(result.header_column_count, 21)
        self.assertEqual(result.data_row_count, 1)
        self.assertEqual(result.data_row_column_count_distribution, ((21, 1),))
        self.assertEqual(result.comparison_to_cashbook_30_column, JdlAccountingJournalListComparison.DIFFERENT_STRUCTURE)

    def test_preamble_and_header_detection(self) -> None:
        result = self.analyze(self.csv_text(preamble=("JDL accounting export", "")))

        self.assertEqual(result.preamble_line_count, 2)
        self.assertEqual(result.header_columns, JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER)

    def test_wrong_column_count_is_reported_without_dropping_row_silently(self) -> None:
        text = self.csv_text(extra_lines=[["footer", "2"]])

        result = self.analyze(text)

        self.assertEqual(result.data_row_count, 1)
        self.assertEqual(result.malformed_row_numbers, (5,))
        self.assertTrue(
            any(warning.rule_id == "JDL-ACCOUNTING-LIST-ROW-WIDTH" for warning in result.warnings)
        )

    def test_malformed_csv_is_error(self) -> None:
        result = JdlAccountingJournalListAnalyzer().analyze_text(
            ",".join(JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER)
            + '\r\n1,9001,2026/09/13,"unterminated',
            encoding="cp932",
            line_ending="CRLF",
        )

        self.assertTrue(
            any(error.rule_id == "JDL-ACCOUNTING-LIST-MALFORMED-CSV" for error in result.errors)
        )
        self.assertEqual(result.readiness, JdlAccountingJournalListReadiness.PARSE_FAILED)

    def test_privacy_safe_serialization_omits_accounting_values(self) -> None:
        result = self.analyze(self.csv_text())

        serialized = json.dumps(
            analysis_to_privacy_safe_dict(result, include_file_name=True),
            ensure_ascii=False,
        )

        self.assertNotIn("架空現金", serialized)
        self.assertNotIn("架空普通預金", serialized)
        self.assertNotIn("架空摘要", serialized)
        self.assertNotIn("2026/09/13", serialized)
        self.assertNotIn("1000", serialized)

    def test_read_only_record_candidate_parse_but_not_common_journal(self) -> None:
        result = self.analyze(self.csv_text())

        self.assertEqual(len(result.record_candidates), 1)
        self.assertFalse(result.can_build_common_journal_entries)
        self.assertEqual(
            result.readiness,
            JdlAccountingJournalListReadiness.INSUFFICIENT_EVIDENCE_FOR_COMMON_JOURNAL,
        )

    def test_expected_actual_verification_match(self) -> None:
        analysis = self.analyze(self.csv_text())

        result = JdlAccountingPostImportVerifier().verify((self.entry(),), analysis)

        self.assertEqual(result.status, PostImportVerificationStatus.MATCH)
        self.assertTrue(result.success)
        self.assertEqual(result.matched_count, 1)

    def test_expected_actual_count_mismatch(self) -> None:
        analysis = self.analyze(self.csv_text())

        result = JdlAccountingPostImportVerifier().verify((self.entry(), self.entry("9002")), analysis)

        self.assertEqual(result.status, PostImportVerificationStatus.MISMATCH)
        self.assertIn(("count_mismatch", 1), result.mismatch_categories)

    def test_expected_actual_amount_mismatch(self) -> None:
        analysis = self.analyze(self.csv_text(amount="999"))

        result = JdlAccountingPostImportVerifier().verify((self.entry(),), analysis)

        self.assertEqual(result.status, PostImportVerificationStatus.MISMATCH)
        self.assertIn(("value_mismatch", 1), result.mismatch_categories)

    def test_ambiguous_match_is_reported(self) -> None:
        text = self.csv_text(rows=[self.row(), self.row()])
        analysis = self.analyze(text)

        result = JdlAccountingPostImportVerifier().verify((self.entry(), self.entry()), analysis)

        self.assertEqual(result.status, PostImportVerificationStatus.AMBIGUOUS)
        self.assertIn(("ambiguous_match", 1), result.mismatch_categories)

    def test_parse_failure_blocks_verification(self) -> None:
        analysis = self.analyze(self.csv_text(date_value="not-a-date"))

        result = JdlAccountingPostImportVerifier().verify((self.entry(),), analysis)

        self.assertEqual(result.status, PostImportVerificationStatus.PARSE_FAILED)

    def test_verification_privacy_safe_serialization(self) -> None:
        analysis = self.analyze(self.csv_text(amount="999"))
        result = JdlAccountingPostImportVerifier().verify((self.entry(),), analysis)

        serialized = json.dumps(verification_to_privacy_safe_dict(result), ensure_ascii=False)

        self.assertIn("value_mismatch", serialized)
        self.assertNotIn("架空現金", serialized)
        self.assertNotIn("架空摘要", serialized)
        self.assertNotIn("2026/09/13", serialized)
        self.assertNotIn("1000", serialized)

    def test_30_column_jdl_cashbook_schema_is_not_confused(self) -> None:
        header30 = jdl_ibex_cashbook_35_5_observed_schema_definition()

        result = self.analyze(self.csv_text())

        self.assertEqual(header30.column_count, 30)
        self.assertEqual(result.header_column_count, 21)
        self.assertEqual(result.comparison_to_cashbook_30_column, JdlAccountingJournalListComparison.DIFFERENT_STRUCTURE)

    def test_production_jdl_output_registry_remains_unavailable(self) -> None:
        registry = production_adapter_registry()
        target = jdl_ibex_cashbook_35_5_observed_schema_definition()

        self.assertEqual(
            registry.get_exact_output(target.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def test_yayoi_to_jdl_readiness_is_not_ready(self) -> None:
        readiness = ConversionPreparationService(
            adapter_registry=production_adapter_registry()
        ).prepare(
            yayoi_ae19_direct_export_observed_schema(),
            jdl_ibex_cashbook_35_5_observed_schema_definition(),
            journal_entries=(),
            saved_profile=None,
        )

        self.assertNotEqual(readiness.status, ConversionReadinessStatus.READY)
        self.assertEqual(
            readiness.adapter_availability.output_status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def analyze(self, text: str):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as handle:
            path = Path(handle.name)
            handle.write(text.encode("cp932"))
        try:
            return JdlAccountingJournalListAnalyzer().analyze_path(path)
        finally:
            path.unlink(missing_ok=True)

    def csv_text(
        self,
        rows: list[list[str]] | None = None,
        preamble: tuple[str, ...] = ("JDL accounting export", "period"),
        extra_lines: list[list[str]] | None = None,
        amount: str = "1000",
        date_value: str = "2026/09/13",
    ) -> str:
        body = [list(JDL_ACCOUNTING_JOURNAL_LIST_OBSERVED_HEADER)]
        if rows is None:
            rows = [self.row(amount=amount, date_value=date_value)]
        body.extend(rows)
        if extra_lines:
            body.extend(extra_lines)
        rendered = []
        for line in preamble:
            rendered.append(line)
        for row in body:
            rendered.append(self.render_row(row))
        return "\r\n".join(rendered) + "\r\n"

    def row(
        self,
        voucher: str = "9001",
        amount: str = "1000",
        date_value: str = "2026/09/13",
    ) -> list[str]:
        return [
            "1",
            voucher,
            date_value,
            "架空現金",
            "",
            "",
            "",
            "架空普通預金",
            "",
            "",
            "",
            amount,
            "架空摘要",
            "対象外",
            "",
            "対象外",
            "",
            "",
            "",
            "",
            "",
        ]

    def render_row(self, row: list[str]) -> str:
        with tempfile.TemporaryFile("w+", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="")
            writer.writerow(row)
            handle.seek(0)
            return handle.read()

    def entry(self, voucher: str = "9001") -> JournalEntry:
        source = SourceReference(
            file_name="expected",
            row_number=1,
            source_journal_id=voucher,
        )
        return JournalEntry(
            id=voucher,
            source_reference=source,
            date=date(2026, 9, 13),
            description="架空摘要",
            lines=[
                JournalLine(
                    side=Side.DEBIT,
                    account="架空現金",
                    amount=Decimal("1000"),
                    source_reference=source,
                ),
                JournalLine(
                    side=Side.CREDIT,
                    account="架空普通預金",
                    amount=Decimal("1000"),
                    source_reference=source,
                ),
            ],
        )

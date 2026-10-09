from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)
from accounting_converter.tools.audit_private_csv import (
    AuditStatus,
    PrivateCsvAuditor,
    report_to_dict,
    report_to_text,
    write_json_report,
)
from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER


class PrivateCsvBatchAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = lambda: datetime(2026, 10, 8, tzinfo=timezone.utc)

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = self._auditor().audit_directory(Path(directory))

        self.assertEqual(report.files_scanned, 0)
        self.assertEqual(report.file_pass_rate, 0.0)
        self.assertIsNone(report.recognized_file_pass_rate)

    def test_valid_moneyforward_is_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            raw = self._write_moneyforward(path)
            report = self._auditor().audit_directory(Path(directory))

        result = report.files[0]
        self.assertEqual(result.status, AuditStatus.PASS)
        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.logical_journal_count, 1)
        self.assertEqual(result.sha256, hashlib.sha256(raw).hexdigest())
        self.assertIsNone(result.relative_path)
        self.assertIn(("simple_journals", 1), result.feature_population_counts)
        self.assertIn(("journals_with_tax", 1), result.feature_population_counts)
        self.assertIn(
            ("journals_with_tax_only_blocker", 1),
            result.feature_population_counts,
        )
        self.assertIn(("journals_clear_current", 0), result.feature_population_counts)
        self.assertIn(("journals_clear_after_tax", 1), result.feature_population_counts)
        self.assertEqual(result.journal_shape_counts, (("1D1C", 1),))

    def test_valid_yayoi_is_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            self._write_yayoi(path)
            report = self._auditor().audit_directory(Path(directory))

        result = report.files[0]
        self.assertEqual(result.status, AuditStatus.PASS)
        self.assertEqual(result.format_label, "YAYOI_AE19_OBSERVED")
        self.assertEqual(result.logical_journal_count, 1)

    def test_yayoi_non_crlf_is_known_format_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            spec = yayoi_accounting_05_official_import_spec()
            row = [""] * spec.column_count
            row[0], row[1], row[3] = "2000", "1", "H.31/01/15"
            row[4], row[7], row[8], row[9] = "SYNTHETIC_DEBIT", "対象外", "1000", "0"
            row[10], row[13], row[14], row[15] = "SYNTHETIC_CREDIT", "対象外", "1000", "0"
            self._write_csv(path, [tuple(row)], "cp932", "\n")
            report = self._auditor().audit_directory(Path(directory))

        self.assertEqual(report.files[0].status, AuditStatus.BLOCK)
        self.assertEqual(report.files[0].reason_codes, ("NEWLINE_MISMATCH",))

    def test_known_moneyforward_malformed_is_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            self._write_moneyforward(path, row=self._moneyforward_row()[:-1])
            report = self._auditor().audit_directory(Path(directory))

        result = report.files[0]
        self.assertEqual(result.status, AuditStatus.BLOCK)
        self.assertEqual(result.reason_codes, ("COLUMN_COUNT_MISMATCH",))

    def test_unknown_six_column_csv_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            self._write_csv(path, [("a", "b", "c", "d", "e", "f")], "utf-8", "\n")
            report = self._auditor().audit_directory(Path(directory))

        result = report.files[0]
        self.assertEqual(result.status, AuditStatus.UNKNOWN)
        self.assertEqual(result.column_count_distribution, ((6, 1),))
        self.assertIsNone(result.logical_journal_count)

    def test_mixed_recursive_directory_and_non_csv_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            self._write_moneyforward(root / "a.csv")
            self._write_yayoi(nested / "b.CSV")
            self._write_csv(root / "unknown.csv", [("a",) * 6], "utf-8", "\n")
            (root / "ignored.txt").write_text("ignored", encoding="utf-8")
            report = self._auditor().audit_directory(root, include_relative_paths=True)

        self.assertEqual(report.files_scanned, 3)
        self.assertEqual(report.pass_count, 2)
        self.assertEqual(report.unknown_count, 1)
        self.assertEqual(report.logical_journals_parsed, 2)
        self.assertAlmostEqual(report.file_pass_rate, 200 / 3)
        self.assertEqual(report.recognized_file_pass_rate, 100.0)
        self.assertTrue(any(result.relative_path == "nested/b.CSV" for result in report.files))

    def test_report_does_not_contain_accounting_values(self) -> None:
        secret_values = ("SECRET_ACCOUNT", "SECRET_DESCRIPTION", "SECRET_PARTNER", "987654")
        row = list(self._moneyforward_row())
        row[2], row[5], row[8], row[16] = (
            secret_values[0], secret_values[2], secret_values[3], secret_values[1]
        )
        row[9], row[15] = "SYNTHETIC_CREDIT", secret_values[3]
        with tempfile.TemporaryDirectory() as directory:
            self._write_moneyforward(Path(directory) / "source.csv", row=tuple(row))
            report = self._auditor().audit_directory(Path(directory))
            serialized = json.dumps(report_to_dict(report), ensure_ascii=False)
            text = report_to_text(report)

        for value in secret_values:
            self.assertNotIn(value, serialized)
            self.assertNotIn(value, text)

    def test_raw_exception_message_is_sanitized(self) -> None:
        class ExplodingAdapter:
            def read(self, path, profile):
                raise RuntimeError("SECRET_RAW_ROW")

        with tempfile.TemporaryDirectory() as directory:
            self._write_moneyforward(Path(directory) / "source.csv")
            report = PrivateCsvAuditor(
                moneyforward_adapter=ExplodingAdapter(),
                now=self.now,
            ).audit_directory(Path(directory))

        self.assertEqual(report.error_count, 1)
        serialized = json.dumps(report_to_dict(report))
        self.assertNotIn("SECRET_RAW_ROW", serialized)
        self.assertIn("AUDIT_TECHNICAL_ERROR", serialized)

    def test_json_report_generation_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_moneyforward(root / "source.csv")
            report = self._auditor().audit_directory(root)
            destination = root / "report.json"
            write_json_report(destination, report)
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["pass"], 1)
            with self.assertRaises(FileExistsError):
                write_json_report(destination, report)

    def test_source_files_are_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            before = self._write_moneyforward(path)
            self._auditor().audit_directory(Path(directory))
            after = path.read_bytes()
        self.assertEqual(after, before)

    def test_summary_block_reason_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_moneyforward(root / "bad.csv", row=self._moneyforward_row()[:-1])
            self._write_moneyforward(root / "good.csv")
            report = self._auditor().audit_directory(root)

        self.assertEqual(report.pass_count, 1)
        self.assertEqual(report.block_count, 1)
        self.assertEqual(report.block_reason_counts, (("COLUMN_COUNT_MISMATCH", 1),))

    def _auditor(self) -> PrivateCsvAuditor:
        return PrivateCsvAuditor(now=self.now)

    def _write_moneyforward(
        self,
        path: Path,
        row: tuple[str, ...] | None = None,
    ) -> bytes:
        return self._write_csv(
            path,
            [MONEYFORWARD_OBSERVED_HEADER, row or self._moneyforward_row()],
            "cp932",
            "\n",
        )

    @staticmethod
    def _moneyforward_row() -> tuple[str, ...]:
        return (
            "1", "2026/10/08", "SYNTHETIC_DEBIT", "", "", "", "対象外", "", "1000",
            "SYNTHETIC_CREDIT", "", "", "", "対象外", "", "1000", "SYNTHETIC", "", "",
        )

    def _write_yayoi(self, path: Path) -> bytes:
        spec = yayoi_accounting_05_official_import_spec()
        row = [""] * spec.column_count
        row[0], row[1], row[3] = "2000", "1", "H.31/01/15"
        row[4], row[7], row[8], row[9] = "SYNTHETIC_DEBIT", "対象外", "1000", "0"
        row[10], row[13], row[14], row[15] = "SYNTHETIC_CREDIT", "対象外", "1000", "0"
        return self._write_csv(path, [tuple(row)], "cp932", "\r\n")

    @staticmethod
    def _write_csv(
        path: Path,
        rows: list[tuple[str, ...]],
        encoding: str,
        line_ending: str,
    ) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator=line_ending, quoting=csv.QUOTE_ALL)
        writer.writerows(rows)
        raw = output.getvalue().encode(encoding)
        path.write_bytes(raw)
        return raw


if __name__ == "__main__":
    unittest.main()

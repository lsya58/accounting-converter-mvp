from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_trade_partner_probe import (
    EXPECTED_DESCRIPTION,
    compare_reexport,
    generate,
)


class TradePartnerProbeTests(unittest.TestCase):
    def test_probe_is_formal_self_validated_and_not_for_production(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            paths = generate(private / "probe", private)
            raw = paths["candidate"].read_bytes()
            rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            result = json.loads(paths["result"].read_text(encoding="utf-8"))
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertEqual({len(row) for row in rows}, {30})
        self.assertEqual(rows[1][rows[0].index("摘要")], EXPECTED_DESCRIPTION)
        self.assertEqual(rows[1][rows[0].index("借方科目名称")], "普通預金")
        self.assertEqual(rows[1][rows[0].index("借方補助")], "0001")
        self.assertEqual(rows[1][rows[0].index("借方補助名称")], "テスト銀行")
        self.assertEqual(rows[1][rows[0].index("借方金額")], "1200")
        self.assertEqual(rows[1][rows[0].index("貸方科目名称")], "現金")
        self.assertEqual(rows[1][rows[0].index("貸方金額")], "1200")
        self.assertEqual(rows[1][rows[0].index("借方課区")], "")
        self.assertEqual(rows[1][rows[0].index("貸方課区")], "")
        self.assertTrue(manifest["NOT_FOR_PRODUCTION"])
        self.assertFalse(manifest["production_allowed"])
        self.assertEqual(result["result_status"], "UNTESTED")

    def test_probe_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            output = private / "probe"
            generate(output, private)
            with self.assertRaises(FileExistsError):
                generate(output, private)

    def test_probe_rejects_output_outside_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                generate(root / "outside", root / "private")

    def test_strict_reexport_comparison_updates_privacy_safe_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            output = private / "probe"
            paths = generate(output, private)
            reexport = output / "reexport.csv"
            reexport.write_bytes(paths["candidate"].read_bytes())
            result = compare_reexport(output, reexport)
            stored = json.loads(paths["result"].read_text(encoding="utf-8"))
        self.assertTrue(result["comparison_pass"])
        self.assertEqual(stored["result_status"], "PASS")
        self.assertNotIn("description", stored)

    def test_strict_reexport_accepts_only_observed_jdl_normalizations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            output = private / "probe"
            paths = generate(output, private)
            rows = list(csv.reader(io.StringIO(paths["candidate"].read_text(encoding="cp932"), newline="")))
            header, row = rows
            for name, value in {
                "伝番": "0", "借方科目": "1311", "借方科目正式名称": "普通預金",
                "借方補助": "1", "借方消費税": "0", "貸方科目": "1111",
                "貸方科目正式名称": "現金", "貸方消費税": "0",
                "借方部門コード": "0", "貸方部門コード": "0",
            }.items():
                row[header.index(name)] = value
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerow(["synthetic preamble"])
            writer.writerow([])
            writer.writerow(["synthetic period"])
            writer.writerow(header)
            writer.writerow(row)
            reexport = output / "reexport.csv"
            reexport.write_bytes(stream.getvalue().encode("cp932"))
            result = compare_reexport(output, reexport)
        self.assertTrue(result["comparison_pass"])
        self.assertEqual(result["round_trip_status"], "VERIFIED_BY_REAL_IMPORT")

    def test_strict_reexport_comparison_rejects_semantic_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            output = private / "probe"
            paths = generate(output, private)
            reexport = output / "reexport.csv"
            rows = list(csv.reader(io.StringIO(paths["candidate"].read_text(encoding="cp932"), newline="")))
            rows[1][rows[0].index("摘要")] = "DIFFERENT"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerows(rows)
            reexport.write_bytes(stream.getvalue().encode("cp932"))
            result = compare_reexport(output, reexport)
        self.assertFalse(result["comparison_pass"])
        self.assertGreater(result["mismatched_field_count"], 0)


if __name__ == "__main__":
    unittest.main()

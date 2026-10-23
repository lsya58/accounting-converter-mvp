from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_jdl_migration_tax_probes import (
    CASES,
    ProbeConfig,
    compare,
    compare_in_reexport,
    generate,
    generate_non_taxable_sales,
    _validate_period,
)


class JdlMigrationTaxProbeTests(unittest.TestCase):
    def test_generates_non_taxable_sales_probe_with_blank_tax_category(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, manifest_path, result_path = generate_non_taxable_sales(
                root / "probe", root
            )
            raw = candidate.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(raw.endswith(b"\r\n"))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            text = raw.decode("cp932")
            self.assertIn("非売上,,", text)
            self.assertIn("20260329", text)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["NOT_FOR_PRODUCTION"])
            self.assertFalse(manifest["production_allowed"])
            self.assertEqual(manifest["tax_category"], "")
            self.assertEqual(result["result_status"], "UNTESTED")
            with self.assertRaises(FileExistsError):
                generate_non_taxable_sales(root / "probe", root)

    def test_generates_two_strict_private_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = generate(root / "probes", root)
            self.assertEqual(len(paths), 6)
            for case, date, scope, description in CASES:
                candidate = root / "probes" / f"{case}.csv"
                raw = candidate.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                self.assertIn(b"\r\n", raw)
                rows = raw.decode("cp932").splitlines()
                self.assertEqual(len(rows), 5)
                self.assertIn(
                    f"// 出力期間 ： {date} ～ {date}", rows[1]
                )
                self.assertEqual(len(rows[3].split(",")), 30)
                self.assertIn(date, rows[4])
                self.assertIn(scope, rows[4])
                self.assertIn(description, rows[4])
                manifest = json.loads(
                    (root / "probes" / f"{case}.manifest.json").read_text()
                )
                self.assertTrue(manifest["NOT_FOR_PRODUCTION"])
                self.assertFalse(manifest["production_allowed"])
                self.assertEqual(
                    compare(candidate, candidate)["comparison_pass"], True
                )
                changed = root / "changed.csv"
                changed.write_bytes(raw.replace(scope.encode("cp932"), b"", 1))
                self.assertFalse(compare(candidate, changed)["comparison_pass"])
                changed.unlink()

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate(root / "probes", root)
            with self.assertRaises(FileExistsError):
                generate(root / "probes", root)

    def test_explicit_target_master_and_accounts_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ProbeConfig(
                "101",
                "Synthetic debit",
                "601",
                "Synthetic credit",
                cases=(("target_case", "20261130", "Synthetic tax", "SYNTHETIC"),),
                target_master_sha256="a" * 64,
            )
            generate(root / "probes", root, config)

            candidate = (root / "probes" / "target_case.csv").read_bytes().decode("cp932")
            manifest = json.loads(
                (root / "probes" / "target_case.manifest.json").read_text()
            )
            self.assertIn("101,Synthetic debit", candidate)
            self.assertIn("601,Synthetic credit", candidate)
            self.assertEqual(manifest["target_master_sha256"], "a" * 64)
            self.assertEqual(manifest["journal_date"], "20261130")

    def test_multi_day_period_and_outside_date_validation(self):
        _validate_period(("20260330", "20260331"), "20260330", "20260331")
        with self.assertRaisesRegex(ValueError, "outside"):
            _validate_period(("20260401",), "20260330", "20260331")

    def test_selects_one_probe_strictly_from_mixed_reexport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate(root / "probes", root)
            first = root / "probes" / "sales_second_10.csv"
            second = root / "probes" / "sales_fifth_10.csv"
            first_rows = first.read_bytes().decode("cp932").splitlines()
            second_rows = second.read_bytes().decode("cp932").splitlines()
            mixed = root / "mixed.csv"
            mixed.write_bytes(
                (first_rows[3] + "\r\n" + first_rows[4] + "\r\n" + second_rows[4] + "\r\n").encode("cp932")
            )
            result = compare_in_reexport(first, mixed)
            self.assertTrue(result["comparison_pass"])
            self.assertEqual(result["reexport_total_rows"], 2)

            duplicate = root / "duplicate.csv"
            duplicate.write_bytes(
                (first_rows[3] + "\r\n" + first_rows[4] + "\r\n" + first_rows[4] + "\r\n").encode("cp932")
            )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                compare_in_reexport(first, duplicate)

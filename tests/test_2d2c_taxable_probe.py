from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_probe import (
    compare_reexport,
    generate,
)


class TwoDebitTwoCreditTaxableProbeTests(unittest.TestCase):
    def test_generates_exact_scoped_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            paths = generate(private / "probe", private)
            raw = paths["candidate"].read_bytes()
            rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        header, first, second = rows
        pos = {name: index for index, name in enumerate(header)}
        self.assertEqual([first[0], second[0]], ["1110", "1101"])
        self.assertEqual(first[pos["借方課区"]], "仕　入")
        self.assertEqual(first[pos["借方税区"]], "10%")
        self.assertTrue(first[pos["借方補助"]])
        self.assertTrue(all(not row[pos["借方取引科目"]] for row in (first, second)))
        self.assertFalse(raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertTrue(manifest["NOT_FOR_PRODUCTION"])
        self.assertFalse(manifest["production_allowed"])
        self.assertEqual(manifest["component_preflight"], "PASS")

    def test_no_overwrite_and_private_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            generate(private / "probe", private)
            with self.assertRaises(FileExistsError):
                generate(private / "probe", private)
            with self.assertRaises(ValueError):
                generate(Path(directory) / "outside", private)

    def test_comparator_accepts_only_known_reexport_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            paths = generate(private / "probe", private)
            rows = list(csv.reader(io.StringIO(paths["candidate"].read_text("cp932"), newline="")))
            header = rows[0]
            pos = {name: index for index, name in enumerate(header)}
            for row in rows[1:]:
                row[pos["借方消費税"]] = "0"
                row[pos["貸方消費税"]] = "0"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerow(["synthetic preamble"])
            writer.writerow([])
            writer.writerow(header)
            writer.writerows(rows[1:])
            reexport = private / "reexport.csv"
            reexport.write_bytes(stream.getvalue().encode("cp932"))
            result = compare_reexport(paths["candidate"], paths["manifest"], reexport)
        self.assertTrue(result["comparison_pass"])


if __name__ == "__main__":
    unittest.main()

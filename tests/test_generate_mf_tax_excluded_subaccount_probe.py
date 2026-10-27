from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_mf_tax_excluded_subaccount_probe import (
    generate,
)


class GenerateMfTaxExcludedSubaccountProbeTests(unittest.TestCase):
    def test_generates_exact_pending_probe_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            self._write_source(source)
            output, manifest = generate(source, root / "out")

            raw = output.read_bytes()
            rows = list(csv.reader(raw.decode("cp932").splitlines()))
            journals = rows[4:]
            payload = json.loads(manifest.read_text(encoding="utf-8"))

            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.count(b"\r\n"), 6)
            self.assertTrue(all(len(row) == 30 for row in rows))
            self.assertEqual([row[16] for row in journals], ["0001", "0001"])
            self.assertEqual(
                [row[17] for row in journals],
                ["三井住友カードご本人", "三井住友カードご本人"],
            )
            self.assertEqual(payload["evidence_status"], "PENDING_REAL_JDL_IMPORT_REEXPORT")
            self.assertFalse(payload["production_allowed"])
            with self.assertRaises(FileExistsError):
                generate(source, root / "out")

    @staticmethod
    def _write_source(path: Path) -> None:
        rows = [
            ["//識別フラグ", *(f"c{i}" for i in range(1, 30))],
            ["1111", "", "20260424", "8471", "旅費交通費", "旅費交通費", "", "", "仕　入", "10%", "内税", "1100", "100", "3181", "未払金", "未払金", "", "", "", "", "", "1100", "", "P05", "", "", "", "", "", ""],
            ["1111", "", "20260426", "8481", "通信費", "通信費", "", "", "仕　入", "10%", "内税", "1100", "100", "3181", "未払金", "未払金", "", "", "", "", "", "1100", "", "P07", "", "", "", "", "", ""],
        ]
        with path.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(rows)


if __name__ == "__main__":
    unittest.main()

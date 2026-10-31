from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_blank_subaccount_probe import generate, _csv_bytes


class BlankSubaccountProbeTests(unittest.TestCase):
    def test_two_independent_probes_are_private_and_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "verified.csv"
            master = root / "master.pdf"
            master.write_bytes(b"synthetic")
            header = list(jdl_ibex_cashbook_official_journal_import_spec().column_names)
            row = [""] * 30
            row[0], row[2] = "1111", "20260501"
            row[3:6] = ["8471", "旅費交通費", "旅費交通費"]
            row[8:13] = ["仕　入", "10%", "内税", "1100", "100"]
            row[13:18] = ["3181", "未払金", "未払金", "0001", "架空補助"]
            row[21], row[23] = "1100", "SYNTHETIC"
            source.write_bytes(_csv_bytes([header, row]))
            observed = SimpleNamespace(
                printed_accounts=(
                    SimpleNamespace(code="8471", name="旅費交通費", abbreviation="旅費交通", enabled=True),
                    SimpleNamespace(code="1551", name="売掛金", abbreviation="売掛金", enabled=True),
                    SimpleNamespace(code="1311", name="普通預金", abbreviation="普通預金", enabled=True),
                ),
                subaccounts=(
                    SimpleNamespace(parent_account_code="1551"),
                    SimpleNamespace(parent_account_code="1311"),
                ),
            )
            output = root / "probe"
            with patch(
                "accounting_converter.tools.generate_mf_blank_subaccount_probe.PypdfTextExtractor.extract_pages",
                return_value=("synthetic",),
            ), patch(
                "accounting_converter.tools.generate_mf_blank_subaccount_probe.JdlAccountListPdfTextParser.parse_pages",
                return_value=observed,
            ):
                paths = generate(source, master, output)
                self.assertEqual(len(paths), 2)
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    generate(source, master, output)
            for path in paths:
                data = path.read_bytes()
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
                with path.open(encoding="cp932", newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(len(rows), 5)
                self.assertTrue(all(len(item) == 30 for item in rows))
                self.assertEqual(rows[-1][16:18], ["", ""])
                self.assertIn(rows[-1][13], ("1551", "1311"))
                manifest = json.loads(path.with_suffix(".manifest.json").read_text())
                self.assertFalse(manifest["production_allowed"])
                self.assertEqual(manifest["evidence_status"], "PENDING")


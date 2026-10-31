from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.mf_tax_context_probe import _journal_rows, compare_probe_patterns
from accounting_converter.tools.subset_mf_pending_tax_probe import generate_clean_non_taxable_probe


class CleanPendingTaxProbeTests(unittest.TestCase):
    def test_extracts_only_two_exact_rows_with_synchronized_period(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "three.csv"
            self._source(source)
            output, manifest = generate_clean_non_taxable_probe(source, root / "clean")
            raw = output.read_bytes()
            rows = _journal_rows(output)
            self.assertEqual(len(rows), 2)
            self.assertEqual([row[2] for row in rows], ["20260521", "20260522"])
            self.assertEqual(
                [row[23] for row in rows],
                ["MF-TAX-NONPUR-PENDING", "MF-TAX-NONSALE-PENDING"],
            )
            self.assertIn(b"20260521", raw)
            self.assertNotIn(b"20260520", raw)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
            self.assertTrue(manifest.exists())
            self.assertTrue(all(
                result["evidence_eligible"]
                for result in compare_probe_patterns(
                    output, output, ("CASE-TAX-NONPUR", "CASE-TAX-NONSALE")
                )
            ))
            with self.assertRaises(FileExistsError):
                generate_clean_non_taxable_probe(source, root / "clean")

    def test_changed_source_case_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "three.csv"
            self._source(source, tamper=True)
            with self.assertRaisesRegex(ValueError, "differs"):
                generate_clean_non_taxable_probe(source, root / "clean")
            self.assertFalse((root / "clean").exists())

    @staticmethod
    def _source(path: Path, *, tamper: bool = False) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        rows = []
        for date, debit, debit_sub, debit_tax, credit, credit_sub, credit_tax, marker in (
            ("20260520", "1551", "0001", "", "6121", "", "売一種", "MF-TAX-SALES10-PENDING"),
            ("20260521", "8571", "", "非仕入", "3181", "0001", "", "MF-TAX-NONPUR-PENDING"),
            ("20260522", "1311", "0002", "", "9111", "", "非売上", "MF-TAX-NONSALE-PENDING"),
        ):
            row = [""] * 30
            row[0], row[2] = "1111", date
            row[3], row[6], row[8], row[11] = debit, debit_sub, debit_tax, "1100"
            row[13], row[16], row[18], row[21] = credit, credit_sub, credit_tax, "1100"
            row[23] = marker
            rows.append(row)
        if tamper:
            rows[1][11] = "1200"
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\r\n").writerows((header, *rows))
        path.write_bytes(stream.getvalue().encode("cp932"))


if __name__ == "__main__":
    unittest.main()

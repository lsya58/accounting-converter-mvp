from __future__ import annotations

import csv
import hashlib
import io
import unittest
from pathlib import Path


class MoneyForwardJdlFormalE2eEvidenceTests(unittest.TestCase):
    ROOT = Path("tests/evidence/e2e/mf_to_jdl_no4")

    def test_import_reexport_is_byte_identical_to_generated_output(self) -> None:
        generated = (self.ROOT / "generated_jdl.csv").read_bytes()
        reexported = (self.ROOT / "jdl_reexport.csv").read_bytes()

        self.assertEqual(generated, reexported)
        self.assertEqual(
            hashlib.sha256(generated).hexdigest(),
            "d82b08aa4636f712c115e1622a568672de41c3c588c550eaf9c46513f3adad4b",
        )
        self.assertFalse(generated.startswith((b"\xef\xbb\xbf", b"\xff\xfe")))
        self.assertEqual(generated.count(b"\r\n"), 2)
        rows = list(csv.reader(io.StringIO(generated.decode("cp932"), newline="")))
        self.assertEqual(len(rows), 2)
        self.assertEqual(tuple(map(len, rows)), (30, 30))
        self.assertEqual(rows[1][0], "1111")
        self.assertEqual(rows[1][11], rows[1][21])

    def test_source_fixture_remains_exact_observed_record(self) -> None:
        source = (self.ROOT / "source_moneyforward.csv").read_bytes()
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            "d273b74a47707d00bcb046d1091e9c48df1b270523521f3d250d20a93b2d625c",
        )
        rows = list(csv.reader(io.StringIO(source.decode("cp932"), newline="")))
        self.assertEqual(len(rows), 2)
        self.assertEqual(tuple(map(len, rows)), (19, 19))
        self.assertEqual(rows[1][0], "4")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_probe import generate as generate_base
from accounting_converter.tools.generate_2d2c_trade_partner_probe import (
    EXPECTED_DESCRIPTION,
    generate,
)


class TwoDebitTwoCreditTradePartnerProbeTests(unittest.TestCase):
    def test_changes_only_date_and_first_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            base = generate_base(private / "base", private)
            paths = generate(base["candidate"], base["manifest"], private / "probe", private)
            base_rows = list(csv.reader(io.StringIO(base["candidate"].read_text("cp932"), newline="")))
            rows = list(csv.reader(io.StringIO(paths["candidate"].read_text("cp932"), newline="")))
        header = rows[0]
        changed = {
            (row_index, header[column_index])
            for row_index, (left, right) in enumerate(zip(base_rows[1:], rows[1:], strict=True), 1)
            for column_index, (old, new) in enumerate(zip(left, right, strict=True))
            if old != new
        }
        self.assertEqual(changed, {(1, "日付"), (1, "摘要"), (2, "日付")})
        self.assertEqual(rows[1][header.index("摘要")], EXPECTED_DESCRIPTION)
        self.assertLessEqual(len(EXPECTED_DESCRIPTION), 32)
        EXPECTED_DESCRIPTION.encode("cp932", errors="strict")

    def test_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            base = generate_base(private / "base", private)
            output = private / "probe"
            generate(base["candidate"], base["manifest"], output, private)
            with self.assertRaises(FileExistsError):
                generate(base["candidate"], base["manifest"], output, private)


if __name__ == "__main__":
    unittest.main()

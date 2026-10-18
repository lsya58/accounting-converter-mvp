from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.generate_2d2c_taxable_probe import generate as generate_taxable
from accounting_converter.tools.generate_2d2c_trade_partner_no_subaccount_probe import (
    DATE,
    EXPECTED_DESCRIPTION,
    TARGET_ACCOUNT_CODE,
    TARGET_ACCOUNT_NAME,
    TARGET_CSV_NAME,
    compare_reexport,
    generate,
)
from accounting_converter.tools.generate_2d2c_trade_partner_probe import (
    generate as generate_trade_partner,
)


class TwoDebitTwoCreditTradePartnerNoSubaccountProbeTests(unittest.TestCase):
    def _generate(self, private: Path) -> dict[str, Path]:
        taxable = generate_taxable(private / "taxable", private)
        trade_partner = generate_trade_partner(
            taxable["candidate"],
            taxable["manifest"],
            private / "trade-partner",
            private,
        )
        return generate(
            trade_partner["candidate"],
            trade_partner["manifest"],
            private / "no-subaccount",
            private,
        )

    def test_changes_only_tax_side_account_subaccount_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            taxable = generate_taxable(private / "taxable", private)
            base = generate_trade_partner(
                taxable["candidate"], taxable["manifest"], private / "base", private
            )
            paths = generate(
                base["candidate"], base["manifest"], private / "probe", private
            )
            base_rows = list(
                csv.reader(io.StringIO(base["candidate"].read_text("cp932"), newline=""))
            )
            rows = list(
                csv.reader(io.StringIO(paths["candidate"].read_text("cp932"), newline=""))
            )
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

        header = rows[0]
        pos = {name: index for index, name in enumerate(header)}
        changed = {
            (row_index, header[column_index])
            for row_index, (left, right) in enumerate(
                zip(base_rows[1:], rows[1:], strict=True), 1
            )
            for column_index, (old, new) in enumerate(zip(left, right, strict=True))
            if old != new
        }
        self.assertEqual(
            changed,
            {
                (1, "日付"),
                (1, "借方科目名称"),
                (1, "借方補助"),
                (1, "借方補助名称"),
                (2, "日付"),
            },
        )
        first, second = rows[1:]
        self.assertEqual([first[0], second[0]], ["1110", "1101"])
        self.assertEqual(first[pos["借方科目名称"]], TARGET_CSV_NAME)
        self.assertFalse(first[pos["借方補助"]])
        self.assertFalse(first[pos["借方補助名称"]])
        self.assertEqual(first[pos["借方課区"]], "仕　入")
        self.assertEqual(first[pos["借方税区"]], "10%")
        self.assertEqual(first[pos["摘要"]], EXPECTED_DESCRIPTION)
        self.assertEqual(second[pos["摘要"]], "JDL-2D2C-TAX-ROW2")
        self.assertEqual(first[pos["日付"]], DATE)
        self.assertEqual(manifest["target_account"]["observed_master_code"], TARGET_ACCOUNT_CODE)
        self.assertEqual(manifest["target_account"]["observed_master_name"], TARGET_ACCOUNT_NAME)
        self.assertEqual(manifest["target_account"]["observed_subaccount_count"], 0)
        self.assertTrue(manifest["NOT_FOR_PRODUCTION"])
        self.assertFalse(manifest["production_allowed"])

    def test_strict_comparator_accepts_only_known_zero_tax_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            paths = self._generate(private)
            rows = list(
                csv.reader(io.StringIO(paths["candidate"].read_text("cp932"), newline=""))
            )
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

    def test_rejects_subaccount_or_description_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            paths = self._generate(private)
            rows = list(
                csv.reader(io.StringIO(paths["candidate"].read_text("cp932"), newline=""))
            )
            header = rows[0]
            pos = {name: index for index, name in enumerate(header)}
            rows[1][pos["借方補助"]] = "0001"
            rows[1][pos["借方補助名称"]] = "SYNTHETIC"
            rows[1][pos["摘要"]] = "changed"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerow(header)
            writer.writerows(rows[1:])
            reexport = private / "reexport.csv"
            reexport.write_bytes(stream.getvalue().encode("cp932"))
            result = compare_reexport(paths["candidate"], paths["manifest"], reexport)
        self.assertFalse(result["comparison_pass"])
        self.assertIn("tax_side_subaccount_blank", result["mismatch_field_categories"])
        self.assertIn("trade_partner_description", result["mismatch_field_categories"])

    def test_no_overwrite_and_private_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            taxable = generate_taxable(private / "taxable", private)
            base = generate_trade_partner(
                taxable["candidate"], taxable["manifest"], private / "base", private
            )
            output = private / "probe"
            generate(base["candidate"], base["manifest"], output, private)
            with self.assertRaises(FileExistsError):
                generate(base["candidate"], base["manifest"], output, private)
            with self.assertRaises(ValueError):
                generate(
                    base["candidate"],
                    base["manifest"],
                    Path(directory) / "outside",
                    private,
                )


if __name__ == "__main__":
    unittest.main()

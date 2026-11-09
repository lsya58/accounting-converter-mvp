import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools import yayoi_negative_probe as np

HEADER = ["h"] * 30


def row(case, debit="", dtax="", credit="", ctax=""):
    values = [""] * 30
    values[0], values[2] = "1100", "20260613"
    values[11], values[12], values[21], values[22], values[23] = debit or "0", dtax, credit or "0", ctax, case
    return values


class NegativeProbeTest(unittest.TestCase):
    def test_negate_voucher_signs_amount_tax_and_credit(self):
        rows = [row("X-R1", credit="2970"), row("X-R2", "2970", "270"), row("X-R3", "1485", "135")]
        out = np.negate_voucher(rows, (1,), {0: 2970})
        self.assertEqual([r[11] for r in out], ["0", "2970", "-1485"])
        self.assertEqual([r[12] for r in out], ["", "270", "-135"])
        self.assertEqual(out[0][21], "1485")  # 2970 - 1485
        self.assertEqual(rows[2][11], "1485")  # input untouched

    def test_counterpart_with_tax_is_refused(self):
        with self.assertRaises(ValueError):
            np.negate_voucher([row("X-R1", credit="100", ctax="9"), row("X-R2", "100")], ())

    def test_judge_requires_signs_to_survive(self):
        probe = Path(tempfile.mkdtemp()) / "p.csv"
        good = Path(probe.parent) / "g.csv"
        flipped = Path(probe.parent) / "f.csv"

        def write(path, rows):
            import csv, io
            buffer = io.StringIO(newline="")
            csv.writer(buffer, lineterminator="\r\n").writerows([HEADER, *rows])
            path.write_bytes(buffer.getvalue().encode("cp932"))

        base = [row("CTL-NEG", "1", "", "1"), row("NEG-MIN-R1", credit="1485"),
                row("NEG-MIN-R2", "2970", "270"), row("NEG-MIN-R3", "-1485", "-135")]
        write(probe, base)
        write(good, base)
        bad = [list(r) for r in base]
        bad[3][11], bad[3][12] = "1485", "135"  # JDL turned the negative line positive
        write(flipped, bad)
        manifest = {"cases": [{"case": "CTL-NEG"}, {"case": "NEG-MIN"}]}
        self.assertEqual(np.judge(probe, good, manifest)["result"], "NEGATIVE_DEBIT_PRESERVED")
        outcome = np.judge(probe, flipped, manifest)
        self.assertEqual(outcome["result"], "NOT_PROVEN")
        self.assertEqual(outcome["cases"]["NEG-MIN"]["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()


class SplitRuleStaysClosedToNegativeLinesTest(unittest.TestCase):
    """Production guard: the approvable rule (V1) must keep refusing journals with a non-positive line."""

    def test_rule_v1_refuses_negative_lines(self):
        import inspect

        from accounting_converter.application import voucher_split

        source = inspect.getsource(voucher_split.ineligible_reason)
        self.assertIn('"NON_POSITIVE_AMOUNT"', source)
        self.assertIn("line.amount <= 0", source)


class ErrorLogTest(unittest.TestCase):
    def test_messages_attach_to_the_row_above(self):
        text = ("// header\r\n\r\n//識別フラグ,x\r\n"
                + ",".join(["1111"] + [""] * 22 + ["CTL-NEG"] + [""] * 6) + "\r\n"
                + ",".join(["1110"] + [""] * 22 + ["NEG-MIN-R1"] + [""] * 6) + "\r\n"
                + "//  伝票内にエラーの仕訳が含まれています\r\n"
                + ",".join(["1101"] + [""] * 22 + ["NEG-MIN-R2"] + [""] * 6) + "\r\n"
                + "//  [借方金額]に数値以外が含まれています\r\n//  [借方消費税]に数値以外が含まれています\r\n")
        path = Path(tempfile.mkdtemp()) / "log.txt"
        path.write_bytes(text.encode("cp932"))
        result = np.analyze_error_log(path)
        self.assertEqual(result["rows_in_log"], 3)
        self.assertEqual(result["cases"]["CTL-NEG"]["messages"], {"(no message)": 1})
        self.assertEqual(result["cases"]["NEG-MIN"]["messages"]["伝票内にエラーの仕訳が含まれています"], 1)
        self.assertIn("[借方金額]に数値以外が含まれています / [借方消費税]に数値以外が含まれています",
                      result["cases"]["NEG-MIN"]["messages"])

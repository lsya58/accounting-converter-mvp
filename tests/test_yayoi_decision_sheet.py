"""Grouped decisions expand into the office sheet; nothing bypasses its checks. Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from accounting_converter.application.yayoi_sources import IMPORT
from accounting_converter.tools import yayoi_decision_sheet as ds
from accounting_converter.tools import yayoi_office_sheet as office
from tests.test_yayoi_import_format import OUTSIDE, SALES, YAYOI, Company, floor_context, journals, row, write_import


def read(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))


def save(path: Path, records: list[dict]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    path.write_bytes(buffer.getvalue().encode("utf-8-sig"))


class DecisionSheetTest(unittest.TestCase):
    LONG = "テスト商事株式会社 定期購入代金 定期購入代金 定期購入代金 1234-5678-9012"  # 72 CP932 bytes

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "data" / "private"
        self.root.mkdir(parents=True)
        rows = journals() + [
            # Same-name accounts so the bulk unit has items.
            row("2000", 7, "R.08/05/15", ("現金", "", OUTSIDE, 3300, 0), ("売上高", "", SALES, 3300, 300), self.LONG),
            row("2000", 8, "R.08/05/16", ("現金", "", OUTSIDE, 1100, 0), ("売上高", "", SALES, 1100, 100),
                "テスト商事株式会社 定期購入代金 9999-8888-7777"),
        ]
        self.source = write_import(self.root, rows)
        self.company = Company(self.root, "company-d", self.source, IMPORT, floor_context())
        self.args = dict(source=self.source, company_store=self.root, company_id="company-d")

    def tearDown(self):
        self._tmp.cleanup()

    def write_sheets(self):
        with mock.patch("builtins.print"):
            ds.write(SimpleNamespace(**self.args, output_dir=self.root, tag="t"))
        return self.root / "判断シート_t.csv", self.root / "摘要ルール_t.csv", self.root / "判断シート_一括対象一覧_t.csv"

    def expand(self, decisions, rules, preview_sha="", name="expanded.csv"):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = ds.expand(SimpleNamespace(**self.args, decisions=decisions, rules=rules,
                                             output=self.root / name, preview_sha=preview_sha))
        return code, json.loads(out.getvalue())

    def test_units_group_rows_and_nothing_is_pre_approved(self):
        decisions, rules, details = self.write_sheets()
        units = read(decisions)
        kinds = {u["単位ID"].split("-")[0] for u in units}
        self.assertIn("ACC", kinds)
        bulk = next(u for u in units if u["単位ID"] == "ACC-ALL-SAME")
        self.assertEqual(int(bulk["対象件数"]), 2)  # 現金, 売上高
        self.assertEqual(len([d for d in read(details) if d["単位ID"] == "ACC-ALL-SAME"]), 2)
        self.assertTrue(all(not u["【記入】判断"] and not u["【記入】コード"] for u in units))
        self.assertTrue(all(not r["【記入】承認"] for r in read(rules)))

    def test_bulk_ok_expands_and_a_changed_list_is_refused(self):
        decisions, rules, _ = self.write_sheets()
        units = read(decisions)
        for unit in units:
            if unit["単位ID"] == "ACC-ALL-SAME":
                unit["【記入】判断"] = "OK"
        save(decisions, units)
        code, result = self.expand(decisions, rules)
        self.assertEqual(code, 0)
        self.assertEqual(result["filled"]["bulk:科目"], 2)
        self.assertEqual(result["check"], "PASS")
        filled = read(self.root / "expanded.csv")
        self.assertEqual({r["キー"] for r in filled if r["【記入】判断"] == "OK"}, {"現金", "売上高"})
        # A target list that no longer matches (e.g. other master) is refused.
        for unit in units:
            if unit["単位ID"] == "ACC-ALL-SAME":
                unit["対象一覧SHA"] = "0" * 64
        save(decisions, units)
        code, result = self.expand(decisions, rules, name="expanded2.csv")
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "expanded2.csv").exists())

    def test_rules_keep_every_digit_and_need_the_preview_sha(self):
        decisions, rules, _ = self.write_sheets()
        records = read(rules)
        for rule in records:
            rule["【記入】承認"] = "OK"
            if rule["種類"] == "語句の短縮":
                rule["【記入】短縮後の語句"] = rule["対象の語句"][:2]
        save(rules, records)
        code, first = self.expand(decisions, rules)
        self.assertEqual(code, 0)
        self.assertFalse(first["descriptions_filled"])  # not before the Human saw the preview
        self.assertNotIn("description:filled", first["filled"])
        preview = next(self.root.glob("expanded_摘要プレビュー_*.csv"))
        self.assertGreaterEqual(sum(1 for line in read(preview) if line["状態"].startswith("適合")), 1)
        for line in read(preview):
            if line["置換後（ルール適用）"]:
                digits = lambda t: "".join(c for c in t if c.isdigit())  # noqa: E731
                if line["状態"].startswith("適合"):
                    self.assertEqual(digits(line["置換後（ルール適用）"]), digits(line["元の摘要"]))
                    self.assertLessEqual(len(line["置換後（ルール適用）"]), 32)
                    self.assertIn("(株)", line["置換後（ルール適用）"])
        code, second = self.expand(decisions, rules, preview_sha=first["preview_sha256"], name="expanded3.csv")
        self.assertEqual(code, 0)
        self.assertTrue(second["descriptions_filled"])
        self.assertEqual(second["check"], "PASS")

    def test_a_rule_result_that_changes_any_digit_is_never_used(self):
        rules = [{"種類": "繰り返し語の削除", "対象の語句": "", "【記入】短縮後の語句": ""}]
        original = "テスト 1234 1234"
        result = ds.apply_rules(original, rules)
        self.assertNotEqual(ds._digits(result), ds._digits(original))  # expand rejects this result
        self.assertEqual(ds.apply_rules("テスト商事株式会社", [{"種類": "法人格の略記"}]), "テスト商事(株)")

    def test_expanded_sheet_still_goes_through_the_office_apply(self):
        decisions, rules, _ = self.write_sheets()
        units = read(decisions)
        for unit in units:
            if unit["単位ID"] == "ACC-ALL-SAME":
                unit["【記入】判断"] = "OK"
        save(decisions, units)
        self.expand(decisions, rules)
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        with mock.patch("builtins.print"):
            code = office.apply(SimpleNamespace(**self.args, sheet=self.root / "expanded.csv", check=True))
        self.assertEqual(code, 0)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*.json")}, before)  # check-only wrote nothing


if __name__ == "__main__":
    unittest.main()

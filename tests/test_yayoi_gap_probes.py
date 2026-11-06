"""Gap round tooling (2026-11-06): conditions, Probe judgement, description relief, demo files. Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import YayoiJournalReportParser
from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.application import scoped_evidence_composition as composition
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_demo_files as demo
from accounting_converter.tools import yayoi_gap_probe_plan as plan
from accounting_converter.tools.yayoi_description_limit_relief import length_only_within
from accounting_converter.tools.yayoi_gap_probe_check import check_round
from accounting_converter.tools.yayoi_probe_check import manifest_path_for

d = Decimal


class FractionRelationTest(unittest.TestCase):
    def test_fractional_relations_are_classified(self):
        # R8 1000 -> exact 74.07; 1200 -> 88.89. T80 1050 -> 76.36; 1000 -> 72.73.
        self.assertEqual(scoped.relation_of("R8", d(1000), d(74)), "HALF_LOW")
        self.assertEqual(scoped.relation_of("R8", d(1200), d(89)), "HALF_HIGH")
        self.assertEqual(scoped.relation_of("R8", d(1200), d(88)), "FLOOR_HIGH")
        self.assertIsNone(scoped.relation_of("R8", d(1000), d(75)))  # ceil of a low fraction: never observed
        self.assertEqual(scoped.relation_of("T80", d(1050), d(76)), "HALF_LOW")
        self.assertEqual(scoped.relation_of("T80", d(1000), d(73)), "HALF_HIGH")
        self.assertEqual(scoped.relation_of("T80", d(1000), d(72)), "FLOOR_HIGH")

    def test_only_the_round_tripped_relations_are_allowed_and_only_on_8471(self):
        # Real JDL 2026-11-06 (G3): kept unchanged on 8471.
        for cell, relation in (("R8", "HALF_LOW"), ("R8", "HALF_HIGH"), ("T80", "HALF_LOW"),
                               ("T80", "HALF_HIGH"), ("T80", "FLOOR_HIGH")):
            with self.subTest(cell=cell, relation=relation):
                self.assertTrue(scoped.relation_covers_account("DEBIT", cell, relation, "8471"))
                self.assertFalse(scoped.relation_covers_account("DEBIT", cell, relation, "8481"))
        # Never probed: stays blocked.
        self.assertFalse(scoped.relation_covers_account("DEBIT", "R8", "FLOOR_HIGH", "8471"))
        gaps, _ = composition.line_gaps(composition.ScopedLine("DEBIT", "8471", "R8", d(1200), d(88)))
        self.assertTrue(gaps)
        gaps, _ = composition.line_gaps(composition.ScopedLine("DEBIT", "8471", "T80", d(1000), d(72)))
        self.assertEqual(gaps, [])

    def test_exact_relations_unchanged(self):
        self.assertEqual(scoped.relation_of("R8", d(1080), d(80)), "EXACT")
        self.assertEqual(scoped.relation_of("T80", d(1100), d(80)), "EXACT")
        self.assertTrue(scoped.relation_covers_account("DEBIT", "T80", "EXACT", "8471"))


class ConditionTest(unittest.TestCase):
    def test_registered_layout_and_cells_are_not_listed_again(self):
        self.assertEqual(plan.conditions((("NO", "S10"),) * 3, "B3", ()), set())

    def test_unobserved_layout_cell_pair_and_amount_are_listed(self):
        needs = plan.conditions((("NO", "S10"),) * 20, "B20", (("DEBIT", "R8", "FLOOR_HIGH"),))
        self.assertIn(("LAYOUT", "B20"), needs)
        self.assertIn(("CELL", "B20", "CREDIT", "S10"), needs)
        self.assertIn(("EXPLICIT", "DEBIT", "R8", "FLOOR_HIGH"), needs)
        self.assertIn(("PAIR", "T80", "S10"), plan.conditions((("T80", "S10"),), "B1", ()))

    def test_probe_provides_exactly_its_own_signature(self):
        provided = plan.provided((("P10", "NO"), ("NO", "S10")), "B2")
        self.assertEqual(provided, {("LAYOUT", "B2"), ("CELL", "B2", "DEBIT", "P10"), ("CELL", "B2", "CREDIT", "S10")})


HEADER = jdl_ibex_cashbook_official_journal_import_spec().column_names


def _row(flag, debit, credit, amount, description, tax=""):
    row = [""] * 30
    row[0], row[2], row[3], row[13], row[11], row[21], row[23] = flag, "20260621", debit, credit, amount, amount, description
    row[12] = tax
    row[4] = row[5] = f"科目{debit}"
    row[14] = row[15] = f"科目{credit}"
    return row


def _write(path: Path, rows):
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((HEADER, *rows))
    path.write_bytes(buffer.getvalue().encode("cp932"))


class CheckRoundTest(unittest.TestCase):
    def _round(self, directory: Path):
        probe = directory / "YAYOI_GAP_G9_20260621_NOT_FOR_PRODUCTION.csv"
        rows = [
            _row("1111", "1111", "6121", "1485", "CTL-G9"),
            _row("1111", "1111", "3181", "1000", "CASE-A"),
            _row("1110", "1111", "3181", "2000", "CASE-B-R1"),
            _row("1101", "1111", "3181", "2000", "CASE-B-R2"),
            _row("1111", "1111", "3181", "3000", "CASE-C"),
            _row("1111", "1111", "3181", "1000", "DS-HW33" + "A" * 26),
        ]
        _write(probe, rows)
        import hashlib

        cases = [("CTL-G9", 0, 1, "CONTROL", False), ("CASE-A", 1, 1, "G1", False), ("CASE-B", 2, 2, "G1", False),
                 ("CASE-C", 3, 1, "G1", False), ("DS-HW33", 4, 1, "G4-DESC", True)]
        manifest = {"batch": "G9", "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
                    "expected_physical_rows": len(rows), "scope_id": scoped.SCOPE_ID, "target": "JDL IBEX 出納帳 35.5",
                    "voucher_row_limit": 16, "sales_tax_rounding": "CEILING", "purchase_tax_rounding": "HALF_UP",
                    "cases": [{"case": c, "journal_index": i, "physical_rows": n, "group": g, "description_under_test": desc,
                               "pending_evidence_id": f"PENDING:{c}"} for c, i, n, g, desc in cases]}
        manifest_path_for(probe).write_text(json.dumps(manifest), encoding="utf-8")
        return rows

    def test_verdicts_pass_changed_missing_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rows = self._round(directory)
            back = [list(r) for r in rows]
            back[1][11] = back[1][21] = "1001"  # CASE-A changed
            del back[4]  # CASE-C missing (rejected)
            back[-1][23] = back[-1][23][:32]  # description truncated
            reexport = directory / "reexport.csv"
            _write(reexport, back)
            report = check_round(directory, reexport)
        verdicts = report["files"]["YAYOI_GAP_G9_20260621_NOT_FOR_PRODUCTION.csv"]["verdicts"]
        self.assertEqual(verdicts, {"CTL-G9": "PASS", "CASE-A": "CHANGED", "CASE-B": "PASS", "CASE-C": "MISSING",
                                    "DS-HW33": "TRUNCATED"})
        self.assertTrue(report["round_valid"])
        self.assertEqual([r["case"] for r in report["pass_records"]], ["CTL-G9", "CASE-B"])
        self.assertEqual(report["pass_records"][1]["applies_only_to"]["layout"], "B2")

    def test_extra_or_duplicate_journal_invalidates_the_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rows = self._round(directory)
            reexport = directory / "reexport.csv"
            _write(reexport, [*rows, _row("1111", "1111", "3181", "9999", "STRANGER")])
            extra = check_round(directory, reexport)
            _write(reexport, [*rows, rows[1]])
            duplicate = check_round(directory, reexport)
        self.assertFalse(extra["round_valid"])
        self.assertEqual(extra["extra_unexplained_reexport_journals"], 1)
        self.assertFalse(duplicate["round_valid"])
        self.assertIn("CASE-A", duplicate["duplicate_identifiers"])

    def test_nothing_is_pass_without_a_reexport_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._round(directory)
            reexport = directory / "reexport.csv"
            _write(reexport, [])
            report = check_round(directory, reexport)
        self.assertEqual(report["verdict_totals"], {"MISSING": 5})
        self.assertEqual(report["pass_records"], [])


class DescriptionLimitTest(unittest.TestCase):
    """Real JDL 2026-11-06 (G4 kept / G5 truncated silently at 64 CP932 bytes)."""

    def test_boundaries(self):
        from accounting_converter.profiles.jdl_official import jdl_description_fits

        for kept in ("あ" * 32, "A" * 64, "ｱ" * 40, "あ" * 22 + "B" * 20, " -./@()#$,&*_+':" * 4,
                     "テスト商事 定期購入代金 1234-5678/90 (7).8@"):
            with self.subTest(kept=kept):
                self.assertTrue(jdl_description_fits(kept))
        for refused in ("A" * 65, "あ" * 33, "あ" * 22 + "B" * 21, "!" * 33, '"' * 33, "A" * 32 + "%"):
            with self.subTest(refused=refused):
                self.assertFalse(jdl_description_fits(refused))
        self.assertTrue(jdl_description_fits("!" * 32))  # the 32-character rule is unchanged

    def test_a_confirmed_replacement_stays_in_force_when_the_original_now_fits(self):
        from types import SimpleNamespace

        from accounting_converter.application.description_replacement import description_sha256
        from accounting_converter.application.moneyforward_description_replacement import (
            MF_DESCRIPTION_REPLACEMENT_POLICY,
            MoneyForwardDescriptionReplacementPolicy,
            moneyforward_description_replacement_key,
        )
        from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference
        from accounting_converter.domain.mapping import MappingStatus, MappingValue

        original = "A" * 40  # fits JDL now (40 bytes); the Human had confirmed a replacement before
        key = moneyforward_description_replacement_key(original)
        mapping = MappingValue(key, "短い摘要", MappingStatus.USER_CONFIRMED, metadata={
            "policy": MF_DESCRIPTION_REPLACEMENT_POLICY, "original_description_sha256": description_sha256(original)})
        ref = SourceReference("t", 1)
        entry = JournalEntry("e", ref, __import__("datetime").date(2026, 6, 1),
                             [JournalLine(Side.DEBIT, "現金", d(1), ref), JournalLine(Side.CREDIT, "売上", d(1), ref)],
                             description=original)
        result = MoneyForwardDescriptionReplacementPolicy(
            SimpleNamespace(loss_policy_mappings={key: mapping})).apply([entry])
        self.assertEqual(result.entries[0].description, "短い摘要")
        unconfirmed = MoneyForwardDescriptionReplacementPolicy(SimpleNamespace(loss_policy_mappings={})).apply([entry])
        self.assertEqual(unconfirmed.entries[0].description, original)
        self.assertEqual(unconfirmed.validation_results, ())


class DescriptionReliefTest(unittest.TestCase):
    def test_only_length_problems_within_the_byte_limit_are_relieved(self):
        self.assertTrue(length_only_within("A" * 64, 64))
        self.assertTrue(length_only_within("あ" * 32, 64))
        self.assertFalse(length_only_within("A" * 65, 64))
        self.assertFalse(length_only_within("あ" * 33, 64))
        self.assertFalse(length_only_within("A\tB", 64))


class DemoFilesTest(unittest.TestCase):
    def test_demo_files_parse_without_issues(self):
        names = {"1111": "現金", "6121": "売上高", "8471": "消耗品費", "8571": "支払手数料", "3181": "未払金"}
        with tempfile.TemporaryDirectory() as tmp:
            normal, blocked = demo.demo_journals(names)
            for journals, count in ((normal, 5), (blocked, 5)):
                path = Path(tmp) / "demo.txt"
                path.write_bytes(demo._render("デモ株式会社", journals))
                result = YayoiJournalReportParser().diagnose(path)
                self.assertEqual(result.issues, ())
                self.assertEqual(len(result.entries), count)
        lengths = [len(rows) for _, rows in blocked]
        self.assertIn(17, lengths)
        self.assertTrue(all(len(rows) <= 16 for _, rows in normal))


if __name__ == "__main__":
    unittest.main()

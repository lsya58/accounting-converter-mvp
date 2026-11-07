"""控除不可 Probes: file layout, raw tax columns, registry exclusion and the tax-summary judgement.

Synthetic values only. The generation test uses the private test store when present (skipped otherwise)."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from accounting_converter.tools import generate_yayoi_noncredit_probes as nc
from accounting_converter.tools import yayoi_noncredit_probe_check as judge

ACCOUNTS = {"cash": "1111"}


def manifest(batch: str) -> dict:
    note, cases = nc.files(ACCOUNTS)[batch]
    return {"batch": batch, "probe_date": "20260705", "summary_fields": nc.SUMMARY_FIELDS,
            "probe_file": f"YAYOI_GAP_{batch}_20260705_NOT_FOR_PRODUCTION.csv",
            "cases": [nc.case_manifest(c, i) for i, c in enumerate(cases)]}


def readings(before: dict, after: dict) -> tuple[dict, dict]:
    base = {"PUR10_AMOUNT": 0, "PUR10_TAX": 0, "PUR8_AMOUNT": 0, "PUR8_TAX": 0, "NONTAX_PURCHASE": 0, "CREDITABLE_TAX": 0}
    return ({k: Decimal(v) for k, v in {**base, **before}.items()},
            {k: Decimal(v) for k, v in {**base, **after}.items()})


class LayoutTest(unittest.TestCase):
    def test_every_file_starts_with_a_known_purchase_control_and_has_no_sales_line(self):
        for name, (_note, cases) in nc.files(ACCOUNTS).items():
            self.assertEqual(cases[0].candidate, "CONTROL", name)
            self.assertIsNone(cases[0].written)  # production writing, already round-tripped
            for case in cases:
                debit, credit = case.case.rows[0]
                self.assertEqual(debit.account, nc.EXPENSE)
                self.assertEqual((credit.account, credit.tax), ("1111", "NO"))

    def test_risky_writings_are_alone_in_their_file(self):
        for name in ("NONCREDIT_B10", "NONCREDIT_B8", "NONCREDIT_C10", "NONCREDIT_C8"):
            _note, cases = nc.files(ACCOUNTS)[name]
            self.assertEqual([c.candidate for c in cases].count("CONTROL"), 1)
            self.assertEqual(len(cases), 2)

    def test_case_ids_and_amounts_are_unique_so_the_tax_summary_can_be_attributed(self):
        cases = [c for _n, (_t, cs) in nc.files(ACCOUNTS).items() for c in cs if c.candidate != "CONTROL"]
        self.assertEqual(len({c.case.case_id for c in cases}), len(cases))
        self.assertEqual(len({c.case.rows[0][0].amount for c in cases}), len(cases))

    def test_noncredit_is_never_written_as_out_of_scope_or_non_taxable_without_being_marked(self):
        kinds = {c.case.case_id: (c.candidate, c.written) for _n, (_t, cs) in nc.files(ACCOUNTS).items() for c in cs}
        self.assertEqual(kinds["NC-A-OOS-10"][0], "COMPARISON")  # 対象外 is only a comparison
        self.assertEqual(kinds["NC-C10-P10-T0"][0], "NEGATIVE")
        self.assertEqual(kinds["NC-A-NP-10"][1], ("非仕入", "", "", ""))

    def test_override_writes_exactly_the_four_debit_tax_columns(self):
        row = tuple(str(i) for i in range(30))
        written = nc.override_tax_columns(row, ("非仕入", "10%", "内税", "0"))
        self.assertEqual([written[i] for i in nc.DEBIT_TAX_COLUMNS], ["非仕入", "10%", "内税", "0"])
        self.assertEqual([v for i, v in enumerate(written) if i not in nc.DEBIT_TAX_COLUMNS],
                         [v for i, v in enumerate(row) if i not in nc.DEBIT_TAX_COLUMNS])


class TaxSummaryJudgementTest(unittest.TestCase):
    def test_noncredit_writing_that_adds_nothing_to_taxable_purchases_is_consistent(self):
        before, after = readings({}, {"PUR10_AMOUNT": 11000, "PUR10_TAX": 1000, "NONTAX_PURCHASE": 44000})
        result = judge.judge_step(manifest("NONCREDIT_B10"), before, after, {}, None)
        self.assertNotIn("undetermined", result)
        self.assertFalse(result["cases"]["NC-B10-NP-R10"]["entered_taxable_purchase_or_tax"])

    def test_a_writing_that_enters_taxable_purchases_is_detected(self):
        before, after = readings({}, {"PUR10_AMOUNT": 66000, "PUR10_TAX": 1000})
        result = judge.judge_step(manifest("NONCREDIT_C10"), before, after, {}, None)
        self.assertTrue(result["cases"]["NC-C10-P10-T0"]["entered_taxable_purchase_or_tax"])

    def test_recomputed_tax_is_detected(self):
        before, after = readings({}, {"PUR10_AMOUNT": 11000, "PUR10_TAX": 5000})
        result = judge.judge_step(manifest("NONCREDIT_B10"), before, after, {}, None)
        self.assertTrue(result["cases"]["NC-B10-NP-R10"]["entered_taxable_purchase_or_tax"])

    def test_attribution_inside_the_known_writing_file(self):
        # 対象外 33,000 entered 課税仕入 10%; 非仕入 22,000 did not.
        before, after = readings({}, {"PUR10_AMOUNT": 44000, "PUR10_TAX": 1000, "PUR8_AMOUNT": 10800, "PUR8_TAX": 800})
        result = judge.judge_step(manifest("NONCREDIT_A"), before, after, {}, None)
        self.assertTrue(result["cases"]["NC-A-OOS-10"]["entered_taxable_purchase_or_tax"])
        self.assertFalse(result["cases"]["NC-A-NP-10"]["entered_taxable_purchase_or_tax"])

    def test_tax_exclusive_display_is_understood(self):
        before, after = readings({}, {"PUR10_AMOUNT": 10000, "PUR10_TAX": 1000})
        result = judge.judge_step(manifest("NONCREDIT_B10"), before, after, {"PUR10_AMOUNT": "税抜"}, None)
        self.assertNotIn("undetermined", result)
        self.assertFalse(result["cases"]["NC-B10-NP-R10"]["entered_taxable_purchase_or_tax"])

    def test_a_control_that_does_not_add_up_makes_the_step_undetermined(self):
        before, after = readings({}, {"PUR10_AMOUNT": 12345, "PUR10_TAX": 1000})
        self.assertIn("undetermined", judge.judge_step(manifest("NONCREDIT_B10"), before, after, {}, None))

    def test_credit_must_match_the_control_share_when_the_ratio_is_given(self):
        before, after = readings({}, {"PUR10_AMOUNT": 11000, "PUR10_TAX": 1000, "CREDITABLE_TAX": 950})
        ok = judge.judge_step(manifest("NONCREDIT_B10"), before, after, {}, Decimal("0.95"))
        self.assertTrue(ok["cases"]["NC-B10-NP-R10"]["credit_consistent_with_control_only"])
        before, after = readings({}, {"PUR10_AMOUNT": 11000, "PUR10_TAX": 1000, "CREDITABLE_TAX": 4750})
        bad = judge.judge_step(manifest("NONCREDIT_B10"), before, after, {}, Decimal("0.95"))
        self.assertIn("undetermined", bad)


class EndToEndJudgeTest(unittest.TestCase):
    """judge(): round verdicts + readings sheet + accountant sign-off -> the five result categories."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "data" / "private"
        self.root.mkdir(parents=True)
        for batch in ("NONCREDIT_A", "NONCREDIT_B10", "NONCREDIT_B8", "NONCREDIT_C10", "NONCREDIT_C8"):
            path = self.root / f"YAYOI_GAP_{batch}_20260705_NOT_FOR_PRODUCTION.csv"
            path.write_bytes(b"")
            (self.root / (path.name + ".manifest.json")).write_text(json.dumps(manifest(batch)), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _report(self, verdicts):
        path = self.root / "round.json"
        path.write_text(json.dumps({"round_valid": True, "files": {"all": {"verdicts": verdicts}}}), encoding="utf-8")
        return path

    def _sheet(self, values: dict, signed=()):
        sheet = self.root / "readings.csv"
        judge.write_sheet(self.root, sheet)
        rows = list(csv.reader(io.StringIO(sheet.read_text(encoding="utf-8-sig"))))
        for row in rows[1:]:
            if row[0] == "READING" and (row[1], row[2]) in values:
                row[5] = str(values[(row[1], row[2])])
            elif row[0] == "READING":
                row[5] = "0" if row[1] == "before" else row[5]
            if row[0] == "SIGNOFF" and row[2] in signed:
                row[5] = "済"
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        sheet.write_text("﻿" + buffer.getvalue(), encoding="utf-8")
        return sheet

    def test_categories(self):
        verdicts = {c["case"]: "PASS" for b in ("NONCREDIT_A", "NONCREDIT_B10", "NONCREDIT_B8", "NONCREDIT_C10", "NONCREDIT_C8")
                    for c in manifest(b)["cases"]}
        verdicts["NC-B8-NP-R8"] = "MISSING"
        verdicts["NC-C8-R8-T0"] = "CHANGED"
        a = {"PUR10_AMOUNT": 11000, "PUR10_TAX": 1000, "PUR8_AMOUNT": 10800, "PUR8_TAX": 800, "NONTAX_PURCHASE": 43600}
        b10 = {k: v for k, v in a.items()}
        b10.update({"PUR10_AMOUNT": 22000, "PUR10_TAX": 2000, "NONTAX_PURCHASE": 87600})
        c10 = dict(b10, PUR10_AMOUNT=88000, PUR10_TAX=3000)
        values = {("after_NONCREDIT_A", k): v for k, v in a.items()}
        values.update({("after_NONCREDIT_B10", k): v for k, v in b10.items()})
        values.update({("after_NONCREDIT_C10", k): v for k, v in c10.items()})
        sheet = self._sheet(values, signed=("NC-B10-NP-R10",))
        result = judge.judge(self.root, self._report(verdicts), sheet)["cases"]
        self.assertEqual(result["NC-A-NP-10"]["result"], "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN")
        self.assertEqual(result["NC-A-OOS-10"]["result"], "NOT_ADOPTED_COMPARISON")
        self.assertEqual(result["NC-B10-NP-R10"]["result"], "EQUIVALENCE_CONFIRMED")
        self.assertEqual(result["NC-B8-NP-R8"]["result"], "IMPORT_REJECTED")
        self.assertEqual(result["NC-C10-P10-T0"]["result"], "TAX_SUMMARY_SHOWS_CREDIT")
        self.assertEqual(result["NC-C8-R8-T0"]["result"], "IMPORTED_REEXPORT_CHANGED")

    def test_without_readings_a_round_trip_pass_is_not_a_meaning(self):
        verdicts = {c["case"]: "PASS" for c in manifest("NONCREDIT_A")["cases"]}
        result = judge.judge(self.root, self._report(verdicts), None)["cases"]
        self.assertEqual(result["NC-A-NP-10"]["result"], "CSV_PASS_MEANING_UNVERIFIED")


REAL_RESULT = {  # what the 2026-11-07 JDL re-export showed (verdicts and raw differences only)
    "files_with_nothing_reexported": ["YAYOI_GAP_NONCREDIT_B10_20260705_NOT_FOR_PRODUCTION.csv",
                                      "YAYOI_GAP_NONCREDIT_B8_20260705_NOT_FOR_PRODUCTION.csv"],
    "verdicts": {"NC-A-CTL-P10": "PASS", "NC-A-CTL-R8": "PASS", "NC-A-NP-10": "PASS", "NC-A-NP-8": "PASS",
                 "NC-A-OOS-10": "PASS", "NC-B10-CTL-P10": "MISSING", "NC-B10-NP-R10": "MISSING",
                 "NC-B8-CTL-P10": "MISSING", "NC-B8-NP-R8": "MISSING", "NC-C10-CTL-P10": "PASS",
                 "NC-C10-P10-T0": "CHANGED", "NC-C8-CTL-P10": "PASS", "NC-C8-R8-T0": "CHANGED"},
    "details": {
        "NC-C10-P10-T0": {"raw_differences": [
            {"row": 1, "column": "借方消費税", "expected": "0", "actual": "5000"},
            {"row": 1, "column": "貸方消費税", "expected": "", "actual": "0"},
            {"row": 1, "column": "借方部門コード", "expected": "", "actual": "0"}]},
        "NC-C8-R8-T0": {"raw_differences": [
            {"row": 1, "column": "借方消費税", "expected": "0", "actual": "4000"},
            {"row": 1, "column": "貸方部門コード", "expected": "", "actual": "0"}]},
    },
}


class RealResultJudgementTest(EndToEndJudgeTest):
    def _real_report(self):
        path = self.root / "real.json"
        path.write_text(json.dumps({"round_valid": True, "files_with_nothing_reexported": REAL_RESULT["files_with_nothing_reexported"],
                                    "files": {"all": {"verdicts": REAL_RESULT["verdicts"], "details": REAL_RESULT["details"]}}}),
                        encoding="utf-8")
        return path

    def test_without_tax_summary(self):
        result = judge.judge(self.root, self._real_report(), None)["cases"]
        self.assertEqual(result["NC-A-NP-10"]["result"], "CSV_PASS_MEANING_UNVERIFIED")
        self.assertEqual(result["NC-A-OOS-10"]["result"], "NOT_ADOPTED_COMPARISON")
        self.assertEqual(result["NC-B10-NP-R10"]["result"], "IMPORT_REJECTED")
        self.assertTrue(result["NC-B8-NP-R8"]["whole_file_absent_including_control"])
        self.assertEqual(result["NC-C10-P10-T0"]["result"], "TAX_RECOMPUTED_BY_JDL")
        self.assertEqual(result["NC-C8-R8-T0"]["tax_written_then_reexported"], ("0", "4000"))

    def _combined(self, after: dict, ratio="95"):
        sheet = self.root / "combined.csv"
        judge.write_sheet(self.root, sheet, combined=True)
        rows = list(csv.reader(io.StringIO(sheet.read_text(encoding="utf-8-sig"))))
        for row in rows[1:]:
            if row[0] == "RATIO":
                row[5] = ratio
            elif row[0] == "READING":
                row[5] = "0" if row[1] == "before" else str(after.get(row[2], 0))
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        sheet.write_text("\ufeff" + buffer.getvalue(), encoding="utf-8")
        return judge.judge(self.root, self._real_report(), sheet)

    # Expected if 非仕入 / 対象外 add nothing to taxable purchases: controls x3 + the two recomputed lines.
    CONSISTENT = {"PUR10_AMOUNT": 88000, "PUR10_TAX": 8000, "PUR8_AMOUNT": 64800, "PUR8_TAX": 4800,
                  "NONTAX_PURCHASE": 43600, "CREDITABLE_TAX": 12160, "TB_8471": 216600, "TB_KARIBARAI": 12800,
                  "PUR_TAX_TOTAL": 12800}

    def test_combined_reading_consistent_with_noncredit(self):
        result = self._combined(self.CONSISTENT)
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN")
        self.assertEqual(result["cases"]["NC-A-NP-8"]["result"], "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN")
        self.assertEqual(result["trial_balance_reference"]["TB_8471"]["observed_change"], "216600")

    def test_combined_reading_where_non_taxable_purchase_entered_taxable_purchases(self):
        result = self._combined(dict(self.CONSISTENT, PUR10_AMOUNT=110000))
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "TAX_SUMMARY_SHOWS_CREDIT")

    def test_combined_reading_with_unexplained_credit_is_undetermined(self):
        result = self._combined(dict(self.CONSISTENT, CREDITABLE_TAX=20000))
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "UNDETERMINED")

    def test_combined_reading_with_more_creditable_tax_base_than_the_controls_is_undetermined(self):
        result = self._combined(dict(self.CONSISTENT, PUR_TAX_TOTAL=14800))
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "UNDETERMINED")
        self.assertIn("課税仕入税額等合計", result["steps"]["after_all"]["undetermined"])

    def _a_only(self, after_a: dict, ratio="0.00"):
        """The 2026-11-07 reading: before and after importing file A only (B/C sheets left blank)."""
        sheet = self.root / "sequential.csv"
        judge.write_sheet(self.root, sheet)
        rows = list(csv.reader(io.StringIO(sheet.read_text(encoding="utf-8-sig"))))
        for row in rows[1:]:
            if row[0] == "RATIO":
                row[5] = ratio
            elif row[0] == "READING" and row[2] != "NONTAX_PURCHASE":  # the JDL report has no such field
                if row[1] == "before":
                    row[5] = "0"
                elif row[1] == "after_NONCREDIT_A":
                    row[5] = str(after_a.get(row[2], 0))
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        sheet.write_text("\ufeff" + buffer.getvalue(), encoding="utf-8")
        return judge.judge(self.root, self._real_report(), sheet)

    # Read from the JDL 消費税集計表 PDFs (before: empty; after A: the two controls only).
    A_ONLY = {"PUR10_AMOUNT": 11000, "PUR10_TAX": 1000, "PUR8_AMOUNT": 10800, "PUR8_TAX": 800,
              "CREDITABLE_TAX": 0, "PUR_TAX_TOTAL": 1800}

    def test_a_only_reading_from_the_real_reports(self):
        result = self._a_only(self.A_ONLY)
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN")
        self.assertEqual(result["cases"]["NC-A-NP-8"]["result"], "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN")
        self.assertEqual(result["cases"]["NC-A-OOS-10"]["result"], "NOT_ADOPTED_COMPARISON")
        step = result["steps"]["after_NONCREDIT_A"]
        self.assertFalse(step["credit_check_discriminating"])  # 0% ratio: the 一括比例 credit proves nothing
        self.assertTrue(step["cases"]["NC-A-NP-10"]["tax_total_consistent_with_control_only"])
        # files never imported in this reading keep the re-export facts
        self.assertEqual(result["cases"]["NC-B10-NP-R10"]["result"], "IMPORT_REJECTED")
        self.assertEqual(result["cases"]["NC-C10-P10-T0"]["result"], "TAX_RECOMPUTED_BY_JDL")

    def test_a_only_reading_where_non_taxable_purchase_counted_as_taxable(self):
        result = self._a_only(dict(self.A_ONLY, PUR10_AMOUNT=33000, PUR10_TAX=3000, PUR_TAX_TOTAL=3800))
        self.assertEqual(result["cases"]["NC-A-NP-10"]["result"], "TAX_SUMMARY_SHOWS_CREDIT")

    def test_a_only_signoff_is_read_from_the_sheet_and_never_assumed(self):
        result = self._a_only(self.A_ONLY)
        self.assertNotIn("EQUIVALENCE_CONFIRMED", {c["result"] for c in result["cases"].values()})


class EngineKeepsNoncreditBlockedTest(unittest.TestCase):
    """The technical facts from the re-export, enforced by the converter."""

    def test_noncredit_identities_have_no_candidate_and_say_why(self):
        from accounting_converter.application.noncredit_observations import NONCREDIT_REASON, is_noncredit_identity
        from accounting_converter.application.yayoi_review import candidate_semantic

        for identity in ("課対仕入10%｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜控除不可"):
            self.assertIsNone(candidate_semantic(identity))
            self.assertTrue(is_noncredit_identity(identity))
        self.assertFalse(is_noncredit_identity("課対仕入10%｜区分記載｜80%経過措置"))
        self.assertIn("取込拒否", NONCREDIT_REASON)
        self.assertIn("税理士確認", NONCREDIT_REASON)

    def test_non_taxable_purchase_is_written_without_a_tax_rate(self):
        # JDL rejected 非仕入 with 10% / 軽減8% ("借方税区が不正です").
        from accounting_converter.adapters.output.jdl.tax_semantics import JDL_TAX_LITERALS, JdlTaxSemantic

        literal = JDL_TAX_LITERALS[JdlTaxSemantic.NON_TAXABLE_PURCHASE]
        self.assertEqual((literal.scope, literal.category), ("非仕入", ""))

    def test_an_explicit_zero_tax_on_a_taxable_purchase_is_never_written(self):
        # JDL replaced a written 0 with the computed tax (55,000 -> 5,000; 54,000 -> 4,000).
        from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
        from accounting_converter.application import scoped_evidence_composition as composition

        for cell, amount in (("P10", 55000), ("R8", 54000), ("T80", 55000)):
            self.assertIsNone(scoped.relation_of(cell, Decimal(amount), Decimal(0)))
            gaps, _ = composition.line_gaps(composition.ScopedLine("DEBIT", "8471", cell, Decimal(amount), Decimal(0)))
            self.assertEqual(gaps, ["EXPLICIT_TAX_AMOUNT_UNVERIFIED"])

    def test_recomputed_tax_detection_ignores_known_normalizations_only(self):
        self.assertEqual(judge.recomputed_tax(REAL_RESULT["details"]["NC-C10-P10-T0"]["raw_differences"]), ("0", "5000"))
        self.assertIsNone(judge.recomputed_tax([{"column": "借方税区", "expected": "10%", "actual": ""}]))
        self.assertIsNone(judge.recomputed_tax([{"column": "借方消費税", "expected": "0", "actual": "5000"},
                                                {"column": "借方金額", "expected": "55000", "actual": "50000"}]))


STORE = Path("data/private/yayoi_store")
SOURCE = Path("data/private/yayoi_buddies/source.txt")


@unittest.skipUnless(STORE.exists() and SOURCE.exists(), "private data is not present")
class GenerateWithThePrivateStoreTest(unittest.TestCase):
    def test_files_are_cp932_crlf_without_bom_self_check_and_cannot_be_registered(self):
        from accounting_converter.tools.build_scoped_evidence_registry import collect_gap_round
        from accounting_converter.tools.yayoi_gap_probe_check import check_round

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "data" / "private" / "noncredit"
            result = nc.generate(STORE, "company-yayoi-buddies", SOURCE, "20260705", out)
            self.assertEqual(sum(m["expected_logical_journals"] for m in result.values()), 13)
            header, rows = None, []
            for path in sorted(out.glob("YAYOI_GAP_*.csv")):
                payload = path.read_bytes()
                self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))
                self.assertEqual(payload.count(b"\r\n"), payload.count(b"\n"))
                lines = payload.split(b"\r\n")
                header = lines[0]
                rows += [line for line in lines[1:] if line]
                payload.decode("cp932")
            reexport = out / "simulated.csv"
            reexport.write_bytes(b"\r\n".join([header, *rows]) + b"\r\n")
            report = check_round(out, reexport)
            self.assertTrue(report["round_valid"])
            self.assertEqual(report["verdict_totals"], {"PASS": 13})
            with self.assertRaisesRegex(ValueError, "may not be registered"):
                collect_gap_round(out, reexport)
            with self.assertRaisesRegex(Exception, "already exists"):
                nc.generate(STORE, "company-yayoi-buddies", SOURCE, "20260705", out)

    def test_a_day_with_source_journals_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Exception, "source journals"):
                nc.generate(STORE, "company-yayoi-buddies", SOURCE, "20260701",
                            Path(directory) / "data" / "private" / "x")


if __name__ == "__main__":
    unittest.main()

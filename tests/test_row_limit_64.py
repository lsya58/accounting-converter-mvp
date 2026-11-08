"""振替伝票入力行数 64: fail-closed until a real round is registered; then only what it proved. Synthetic data only.

What is proven here:
- 64 (or any other limit than 16) is VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED without registered Evidence: nothing is
  composed or written, and the 16-row Evidence is not used for it;
- once a 64 round is registered, its own layouts (17..64 rows) apply only under 64, the 16-row cases carry over to
  64, cases recorded under 64 never reach the 16 scope, and the limit itself is still enforced;
- the Probe tool's gate, registry block and dry-run forecast; the interim-closing judge never guesses a month.
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    JdlOutputPreflight,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.adapters.output.jdl.scoped_evidence_registry import RowLimitScopeEvidence, ScopedCase
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application import closing_entries, noncredit_approval, voucher_split
from accounting_converter.application import scoped_evidence_composition as composition
from accounting_converter.tools import yayoi_interim_closing_probe as interim
from accounting_converter.tools import yayoi_row64_probe as row64
from tests.test_scoped_evidence import context, journal, match, profile, sales_journal, side

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PROBE = ROOT / "data/private/yayoi_buddies/row64_probe_20261108"


def untaxed(rows: int):
    return journal([(side("1111", "NO", "1100"), side("3181", "NO", "1100"))] * rows)


def record(case_id, rows):
    return {"case_id": case_id, "evidence_id": f"EVID-TEST-{case_id}", "layout": row64.signature_layout(rows),
            "rows": rows, "taxed": ()}


B20 = record("L64-B20", (("NO", "NO"),) * 20)


def write_errors(entry, ctx):
    found = ev.evidence_for_occurrence(entry, entry, ctx, profile(ctx))
    literal = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
    literal.metadata[JDL_OUTPUT_METADATA_KEY] = (
        found.profile.value if found else JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL.value)
    return {r.rule_id for r in JdlOutputPreflight(ctx).evaluate((literal,), jdl_ibex_35_5_output_profile()).validation_results}


LIM = 40  # a hypothetical, UNREGISTERED row limit: used wherever the tests need an unverified or freshly registered one


def assumed(records, **kwargs):
    return row64.assumed_round(records, limit=LIM, **kwargs)


class UnverifiedSettingTest(unittest.TestCase):
    def test_an_unregistered_limit_is_blocked_and_uses_no_evidence(self):
        self.assertNotIn(LIM, scoped.verified_row_limits())
        self.assertIs(scoped.scope_state(context(limit=LIM)), scoped.ScopeState.VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED)
        self.assertEqual(scoped.cases_for(LIM), ())
        self.assertEqual(scoped.row_limit_evidence_ids(LIM), ())
        result = match(sales_journal(3), context(limit=LIM))  # covered under 16, NOT released under another limit
        self.assertIsNone(result.evidence)
        self.assertIn("VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED", result.mismatch_fields)
        self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT-SETTING", write_errors(sales_journal(3), context(limit=LIM)))
        self.assertTrue(scoped.semantic_evidence_applies(context(limit=LIM)))  # candidates shown, journals blocked

    def test_16_is_unchanged(self):
        self.assertIs(scoped.scope_state(context(limit=16)), scoped.ScopeState.IN_SCOPE)
        self.assertEqual(scoped.row_limit_evidence_ids(16), (scoped.VOUCHER_ROW_LIMIT_EVIDENCE_ID,))
        self.assertEqual(scoped.cases_for(16), tuple(c for c in scoped.SCOPED_CASES if c.row_limit_scope == 16))
        self.assertEqual(sum(c.row_limit_scope == 16 for c in scoped.SCOPED_CASES), 184)
        self.assertEqual(scoped.scope_id_for(16), scoped.SCOPE_ID)
        self.assertTrue(scoped.scope_id_for(64).endswith("-VOUCHER-ROWS-64"))
        self.assertTrue(scoped.carries(16, "CLOSING"))


class RegisteredSixtyFourTest(unittest.TestCase):
    """The real round 5 (2026-06-14) as registered: what 64 allows and what it still blocks."""

    def test_the_registered_scope(self):
        record = scoped.ROW_LIMIT_SCOPES[64]
        self.assertIn(64, scoped.verified_row_limits())
        self.assertEqual(record.counts, "LINES_PER_SIDE")  # SIDE-D and SIDE-C (65 physical rows) round-tripped
        self.assertEqual([c for c, _ in record.carried], ["LAYOUT", "TAX_RELATION", "SUBACCOUNT"])
        self.assertEqual(sum(c.row_limit_scope == 64 for c in scoped.SCOPED_CASES), 30)
        self.assertEqual(sum(c.row_limit_scope == 16 for c in scoped.SCOPED_CASES), 184)
        self.assertIs(scoped.scope_state(context(limit=64)), scoped.ScopeState.IN_SCOPE)

    def test_lines_per_side_are_counted_not_csv_rows(self):
        one_credit = journal([(None, side("3181", "NO", str(1100 * 64)))] + [(side("1111", "NO", "1100"), None)] * 64)
        rows = composition.journal_physical_rows(one_credit)
        self.assertEqual(len(rows), 65)
        self.assertFalse(scoped.exceeds_row_limit(rows, 64))
        self.assertEqual(voucher_split.ineligible_reason(one_credit, 64), "WITHIN_LIMIT")
        self.assertTrue(scoped.exceeds_row_limit(composition.journal_physical_rows(
            journal([(None, side("3181", "NO", str(1100 * 65)))] + [(side("1111", "NO", "1100"), None)] * 65)), 64))
        self.assertTrue(scoped.exceeds_row_limit(rows, 16))  # unchanged under 16

    def test_unobserved_layouts_and_over_limit_vouchers_stay_blocked(self):
        entry = journal([(side("1111", "NO", "1100"), side("3181", "NO", "1100"))] * 20)  # B20: never round-tripped
        self.assertIn("VOUCHER_LAYOUT_UNVERIFIED", match(entry, context(limit=64)).mismatch_fields)
        over = journal([(None, side("3181", "NO", str(1100 * 65)))] + [(side("1111", "NO", "1100"), None)] * 65)
        self.assertIn("VOUCHER_ROW_LIMIT_EXCEEDED", match(over, context(limit=64)).mismatch_fields)
        self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT", write_errors(over, context(limit=64)))

    def test_unverified_conditions_stay_blocked(self):
        self.assertFalse(scoped.carries(64, "CLOSING"))  # no 64-row closing Probe yet
        self.assertFalse(closing_entries._scope_ok(context(limit=64)))
        self.assertTrue(closing_entries._scope_ok(context(limit=16)))
        self.assertFalse(noncredit_approval._context_in_scope(context(limit=64)))  # 控除不可: never carried
        self.assertTrue(noncredit_approval._context_in_scope(context(limit=16)))
        self.assertTrue(scoped.carries(64, "LAYOUT") and scoped.carries(64, "TAX_RELATION") and scoped.carries(64, "SUBACCOUNT"))

    def test_64_cases_never_reach_the_16_scope(self):
        long_layouts = [c.layout for c in scoped.SCOPED_CASES if c.row_limit_scope == 64 and len(c.rows) > 16]
        self.assertTrue(long_layouts)
        for layout in long_layouts:
            self.assertNotIn(layout, scoped.views(16)[0])
        self.assertIn("VOUCHER_ROW_LIMIT_EXCEEDED", match(untaxed(20), context(limit=16)).mismatch_fields)
        self.assertEqual(scoped.cases_for(16), tuple(c for c in scoped.SCOPED_CASES if c.row_limit_scope == 16))


class VerifiedRoundTest(unittest.TestCase):
    """A freshly registered limit (the hypothetical LIM): the same rules as the real 64, on synthetic data."""

    def test_registered_round_releases_only_what_it_proved(self):
        b20 = record("L64-B20", (("NO", "NO"),) * 20)
        with assumed([b20]):
            self.assertIs(scoped.scope_state(context(limit=LIM)), scoped.ScopeState.IN_SCOPE)
            released = match(untaxed(20), context(limit=LIM))
            self.assertIsNotNone(released.evidence, released.mismatch_fields)
            self.assertIn("FORECAST:LIMIT", released.evidence.supporting_evidence_ids)
            self.assertEqual(write_errors(untaxed(20), context(limit=LIM)), set())
            carried = match(sales_journal(3), context(limit=LIM))
            self.assertIsNotNone(carried.evidence, carried.mismatch_fields)
            self.assertIn("FORECAST:CARRY-LAYOUT", carried.evidence.supporting_evidence_ids)
            self.assertNotIn(scoped.VOUCHER_ROW_LIMIT_EVIDENCE_ID, carried.evidence.supporting_evidence_ids)
            self.assertIn("VOUCHER_LAYOUT_UNVERIFIED", match(untaxed(21), context(limit=LIM)).mismatch_fields)
            self.assertIn("VOUCHER_ROW_LIMIT_EXCEEDED", match(untaxed(LIM + 1), context(limit=LIM)).mismatch_fields)
            self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT", write_errors(untaxed(LIM + 1), context(limit=LIM)))
            self.assertNotIn("B20", scoped.views(16)[0])
        self.assertIs(scoped.scope_state(context(limit=LIM)), scoped.ScopeState.VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED)
        self.assertIsNone(match(untaxed(20), context(limit=LIM)).evidence)

    def test_a_short_case_recorded_under_the_limit_is_not_16_evidence(self):
        short = record("L64-B9", (("NO", "NO"),) * 9)
        before = scoped.views(16)[1].get("B9", ())
        with assumed([short]):
            self.assertEqual(scoped.views(16)[1].get("B9", ()), before)
            self.assertIn("FORECAST:EVID-TEST-L64-B9", scoped.views(LIM)[1]["B9"])

    def test_counting_rules(self):
        one_credit = journal([(None, side("3181", "NO", str(1100 * LIM)))] + [(side("1111", "NO", "1100"), None)] * LIM)
        rows = composition.journal_physical_rows(one_credit)  # LIM + 1 physical rows, LIM debit lines
        with assumed([]):  # physical-row counting (the safe default)
            self.assertTrue(scoped.exceeds_row_limit(rows, LIM))
            self.assertIsNone(voucher_split.ineligible_reason(one_credit, LIM))  # so it is a split candidate
        with assumed([], counts="LINES_PER_SIDE"):
            self.assertEqual(scoped.counted_rows(rows, LIM), LIM)
            self.assertFalse(scoped.exceeds_row_limit(rows, LIM))
            self.assertEqual(voucher_split.ineligible_reason(one_credit, LIM), "WITHIN_LIMIT")
            self.assertTrue(scoped.exceeds_row_limit(rows + rows[-1:], LIM))
        old = scoped.ROW_LIMIT_SCOPES
        try:
            scoped.ROW_LIMIT_SCOPES = {LIM: RowLimitScopeEvidence(LIM, "X", counts="GUESSED")}
            scoped.reset_views()
            self.assertNotIn(LIM, scoped.verified_row_limits())
        finally:
            scoped.ROW_LIMIT_SCOPES = old
            scoped.reset_views()
            composition.reset_capabilities()

    def test_each_16_row_category_carries_only_with_its_control(self):
        company_rounding = journal([(side("1111", "NO", "1000"), side("6121", "S10", "1000", "91"))])
        self.assertIsNotNone(match(company_rounding, context(limit=16)).evidence)
        with assumed([], carried=("LAYOUT", "SUBACCOUNT", "CLOSING")):
            gaps = match(company_rounding, context(limit=LIM)).mismatch_fields
            self.assertIn("EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED", gaps)
            self.assertIsNotNone(match(sales_journal(3), context(limit=LIM)).evidence)  # no fraction: layout only
        with assumed([], carried=("TAX_RELATION", "SUBACCOUNT", "CLOSING")):
            self.assertIsNone(match(sales_journal(3), context(limit=LIM)).evidence)  # no layout carry-over
        with assumed([], carried=("LAYOUT", "TAX_RELATION", "CLOSING")):
            self.assertFalse(scoped.carries(LIM, "SUBACCOUNT"))
            entry = sales_journal(3)
            literal = ev.apply_verified_tax_semantics(entry, entry, context(limit=LIM), profile(context(limit=LIM)))
            literal.lines[0].sub_account = "テスト補助"
            literal.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL.value
            errors = {r.rule_id for r in JdlOutputPreflight(context(limit=LIM)).evaluate(
                (literal,), jdl_ibex_35_5_output_profile()).validation_results}
            self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT-SUBACCOUNT", errors)
        with assumed([]):
            self.assertFalse(noncredit_approval._context_in_scope(context(limit=LIM)))  # never carried
        with assumed([], carried=("LAYOUT",)):
            self.assertFalse(closing_entries._scope_ok(context(limit=LIM)))
        with assumed([], carried=("LAYOUT", "CLOSING")):
            self.assertTrue(closing_entries._scope_ok(context(limit=LIM)))


class ProbeToolTest(unittest.TestCase):
    def test_inv_case_is_long_and_carries_every_registered_row_pair(self):
        signature = row64.inv_signature()
        self.assertGreater(len(signature), 16)
        self.assertEqual(set(signature), set(scoped.views(16)[2]))
        cells = {(s, c) for d, cr in signature for s, c in (("DEBIT", d), ("CREDIT", cr)) if c not in {"NO", "-"}}
        self.assertEqual(cells, {c for v in scoped.views(16)[0].values() for c in v})

    def test_rel_lines_cover_every_registered_rounding_relation(self):
        registered = {(s, c, r) for (s, c, r) in scoped.views(16)[4] if r not in {"", "NONE", "EXACT"}}
        self.assertEqual({(s, c, r) for s, c, _a, _m, _t, r in row64.REL_LINES}, registered)
        for side_, cell, account, _m, _t, relation in row64.REL_LINES:
            self.assertIn(account, scoped.views(16)[4][(side_, cell, relation)])

    def test_layout_of_a_signature(self):
        self.assertEqual(row64.signature_layout((("-", "NO"),) + (("P10", "-"),) * 64), "C1D64")
        self.assertEqual(row64.signature_layout((("NO", "NO"), ("-", "NO"), ("P10", "-"))), "B1C1D1")

    def test_registry_block_is_valid_code_scoped_to_64(self):
        text = row64.render_registry_block([B20], {"reexport_journals": 1, "reexport_rows": 20}, "PHYSICAL_ROWS",
                                           {"LAYOUT": True, "TAX_RELATION": False, "SUBACCOUNT": True, "CLOSING": True})
        namespace = {"SCOPED_CASES": (), "ROW_LIMIT_SCOPES": {}, "ScopedCase": ScopedCase,
                     "RowLimitScopeEvidence": RowLimitScopeEvidence}
        exec(text, namespace)  # noqa: S102 (generated by the tool itself)
        (case,) = namespace["SCOPED_CASES"]
        self.assertEqual((case.layout, case.row_limit_scope), ("B20", 64))
        scope = namespace["ROW_LIMIT_SCOPES"][64]
        self.assertEqual(scope.limit_evidence_id, row64.LIMIT_EVIDENCE_ID)
        self.assertEqual([c for c, _ in scope.carried], ["LAYOUT", "SUBACCOUNT", "CLOSING"])

    @unittest.skipUnless(PRIVATE_PROBE.exists(), "private 64-row Probe not generated here")
    def test_gate_with_simulated_reexports(self):
        def body(path):
            return [r for r in path.read_bytes().decode("cp932").split("\r\n")[1:] if r]

        def file(name, folder=PRIVATE_PROBE):
            return next(folder.glob(f"YAYOI_GAP_{name}_*_NOT_FOR_PRODUCTION.csv"))

        names = [p.name.split("_")[2] for p in PRIVATE_PROBE.glob("YAYOI_GAP_R64*_NOT_FOR_PRODUCTION.csv")]
        header = file("R64A").read_bytes().decode("cp932").split("\r\n")[0]
        controls_only = lambda name: body(file(name))[:1]  # noqa: E731 (a rejected voucher, its control imported)
        main = [n for n in names if n not in row64.BOUNDARY_FILES]
        ok = [r for n in main for r in body(file(n))] + [r for n in row64.BOUNDARY_FILES for r in controls_only(n)]
        results = {n: {"message": row64.REJECTION_HINT} for n in row64.BOUNDARY_FILES}
        with tempfile.TemporaryDirectory() as directory:
            def run(rows, res=results):
                path = Path(directory) / "reexport.csv"
                path.write_bytes(("\r\n".join([header, *rows]) + "\r\n").encode("cp932"))
                return row64.check(PRIVATE_PROBE, path, res)

            passed = run(ok)
            self.assertTrue(passed["row_limit_64_verified"], passed["gate"])
            self.assertEqual(passed["counts"], "PHYSICAL_ROWS")
            self.assertEqual(passed["carried"], {"LAYOUT": True, "TAX_RELATION": True, "SUBACCOUNT": True, "CLOSING": False})
            self.assertIn("row_limit_scope=64", passed["registry"])
            self.assertEqual(passed["not_judged"], [])
            # a group file rejected: its cases come from the fallback files, nothing is lost
            fallback = PRIVATE_PROBE / row64.FALLBACK_DIR
            singles = [r for p in sorted(fallback.glob("YAYOI_GAP_*.csv"))
                       if json.loads(Path(str(p) + ".manifest.json").read_text(encoding="utf-8"))["fallback_for"] == "R64L5"
                       for r in body(p)]
            via_fallback = run([r for r in ok if r not in body(file("R64L5"))] + singles)
            self.assertTrue(via_fallback["row_limit_64_verified"])
            self.assertEqual(via_fallback["not_judged"], [])
            self.assertEqual(via_fallback["verdicts"]["L64-C1D54"], "PASS")
            # both SIDE vouchers imported: lines per side are counted
            sides = run(ok + [r for n in ("R64SIDED", "R64SIDEC") for r in body(file(n))[1:]])
            self.assertEqual(sides["counts"], "LINES_PER_SIDE")
            self.assertIn("L64-SIDE-D", [r["case_id"] for r in sides["registry_records"]])
            # one side over the limit imported, or its rejection not recorded: 64 not verified
            self.assertFalse(run(ok + body(file("R64OVERC"))[1:])["row_limit_64_verified"])
            self.assertFalse(run(ok, {**results, "R64OVERD": {"message": ""}})["row_limit_64_verified"])
            # INV lost: verified, but the 16-row layouts are not carried
            no_inv = run([r for r in ok if ",L64-INV-R" not in r])
            self.assertFalse(no_inv["carried"]["LAYOUT"])
            self.assertIn("L64-INV", no_inv["not_judged"])


def jdl_csv(path: Path, entries) -> Path:
    """entries: [(date text, 摘要)] -> one 2-row 対象外 voucher each (30 columns, cp932)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["//識別フラグ"] + [""] * 29)
    for day, marker in entries:
        for flag, n in (("1110", 1), ("1101", 2)):
            row = [""] * 30
            row[0], row[2], row[3], row[11], row[13], row[21], row[23] = flag, day, "1111", "1100", "3181", "1100", f"{marker}-R{n}"
            writer.writerow(row)
    path.write_bytes(buffer.getvalue().encode("cp932"))
    return path


class InterimClosingTest(unittest.TestCase):
    def judge(self, interim_date, screen=None):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            with_ = jdl_csv(d / "with.csv", [("20260131", interim.NORMAL), (interim_date, interim.INTERIM)])
            without = jdl_csv(d / "without.csv", [("20260131", interim.NORMAL)])
            return interim.judge_export(with_, without, screen or {}, "20260131", "20260731")

    def test_the_date_jdl_writes_is_observed_never_assumed(self):
        found = self.judge("20261431")
        self.assertEqual(found["result"], "INTERIM_MARK_FOUND_IMPORT_UNVERIFIED")
        self.assertEqual(found["interim_date_text"], ["20261431"])
        self.assertEqual(self.judge("20261331")["result"], "INTERIM_SAME_AS_YEAR_END_CLOSING")
        self.assertEqual(self.judge("20260131")["result"], "CSV_CANNOT_CARRY_CLOSING")
        self.assertEqual(self.judge("20261431", {"entry_screen_offers_interim_closing": False})["result"],
                         "INTERIM_NOT_ENTERABLE")

    def test_no_import_probe_without_a_usable_mark(self):
        with self.assertRaises(SystemExit):
            interim.generate_import(Path("x"), Path("y"), "c", "20260131", {"result": "INTERIM_SAME_AS_YEAR_END_CLOSING"},
                                    Path("data/private/x"))


if __name__ == "__main__":
    unittest.main()

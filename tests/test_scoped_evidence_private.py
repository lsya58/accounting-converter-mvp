"""Registered Evidence vs the REAL probe files and JDL re-exports (skipped when data/private is absent).

For every registered case the production output stage (scoped profile) must
write exactly the rows that PASSED a real JDL Import and re-export; the table
in scoped_evidence_registry.py must equal the table regenerated from those
files; and the rejected 17/25/50/73-row probe must stay refused. Prints nothing
about customer values.
"""
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    JdlOutputPreflight,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.scoped_evidence_registry import SCOPED_CASES
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, LINE_ROW_KEY, ROW_ORDER_KEY
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows
from accounting_converter.tools.yayoi_probe_check import manifest_path_for

STORE = Path("data/private/yayoi_store")
CAMPAIGN = Path("data/private/yayoi_buddies/evidence_campaign_20261105")
PENDING = Path("data/private/yayoi_buddies/evidence_pending_20261104")
GAP = Path("data/private/yayoi_buddies/evidence_gap_20261106")
PROBES = (
    PENDING / "BUDDIES_3D3C_4D4C_SALES10_NOT_FOR_PRODUCTION.csv",
    CAMPAIGN / "YAYOI_EVIDENCE_CAMPAIGN_A1_20260628_NOT_FOR_PRODUCTION.csv",
    CAMPAIGN / "YAYOI_EVIDENCE_CAMPAIGN_A2_20260628_NOT_FOR_PRODUCTION.csv",
    CAMPAIGN / "YAYOI_EVIDENCE_CAMPAIGN_A3_20260628_ROWS16_NOT_FOR_PRODUCTION.csv",
    CAMPAIGN / "YAYOI_EVIDENCE_CAMPAIGN_B_20260627_NOT_FOR_PRODUCTION.csv",
    *(GAP / f"YAYOI_GAP_{name}_20260621_NOT_FOR_PRODUCTION.csv" for name in ("G1a", "G1b", "G1c", "G2", "G3")),
)
GAP_REEXPORT = GAP / "reexport_20260621.csv"
NEW_ACCOUNTS = Path("data/private/yayoi_buddies/new_account_evidence_20261106_rev3")
NEW_ACCOUNTS_PROBE = NEW_ACCOUNTS / "YAYOI_GAP_NEW_ACCOUNT_12_20260726_NOT_FOR_PRODUCTION.csv"
NEW_ACCOUNTS_REEXPORT = NEW_ACCOUNTS / "YAYOI_NEW_ACCOUNT_12_REEXPORT_20260726.csv"
MASTER_PDF = Path("data/private/yayoi_buddies/バディーズ科目一覧-科目追加後.pdf")
SUBTAX = Path("data/private/yayoi_buddies/subaccount_tax_evidence_20261107")
SUBTAX_REEXPORT = SUBTAX / "yayoi補助再エクスポート.csv"
SUBTAX_PROBES = tuple(SUBTAX / f"YAYOI_GAP_SUBTAX_{name}_20260719_NOT_FOR_PRODUCTION.csv"
                      for name in ("TAX15", "STRUCT6"))
PROBES = (*PROBES, NEW_ACCOUNTS_PROBE, *SUBTAX_PROBES)
REF = SourceReference("private", 1)
AVAILABLE = (STORE.exists() and GAP_REEXPORT.exists() and NEW_ACCOUNTS_REEXPORT.exists() and SUBTAX_REEXPORT.exists()
             and all(path.exists() for path in PROBES))


def _tax(row, scope, category, method, tax):
    if not (row[scope] or row[category] or row[method] or row[tax]):
        return None
    return TaxInfo(category=row[category], tax_amount=Decimal(row[tax]) if row[tax] else None,
                   metadata={"jdl_tax_scope": row[scope], "jdl_tax_input_method": row[method]})


def entry_from_probe_rows(group, names) -> JournalEntry:
    lines = []
    for number, row in enumerate(group, start=1):
        meta = {LINE_ROW_KEY: number, LINE_ROW_DESCRIPTION_KEY: row[23]}
        if row[3]:
            lines.append(JournalLine(Side.DEBIT, names[row[3]], Decimal(row[11]), REF,
                                     tax_info=_tax(row, 8, 9, 10, 12), metadata=dict(meta)))
        if row[13]:
            lines.append(JournalLine(Side.CREDIT, names[row[13]], Decimal(row[21]), REF,
                                     tax_info=_tax(row, 18, 19, 20, 22), metadata=dict(meta)))
    day = group[0][2]
    return JournalEntry("j", REF, date(int(day[:4]), int(day[4:6]), int(day[6:])), lines, metadata={
        ROW_ORDER_KEY: tuple(range(1, len(group) + 1)),
        JDL_OUTPUT_METADATA_KEY: JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL.value,
    })


@unittest.skipUnless(AVAILABLE, "private probe files are not present")
class RegisteredEvidenceMatchesTheRealProbesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profiles = ConversionProfileStore(STORE / "profiles")
        context = CompanySettingStore(STORE / "companies", profiles).resolve("company-yayoi-buddies").context
        # The stored test master predates the accounts added in JDL on 2026-11-06; add exactly the identities
        # the new-account probe sent to JDL (code, 略名称, 正式名称) so the output stage can be checked on them.
        from accounting_converter.adapters.output.jdl import JdlAccountIdentity

        known = {item.target_master_code for item in context.account_master}
        added = {}
        for row in _rows(NEW_ACCOUNTS_PROBE):
            for code, short, formal in ((row[3], row[4], row[5]), (row[13], row[14], row[15])):
                if code and code not in known:
                    added[code] = JdlAccountIdentity(formal, code, short, formal)
        cls.context = replace(context, voucher_row_limit=16,
                              account_master=context.account_master + tuple(added.values()),
                              accounts=frozenset(context.accounts) | {item.mapping_value for item in added.values()})
        cls.names = {item.target_master_code: item.mapping_value for item in cls.context.account_master}

    def test_the_production_output_stage_writes_the_rows_that_round_tripped(self):
        checked = 0
        registered = {case.case_id for case in SCOPED_CASES}
        for probe in PROBES:
            manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
            groups = _groups(_rows(probe))
            for case in manifest["cases"]:
                if case["case"] not in registered:
                    continue
                group = groups[case["journal_index"]]
                result = JdlOutputPreflight(self.context).evaluate(
                    [entry_from_probe_rows(group, self.names)], jdl_ibex_35_5_output_profile())
                with self.subTest(case=case["case"]):
                    self.assertEqual([v.rule_id for v in result.validation_results], [])
                    self.assertEqual([list(row.columns()) for row in result.plan.rows], [r[:30] for r in group])
                checked += 1
        self.assertEqual(checked, len(SCOPED_CASES))

    def test_registry_equals_the_table_regenerated_from_the_real_files(self):
        from accounting_converter.tools.build_scoped_evidence_registry import collect, collect_gap_round

        cases, _summary = collect(CAMPAIGN, PENDING)
        gap_cases, _gap_summary = collect_gap_round(GAP, GAP_REEXPORT)
        cases += gap_cases
        new_cases, _new_summary = collect_gap_round(NEW_ACCOUNTS, NEW_ACCOUNTS_REEXPORT)
        cases += new_cases
        subtax_cases, _subtax_summary = collect_gap_round(SUBTAX, SUBTAX_REEXPORT)
        cases += subtax_cases
        self.assertEqual(
            [(c["case_id"], c["evidence_id"], c["layout"], c["rows"], c["taxed"]) for c in cases],
            [(c.case_id, c.evidence_id, c.layout, c.rows, c.taxed) for c in SCOPED_CASES])

    def test_subtax_round_keeps_failures_out_of_positive_registry(self):
        from collections import Counter
        from accounting_converter.tools.yayoi_gap_probe_check import check_round

        report = check_round(SUBTAX, SUBTAX_REEXPORT)
        self.assertTrue(report["round_valid"])
        self.assertEqual((report["expected_journals"], report["expected_rows"]), (35, 51))
        self.assertEqual((report["reexport_journals"], report["reexport_rows"]), (30, 46))
        expected = {
            "TAX15": {"PASS": 16}, "STRUCT6": {"PASS": 7},
            "SUB_KEEP": {"PASS": 3, "CHANGED": 1},
            "SUB_NAMEONLY": {"PASS": 1, "CHANGED": 2},
            "SUB_BLANK": {"MISSING": 2}, "SUB_0000": {"MISSING": 3},
        }
        for filename, result in report["files"].items():
            kind = next(key for key in expected if f"_{key}_" in filename)
            self.assertEqual(dict(Counter(result["verdicts"].values())), expected[kind])
        registered = {case.case_id for case in SCOPED_CASES}
        self.assertFalse(any(case.startswith(("SK-", "SB-", "SZ-", "SN-")) for case in registered))

    def test_setting_peers_equal_the_table_regenerated_from_the_master_pdf(self):
        try:
            import pypdf  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("pypdf is not installed")
        from accounting_converter.adapters.output.jdl.scoped_evidence_registry import JDL_TAX_SETTING_PEERS
        from accounting_converter.tools.build_scoped_evidence_registry import setting_peers, tax_setting_keys

        cases = [{"taxed": case.taxed} for case in SCOPED_CASES]
        self.assertEqual(setting_peers(cases, tax_setting_keys(MASTER_PDF)), JDL_TAX_SETTING_PEERS)

    def test_descriptions_follow_the_real_64_byte_result(self):
        """G4 (kept by JDL) is written unchanged; G5 (JDL truncated it silently to 64 bytes) is refused."""
        for name, kept in (("G4", True), ("G5", False)):
            probe = GAP / f"YAYOI_GAP_{name}_20260621_NOT_FOR_PRODUCTION.csv"
            manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
            groups = _groups(_rows(probe))
            for case in manifest["cases"]:
                if not case["description_under_test"]:
                    continue
                group = groups[case["journal_index"]]
                result = JdlOutputPreflight(self.context).evaluate(
                    [entry_from_probe_rows(group, self.names)], jdl_ibex_35_5_output_profile())
                with self.subTest(case=case["case"]):
                    if kept:
                        self.assertEqual([v.rule_id for v in result.validation_results], [])
                        self.assertEqual([list(row.columns()) for row in result.plan.rows], [r[:30] for r in group])
                    else:
                        self.assertIsNone(result.plan)
                        self.assertIn("JDL-OUT-DESCRIPTION-LENGTH", {v.rule_id for v in result.validation_results})

    def test_the_rejected_over_limit_probe_is_refused_by_the_output_stage(self):
        probe = CAMPAIGN / "YAYOI_EVIDENCE_CAMPAIGN_A4_20260628_OVER16_NOT_FOR_PRODUCTION.csv"
        if not probe.exists():
            self.skipTest("A4 probe not present")
        manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
        groups = _groups(_rows(probe))
        for case in manifest["cases"]:
            with self.subTest(case=case["case"]):
                result = JdlOutputPreflight(self.context).evaluate(
                    [entry_from_probe_rows(groups[case["journal_index"]], self.names)], jdl_ibex_35_5_output_profile())
                self.assertIsNone(result.plan)
                self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT", {v.rule_id for v in result.validation_results})


if __name__ == "__main__":
    unittest.main()

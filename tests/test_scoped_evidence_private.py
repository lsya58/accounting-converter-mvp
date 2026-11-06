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
REF = SourceReference("private", 1)
AVAILABLE = STORE.exists() and GAP_REEXPORT.exists() and all(path.exists() for path in PROBES)


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
        cls.context = replace(context, voucher_row_limit=16)
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
        self.assertEqual(
            [(c["case_id"], c["evidence_id"], c["layout"], c["rows"], c["taxed"]) for c in cases],
            [(c.case_id, c.evidence_id, c.layout, c.rows, c.taxed) for c in SCOPED_CASES])

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

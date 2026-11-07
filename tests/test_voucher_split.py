"""Human-approved split of an over-limit Yayoi voucher into JDL vouchers. Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.application import voucher_split as vs
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJournalReportJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.domain.journal_rows import journal_physical_rows
from tests.test_yayoi_jdl_workflow import OUTSIDE, PURCHASE, YAYOI
from tests.test_yayoi_journal_report_parser import detail
from tests.test_yayoi_scoped_workflow import DATE, assess, make

COMPANY = "company-yayoi"


def card_voucher(debits: int, *, first_row_shared=False, amount=1100, voucher=1, closing=""):
    """未払金-like counterpart (現金Y, 対象外) on the first row; one 課税仕入10% debit per row."""
    total = amount * debits
    rows = []
    counterpart = (YAYOI["cash"], "", OUTSIDE, total, None)
    debit = lambda k: (YAYOI["fee"], "", PURCHASE, amount, amount // 11)  # noqa: E731
    if first_row_shared:
        rows.append(detail(DATE, voucher, debit=debit(1), credit=counterpart, invoice="適格", credit_ratio="100%",
                           description="明細1", number=voucher, closing=closing))
        start = 2
    else:
        rows.append(detail(DATE, voucher, credit=counterpart, description="カード利用分", number=voucher, closing=closing))
        start = 1
    for k in range(start, debits + 1):
        rows.append(detail(DATE, voucher, debit=debit(k), invoice="適格", credit_ratio="100%",
                           description=f"明細{k}", number=voucher, closing=closing))
    return rows


def approve(fixture, **overrides):
    resolved = fixture.resolved()
    kwargs = dict(human_approver="担当者A", tax_accountant="税理士B", signoff_reference="分割の確認書 No.1",
                  signoff_date=date(2026, 11, 7))
    kwargs.update(overrides)
    vs.approve_split_policy(fixture.profiles, resolved.profile.profile_id, COMPANY, resolved.context, **kwargs)
    fixture._rebind()


class PlanTest(unittest.TestCase):
    def _entry(self, directory, rows):
        return make(directory, rows).entries[0]

    def test_balanced_fewest_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = self._entry(directory, card_voucher(39))
            plan = vs.plan_split(entry, 16)
            self.assertEqual([len(p) for p in plan.parts], [13, 13, 13])
        with tempfile.TemporaryDirectory() as directory:
            entry = self._entry(directory, card_voucher(31, first_row_shared=True))
            plan = vs.plan_split(entry, 16)
            self.assertEqual([len(p) for p in plan.parts], [11, 10, 10])

    def test_parts_rebuild_the_original_and_keep_every_line(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = self._entry(directory, card_voucher(31, first_row_shared=True))
            plan = vs.plan_split(entry, 16)
            parts = vs.split_entry(entry, plan)
            self.assertEqual(vs.reconstruction_problems(entry, parts, plan, 16), [])
            self.assertEqual([vs_layout(p) for p in parts], ["B1D10", "C1D10", "C1D10"])
            self.assertEqual(sum(p.credit_total() for p in parts), entry.credit_total())
            for part in parts:
                self.assertEqual(part.debit_total(), part.credit_total())
                self.assertEqual(part.metadata[vs.SPLIT_OF_KEY], entry.id)
            # a changed line is detected
            broken = replace(parts[1], lines=[replace(l, amount=l.amount + 1) if l.side.value == "DEBIT" and i == 1 else l
                                              for i, l in enumerate(parts[1].lines)])
            self.assertIn("LINES_NOT_PRESERVED_EXACTLY_ONCE",
                          vs.reconstruction_problems(entry, (parts[0], broken, parts[2]), plan))

    def test_only_the_single_untaxed_counterpart_shape_qualifies(self):
        cases = {
            "WITHIN_LIMIT": card_voucher(15),
            "CLOSING_ENTRY": card_voucher(20, closing="本決"),
        }
        two_sided = card_voucher(20)
        two_sided.append(detail(DATE, 1, credit=(YAYOI["sales"], "", OUTSIDE, 1, None), description="x", number=1))
        two_sided[0] = detail(DATE, 1, credit=(YAYOI["cash"], "", OUTSIDE, 1100 * 20 - 1, None), description="カード利用分", number=1)
        cases["MORE_THAN_ONE_LINE_ON_BOTH_SIDES"] = two_sided
        taxed = card_voucher(20)
        taxed[0] = detail(DATE, 1, credit=(YAYOI["sales"], "", "課税売上内10%", 22000, 2000), description="x", number=1)
        cases["COUNTERPART_TAXED"] = taxed
        for reason, rows in cases.items():
            with self.subTest(reason), tempfile.TemporaryDirectory() as directory:
                self.assertEqual(vs.ineligible_reason(self._entry(directory, rows), 16), reason)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(vs.ineligible_reason(self._entry(directory, card_voucher(20)), None), "ROW_LIMIT_UNCONFIRMED")


def vs_layout(entry):
    from accounting_converter.adapters.output.jdl import scoped_evidence

    return scoped_evidence.layout_of(journal_physical_rows(entry))


class WorkflowTest(unittest.TestCase):
    def test_without_approval_the_journal_stays_blocked(self):
        # Parts verified (C1D13 x2): only the Human's recorded approval is missing, and that is what is reported.
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(26))
            assessment, resolved = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {vs.APPROVAL_BLOCKER: 1})
            self.assertEqual(assessment.ready_journals, 0)
            self.assertEqual(len(vs.apply_split(fixture.entries, resolved.profile, resolved.context)), 1)  # conversion path
            workflow = YayoiJournalReportJdlWorkflow()
            prepared = workflow.prepare(input_path=fixture.source, output_path=Path(directory) / "x.csv",
                                        profile=resolved.profile, context=resolved.context, company_setting_validated=True)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            self.assertTrue(any("税理士確認" in reason for reason in prepared.summary.blocking_reasons))

    def test_approval_needs_the_signoff_and_the_same_row_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(26))
            for override in (dict(signoff_reference=""), dict(tax_accountant=" "), dict(signoff_date=None)):
                with self.subTest(override), self.assertRaises(ValueError):
                    approve(fixture, **override)
            approve(fixture)
            from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService

            CompanyVoucherRowLimitService(fixture.companies, fixture.profiles).set(COMPANY, 20, confirmed=True)
            resolved = fixture.resolved()
            self.assertIn("ROW_LIMIT_DIFFERS_FROM_APPROVAL", vs.policy_problems(resolved.profile, resolved.context))
            self.assertEqual(len(vs.apply_split(fixture.entries, resolved.profile, resolved.context)), 1)

    def test_approved_split_converts_as_verified_vouchers_with_an_audit_record(self):
        # C1D26 -> C1D13 x2: a layout that round-tripped with 課税仕入10% debits.
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(26))
            approve(fixture)
            assessment, resolved = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {})
            self.assertEqual((assessment.ready_journals, assessment.entry_count), (1, 1))
            workflow = YayoiJournalReportJdlWorkflow()
            output = Path(directory) / "out" / "jdl.csv"
            output.parent.mkdir()
            prepared = workflow.prepare(input_path=fixture.source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=resolved.available)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            data = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
            self.assertEqual(len(data), 28)
            self.assertEqual([r[0] for r in data].count("1110"), 2)  # two vouchers
            credits = [r for r in data if r[13]]
            self.assertEqual([(r[13], r[21], r[23]) for r in credits],
                             [("1111", "14300", "カード利用分"), ("1111", "14300", "カード利用分")])
            self.assertEqual(sorted(r[23] for r in data if r[3]), sorted(f"明細{k}" for k in range(1, 27)))
            audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
            self.assertEqual(audit["voucher_split_journal_count"], 1)
            split = audit["journals"][0]["voucher_split"]
            self.assertEqual(split["reconstruction"], "PASS")
            self.assertEqual([p["counterpart_amount"] for p in split["parts"]], ["14300", "14300"])
            self.assertEqual(split["counterpart"]["amount"], "28600")
            self.assertEqual(split["tax_accountant_signoff_reference"], "分割の確認書 No.1")
            self.assertEqual(verify_non_retained_audit(fixture.source, output, resolved.profile, resolved.context)["verdict"], "PASS")
            # without the context the expected split is not known: the check fails instead of passing silently
            self.assertEqual(verify_non_retained_audit(fixture.source, output, resolved.profile)["verdict"], "FAIL")

    def test_an_unverified_part_blocks_the_original_journal(self):
        # B1D26 -> B1D13 + C1D13: B1D13 never round-tripped.
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(27, first_row_shared=True))
            before, _ = assess(fixture)  # not approved: still over the limit, with the part's gap shown
            self.assertIn("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", before.blocker_counts())
            self.assertNotIn(vs.APPROVAL_BLOCKER, before.blocker_counts())
            approve(fixture)
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.ready_journals, 0)
            self.assertIn("SYSTEM_EVIDENCE:VOUCHER_LAYOUT_UNVERIFIED", assessment.blocker_counts())
            self.assertEqual(list(assessment.journal_blockers), [fixture.entries[0].id])  # reported per source journal

    def test_round4_layouts_are_registered(self):
        # 2026-11-07 round 4: the split parts C1D14 (課税仕入10% + 軽減8%) now round-tripped.
        from accounting_converter.adapters.output.jdl import scoped_evidence as scoped

        for layout, cell in (("C1D9", "P10"), ("C1D10", "R8"), ("C1D11", "R8"), ("C1D13", "R8"), ("C1D14", "R8"),
                             ("C1D15", "R8"), ("B1D14", "R8"), ("B1D4", "NP"), ("B1D10", "NP"), ("B1D12", "NP")):
            self.assertIn(("DEBIT", cell), scoped.LAYOUT_CELLS[layout], layout)
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(28))  # -> C1D14 x2
            approve(fixture)
            self.assertEqual(assess(fixture)[0].ready_journals, 1)


class SplitProbeTest(unittest.TestCase):
    def test_probe_rows_carry_each_needed_cell(self):
        from accounting_converter.tools.generate_yayoi_split_probes import probe_signature

        rows = probe_signature("C1D14", {("DEBIT", "R8"), ("DEBIT", "P10")})
        self.assertEqual(len(rows), 15)
        self.assertEqual(rows[0], ("-", "NO"))
        self.assertEqual({r[0] for r in rows[1:]}, {"P10", "R8"})
        rows = probe_signature("B1D4", {("DEBIT", "NP")})
        self.assertEqual(rows[0], ("NP", "NO"))
        self.assertEqual(len(rows), 5)
        with self.assertRaises(Exception):
            probe_signature("C2D3", set())


class ClosingProbeCheckTest(unittest.TestCase):
    HEADER = "//識別フラグ,伝番,日付,借方科目,借方科目名称,借方科目正式名称,借方補助,借方補助名称,借方課区,借方税区,借方税入力方法,借方金額,借方消費税,貸方科目,貸方科目名称,貸方科目正式名称,貸方補助,貸方補助名称,貸方課区,貸方税区,貸方税入力方法,貸方金額,貸方消費税,摘要,借方取引科目,貸方取引科目,借方部門コード,借方部門名称,貸方部門コード,貸方部門名称"

    def _csv(self, directory, name, rows):
        path = Path(directory) / name
        lines = [self.HEADER] + [",".join(r) for r in rows]
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
        return path

    def _row(self, marker, date_value="20260731", flag="1111"):
        r = [""] * 30
        r[0], r[2], r[3], r[11], r[12], r[13], r[21], r[22], r[23] = flag, date_value, "1111", "1000", "0", "3181", "1000", "0", marker
        return r

    def test_results(self):
        from accounting_converter.tools.yayoi_closing_probe_check import judge

        with tempfile.TemporaryDirectory() as d:
            normal, closing = self._row("CL-NORMAL"), self._row("CL-CLOSING")
            without = self._csv(d, "without.csv", [normal])
            same = self._csv(d, "with_same.csv", [normal, closing])
            self.assertEqual(judge(same, without)["result"], "CSV_CANNOT_CARRY_CLOSING")
            marked = self._csv(d, "with_mark.csv", [normal, self._row("CL-CLOSING", flag="1000")])
            found = judge(marked, without)
            self.assertEqual(found["result"], "CSV_MARK_FOUND_IMPORT_UNVERIFIED")
            self.assertEqual(found["column_differences"][0]["column"], "//識別フラグ")
            self.assertEqual(judge(marked, without, without)["result"], "CSV_MARK_ROUNDTRIPS")
            self.assertEqual(judge(marked, without, marked)["result"], "CSV_MARK_LOST_ON_IMPORT")
            self.assertEqual(judge(same, same)["result"], "JDL_DOES_NOT_SEPARATE")
            self.assertEqual(judge(without, without)["result"], "UNDETERMINED")


class ClosingImportJudgeTest(unittest.TestCase):
    """Step 2: the app-format closing entries (month-13 date) must re-export only with 決算整理を含む."""

    HEADER = ClosingProbeCheckTest.HEADER

    def _probe(self, directory, name, cases):
        from accounting_converter.tools.yayoi_probe_check import manifest_path_for

        path = Path(directory) / f"YAYOI_GAP_{name}_20260731_NOT_FOR_PRODUCTION.csv"
        rows = [self.HEADER] + [",".join(row) for _, row in cases]
        path.write_bytes(("\r\n".join(rows) + "\r\n").encode("cp932"))
        manifest = {"probe_date": "20260731", "cases": [
            {"case": case, "journal_index": i, "physical_rows": 1, "pending_evidence_id": f"PENDING:{case}"}
            for i, (case, _) in enumerate(cases)]}
        manifest_path_for(path).write_text(json.dumps(manifest), encoding="utf-8")
        return rows[1:]

    def _row(self, marker, day):
        r = [""] * 30
        r[0], r[2], r[3], r[4], r[5], r[11], r[13], r[14], r[15], r[21], r[23] = (
            "1111", day, "1111", "現金", "現金", "1000", "3181", "未払金", "未払金", "1000", marker)
        return r

    def _export(self, directory, name, rows):
        path = Path(directory) / name
        path.write_bytes(("\r\n".join([self.HEADER, *rows]) + "\r\n").encode("cp932"))
        return path

    def test_results(self):
        from accounting_converter.tools.yayoi_closing_probe_check import judge_import

        with tempfile.TemporaryDirectory() as d:
            probes = Path(d) / "probe"
            probes.mkdir()
            ctl = self._probe(probes, "CLOSING_CTL", [("CI-CTL", self._row("CI-CTL", "20260731"))])
            imp = self._probe(probes, "CLOSING_IMP", [("CI-B1-NO", self._row("CI-B1-NO", "20261331"))])
            ordinary = ",".join(self._row("CI-B1-NO", "20260731"))
            cases = {
                "CLOSING_IMPORT_PRESERVED": (ctl + imp, ctl),
                "CLOSING_IMPORT_REJECTED": (ctl, ctl),
                "CLOSING_IMPORTED_AS_ORDINARY": (ctl + [ordinary], ctl + [ordinary]),
                "UNDETERMINED": (imp, []),
            }
            for expected, (with_rows, without_rows) in cases.items():
                with self.subTest(expected):
                    result = judge_import(probes, self._export(d, "w.csv", with_rows), self._export(d, "o.csv", without_rows))
                    self.assertEqual(result["result"], expected, result)


class RoundTripCheckParentOnlyTest(unittest.TestCase):
    def test_parent_only_subaccount_is_expected_blank(self):
        from accounting_converter.domain.mapping import (
            MappingKey, MappingStatus, MappingType, MappingValue, SubaccountPolicy)
        from accounting_converter.tools.yayoi_roundtrip_check import _subaccount_code
        from types import SimpleNamespace

        key = MappingKey(MappingType.SUBACCOUNT, "その他", "荷造運賃")
        parent_only = MappingValue("その他", "", MappingStatus.USER_CONFIRMED, parent_account="荷造運賃",
                                   metadata={"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value,
                                             "output_code": "0000"})
        profile = SimpleNamespace(subaccount_context_mappings={key: parent_only})
        self.assertEqual(_subaccount_code(profile, "荷造運賃", "その他"), "")


if __name__ == "__main__":
    unittest.main()

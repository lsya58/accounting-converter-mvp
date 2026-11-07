"""Yayoi 控除不可 → JDL 非仕入 only with a company-scoped, tax-accountant-signed approval. Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import noncredit_approval as nc
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    YayoiJournalReportJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.application.yayoi_review import confirm_tax_identity, review_source, yayoi_tax_mapping_review
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from tests.test_yayoi_jdl_workflow import OUTSIDE, YAYOI
from tests.test_yayoi_journal_report_parser import HEADER, build, detail
from tests.test_yayoi_scoped_workflow import DATE, assess, make

NC10, NC8 = "課対仕入10%｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜控除不可"
COMPANY = "company-yayoi"


def noncredit(amount=1399, tax=0, tax_name="課対仕入10%", voucher=1, credit_side=False, invoice="区分記載"):
    line = (YAYOI["fee"], "", tax_name, amount, tax)
    other = (YAYOI["cash"], "", OUTSIDE, amount, None)
    debit, credit = (other, line) if credit_side else (line, other)
    return detail(DATE, voucher, debit=debit, credit=credit, invoice=invoice, credit_ratio="控除不可",
                  description=f"控除不可{voucher}", number=voucher)


@contextmanager
def evidence_covers_test_company():
    """The Evidence names the real company only; the synthetic fixture company stands in for it."""
    with patch.object(nc, "TECHNICAL_EVIDENCE",
                      replace(nc.TECHNICAL_EVIDENCE, company_setting_ids=frozenset({COMPANY}))):
        yield


def approve(fixture, identity=NC10, **overrides):
    resolved = fixture.resolved()
    kwargs = dict(human_approver="担当者A", tax_accountant="税理士B", signoff_reference="確認書 2026-11-07 No.1",
                  signoff_date=date(2026, 11, 7), rate_distinction_loss_acknowledged=True)
    kwargs.update(overrides)
    nc.approve_noncredit_identity(fixture.profiles, resolved.profile.profile_id, COMPANY,
                                  resolved.context, identity, **kwargs)
    fixture._rebind()


def convert(fixture, directory):
    resolved = fixture.resolved()
    workflow = YayoiJournalReportJdlWorkflow()
    output = Path(directory) / "out" / "jdl.csv"
    output.parent.mkdir(exist_ok=True)
    prepared = workflow.prepare(input_path=fixture.source, output_path=output, profile=resolved.profile,
                                context=resolved.context, company_setting_validated=resolved.available)
    return workflow, prepared, output


class ApprovalPreconditionsTest(unittest.TestCase):
    def test_ordinary_confirmation_never_accepts_noncredit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, [noncredit()])
            resolved = fixture.resolved()
            for identity in (NC10, NC8, "課対仕入10%｜適格｜控除不可"):
                with self.assertRaises(ValueError):
                    confirm_tax_identity(fixture.profiles, resolved.profile.profile_id, resolved.context, identity,
                                         JdlTaxSemantic.NON_TAXABLE_PURCHASE)

    def test_every_missing_condition_refuses_the_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, [noncredit()])
            cases = {
                "SIGNOFF": dict(signoff_reference=" "),
                "TAX_ACCOUNTANT": dict(tax_accountant=""),
                "APPROVER": dict(human_approver=""),
                "DATE": dict(signoff_date=None),
                "RATE_LOSS": dict(rate_distinction_loss_acknowledged=False),
            }
            with evidence_covers_test_company():
                for name, override in cases.items():
                    with self.subTest(name), self.assertRaises(ValueError):
                        approve(fixture, **override)
                with self.assertRaises(ValueError):
                    approve(fixture, identity="課対仕入10%｜適格｜控除不可")
            # the real Evidence does not cover another company
            with self.assertRaisesRegex(ValueError, nc.COMPANY_OUT_OF_SCOPE):
                approve(fixture)
            self.assertIs(fixture.resolved().profile.tax_mappings[NC10].status, MappingStatus.UNRESOLVED)

    def test_other_jdl_settings_are_refused(self):
        for settings in (dict(limit=None), dict(limit=20), dict(purchase=JdlTaxRounding.FLOOR)):
            with self.subTest(settings), tempfile.TemporaryDirectory() as directory:
                fixture = make(directory, [noncredit()], **settings)
                with evidence_covers_test_company(), self.assertRaisesRegex(ValueError, nc.CONTEXT_OUT_OF_SCOPE):
                    approve(fixture)


class ConversionTest(unittest.TestCase):
    def test_blocked_until_approved_then_written_as_the_verified_non_taxable_purchase_with_an_audit(self):
        rows = [noncredit(1399, voucher=1), noncredit(5130, tax_name="課対仕入8%（軽）", voucher=2)]
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            fixture = make(directory, rows)
            self.assertEqual(assess(fixture)[0].blocker_counts(), {"HUMAN:TAX_MAPPING": 2})
            approve(fixture, NC10)
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.ready_journals, 1)  # the 8% identity is not covered by the 10% approval
            _, prepared, _ = convert(fixture, directory)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            approve(fixture, NC8)
            self.assertEqual(assess(fixture)[0].blocker_counts(), {})
            workflow, prepared, output = convert(fixture, directory)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            data = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
            # 借方 課区 / 税区 / 入力 / 金額 / 消費税: exactly the A-probe writing (NC-A-NP-10 / NC-A-NP-8)
            self.assertEqual([(r[8], r[9], r[10], r[11], r[12]) for r in data],
                             [("非仕入", "", "", "1399", ""), ("非仕入", "", "", "5130", "")])
            audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
            self.assertEqual(audit["noncredit_tax_line_count"], 2)
            lines = [line for journal in audit["journals"] for line in journal["noncredit_tax_lines"]]
            self.assertEqual([(l["source_tax_identity"], l["source_rate"], l["source_reduced_rate"]) for l in lines],
                             [(NC10, "10%", False), (NC8, "軽減8%", True)])
            first = lines[0]
            self.assertEqual((first["source_invoice_class"], first["source_purchase_credit"], first["source_tax_calculation"],
                              first["source_amount_tax_included"], first["source_tax_amount"]),
                             ("区分記載", "控除不可", "内税", "1399", "0"))
            self.assertEqual((first["jdl_tax_scope"], first["jdl_tax_scope_code"], first["jdl_tax_rate_cell"]), ("非仕入", "34", ""))
            self.assertEqual(first["noncredit_evidence_id"], nc.TECHNICAL_EVIDENCE.evidence_id)
            self.assertEqual((first["human_approver"], first["tax_accountant"], first["tax_accountant_signoff_reference"]),
                             ("担当者A", "税理士B", "確認書 2026-11-07 No.1"))
            self.assertTrue(all(j["source_journal_content_sha256"] and j["source_rows"] for j in audit["journals"]))
            self.assertEqual(verify_non_retained_audit(fixture.source, output, fixture.resolved().profile)["verdict"], "PASS")

    def test_saved_approval_is_rechecked_at_conversion(self):
        tamper = {
            "signoff removed": lambda m: {**m, "noncredit_signoff_reference": ""},
            "another profile": lambda m: {**m, "noncredit_profile_id": "yayoi-jdl-other"},
            "another company": lambda m: {**m, "noncredit_company_setting_id": "company-other"},
            "another evidence": lambda m: {**m, "noncredit_evidence_id": "EVID-OTHER"},
            "no approval kind": lambda m: {k: v for k, v in m.items() if k != "noncredit_approval_kind"},
            "rate loss not acknowledged": lambda m: {**m, "noncredit_rate_distinction_loss_acknowledged": "false"},
        }
        for name, change in tamper.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
                fixture = make(directory, [noncredit()])
                approve(fixture)
                profile = fixture.profiles.get(fixture.resolved().profile.profile_id)
                taxes = dict(profile.tax_mappings)
                taxes[NC10] = replace(taxes[NC10], metadata=change(dict(taxes[NC10].metadata)))
                fixture.profiles.update(replace(profile, tax_mappings=taxes))
                fixture._rebind()
                self.assertEqual(assess(fixture)[0].blocker_counts(), {"HUMAN:TAX_MAPPING": 1})

    def test_an_approval_outside_the_evidence_company_list_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            with evidence_covers_test_company():
                fixture = make(directory, [noncredit()])
                approve(fixture)
                self.assertEqual(assess(fixture)[0].ready_journals, 1)
            # the real Evidence names only the real company: the same saved approval no longer converts
            self.assertEqual(assess(fixture)[0].ready_journals, 0)

    def test_a_changed_jdl_setting_blocks_an_existing_approval(self):
        from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            fixture = make(directory, [noncredit()])
            approve(fixture)
            CompanyVoucherRowLimitService(fixture.companies, fixture.profiles).set(COMPANY, 20, confirmed=True)
            self.assertEqual(assess(fixture)[0].ready_journals, 0)

    def test_only_the_verified_line_shape_converts(self):
        shapes = {
            "tax amount not 0": noncredit(tax=127),
            "credit side": noncredit(credit_side=True),
        }
        for name, row in shapes.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
                fixture = make(directory, [row])
                approve(fixture)
                self.assertEqual(assess(fixture)[0].ready_journals, 0)

    def test_an_external_tax_line_is_blocked(self):
        row = noncredit()
        row[HEADER.index("借方税計算区分")] = "外税"
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            fixture = make(directory, [row])
            approve(fixture)
            line = fixture.entries[0].lines[0]
            self.assertEqual(line.tax_info.metadata["yayoi_tax_calculation"], "外税")
            self.assertEqual(nc.line_problems(line), (nc.LINE_SHAPE_UNVERIFIED,))
            self.assertEqual(assess(fixture)[0].blocker_counts(), {"HUMAN:TAX_MAPPING": 1})

    def test_a_forged_ordinary_mapping_of_another_noncredit_identity_never_converts(self):
        identity = "課対仕入10%｜適格｜控除不可"
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            fixture = make(directory, [noncredit(invoice="適格")])
            approve(fixture)  # the exact 10% identity is approved; this line is a different identity
            resolved = fixture.resolved()
            profile = fixture.profiles.get(resolved.profile.profile_id)
            taxes = dict(profile.tax_mappings)
            taxes[identity] = replace(profile.tax_mappings[NC10], source_value=identity)
            fixture.profiles.update(replace(profile, tax_mappings=taxes))
            fixture._rebind()
            self.assertEqual(assess(fixture)[0].ready_journals, 0)
            items = {i.identity: i for i in review_source(fixture.entries, fixture.resolved().profile, resolved.context).taxes}
            self.assertEqual(items[identity].mapping_state, "UNCONFIRMED")


class Journal565ShapeTest(unittest.TestCase):
    """B1D4 with 非仕入 debits (journal 565): structure proven by round 4 (NP-B1D4); 控除不可 still needs the sign-off."""

    def rows(self):
        from tests.test_yayoi_jdl_workflow import PURCHASE

        total = 1100 * 3 + 999 + 1399
        p10 = lambda: (YAYOI["fee"], "", PURCHASE, 1100, 100)  # noqa: E731
        nc10 = lambda amount: (YAYOI["fee"], "", "課対仕入10%", amount, 0)  # noqa: E731
        out = [detail(DATE, 1, debit=p10(), credit=(YAYOI["cash"], "", OUTSIDE, total, None), invoice="適格",
                      credit_ratio="100%", description="R1", number=1)]
        for k, (line, invoice, ratio) in enumerate(((p10(), "適格", "100%"), (nc10(999), "区分記載", "控除不可"),
                                                     (nc10(1399), "区分記載", "控除不可"), (p10(), "適格", "100%")), start=2):
            out.append(detail(DATE, 1, debit=line, invoice=invoice, credit_ratio=ratio, description=f"R{k}", number=1))
        return out

    def test_blocked_without_signoff_ready_with_it(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            fixture = make(directory, self.rows())
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.ready_journals, 0)
            self.assertIn("HUMAN:TAX_MAPPING", assessment.blocker_counts())
            approve(fixture)
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {})


class ReviewScreenTest(unittest.TestCase):
    def _review(self, fixture, company=COMPANY):
        resolved = fixture.resolved()
        return {item.source_value: item for item in yayoi_tax_mapping_review(
            resolved.profile, resolved.context, observed_source_values=(NC10,), company_setting_id=company).items}

    def test_states_are_explained_and_never_bulk_confirmable(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, [noncredit()])
            item = self._review(fixture)[NC10]  # real Evidence: this company is not covered
            self.assertEqual(item.blocker_code, "YAYOI-JDL-TAX-REPRESENTATION-UNVERIFIED")
            self.assertFalse(item.human_confirmable)
            with evidence_covers_test_company():
                item = self._review(fixture)[NC10]
                self.assertEqual(item.blocker_code, "YAYOI-JDL-TAX-NONCREDIT-TAX-ACCOUNTANT-SIGNOFF-REQUIRED")
                self.assertFalse(item.human_confirmable)
                self.assertEqual(item.action_owner, "HUMAN")
                for text in ("税理士", "10%／軽減8%", "監査記録"):
                    self.assertIn(text, item.reason)
                approve(fixture)
                self.assertEqual(self._review(fixture), {})


class ApprovalToolTest(unittest.TestCase):
    def _run(self, *args):
        env = {**os.environ, "PYTHONPATH": "src"}
        code = ("import sys; from unittest.mock import patch; from dataclasses import replace;"
                "from accounting_converter.application import noncredit_approval as nc;"
                "from accounting_converter.tools import yayoi_noncredit_approval as tool;"
                "p = patch.object(nc, 'TECHNICAL_EVIDENCE', replace(nc.TECHNICAL_EVIDENCE, company_setting_ids=frozenset({'company-yayoi'})));"
                "p.start(); sys.argv = ['tool', *sys.argv[1:]]; raise SystemExit(tool.main())")
        return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env)

    def test_approval_needs_the_judged_signoff(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, [noncredit()])
            report = Path(directory) / "judge.json"
            common = ["approve", "--company-store", directory, "--company-id", COMPANY, "--identity", NC10,
                      "--judge-report", str(report), "--human-approver", "担当者A", "--tax-accountant", "税理士B",
                      "--signoff-reference", "確認書", "--signoff-date", "2026-11-07", "--acknowledge-rate-loss"]
            report.write_text(json.dumps({"cases": {"NC-A-NP-10": {"result": "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN"}}}),
                              encoding="utf-8")
            failed = self._run(*common)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("EQUIVALENCE_CONFIRMED", failed.stderr)
            self.assertEqual(assess(fixture)[0].ready_journals, 0)
            report.write_text(json.dumps({"cases": {"NC-A-NP-10": {"result": "EQUIVALENCE_CONFIRMED"}}}), encoding="utf-8")
            no_ack = self._run(*common[:-1])
            self.assertNotEqual(no_ack.returncode, 0)
            done = self._run(*common)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(json.loads(done.stdout)["identities"][NC10]["converted"])
            mapping = fixture.resolved().profile.tax_mappings[NC10]
            self.assertEqual(len(mapping.metadata["noncredit_judge_report_sha256"]), 64)
            with evidence_covers_test_company():
                self.assertEqual(assess(fixture)[0].ready_journals, 1)


class NoApprovalInSourceTest(unittest.TestCase):
    def test_the_code_holds_evidence_but_no_approval(self):
        text = Path("src/accounting_converter/application/noncredit_approval.py").read_text(encoding="utf-8")
        self.assertEqual(nc.TECHNICAL_EVIDENCE.technical_state,
                         "TECHNICAL_VERIFIED_TAX_EQUIVALENCE_PENDING_TAX_ACCOUNTANT")
        self.assertNotIn("EQUIVALENCE_CONFIRMED", text)
        self.assertEqual(set(nc.NONCREDIT_SOURCES), {NC10, NC8})


if __name__ == "__main__":
    unittest.main()

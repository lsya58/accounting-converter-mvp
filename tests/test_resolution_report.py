"""解決項目モデル・準備状況画面・分割承認の接続。Synthetic data only; Qt tests run offscreen."""
from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.application import resolution_report as rr
from accounting_converter.application import voucher_split
from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from tests.test_voucher_split import card_voucher
from tests.test_yayoi_scoped_workflow import assess, make

try:
    from PySide6.QtWidgets import QApplication
    from accounting_converter.ui_qt.resolution_center import ResolutionCenterDialog, VoucherSplitApprovalDialog
    PYSIDE6 = True
except ModuleNotFoundError:
    PYSIDE6 = False


def line(amount, category=None, side="DEBIT"):
    info = SimpleNamespace(category=category, tax_amount=None) if category else None
    return SimpleNamespace(amount=Decimal(amount), tax_info=info, side=SimpleNamespace(value=side))


def entry(*lines):
    return SimpleNamespace(lines=list(lines))


class ModelTest(unittest.TestCase):
    def test_every_code_of_every_journal_is_kept(self):
        blockers = {
            "x:1": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "SYSTEM_EVIDENCE:MULTIPLE_TAXED_LINES_UNVERIFIED"}),
            "x:2": frozenset(), "x:3": frozenset({"HUMAN:ACCOUNT_MAPPING"})}
        report = rr.build_report(blockers, {})
        self.assertEqual((report.total, report.ready, report.blocked), (3, 1, 2))
        one = report.journal("1")
        self.assertEqual(set(one.codes), blockers["x:1"])  # nothing dropped
        self.assertIsNone(report.journal("2"))  # READY journals are not listed as problems
        self.assertEqual(set(report.item(rr.EVIDENCE_KEY).codes), {"SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "SYSTEM_EVIDENCE:MULTIPLE_TAXED_LINES_UNVERIFIED"})

    def test_ready_is_never_created_by_the_report(self):
        report = rr.build_report({"x:1": frozenset({"SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"})}, {})
        self.assertEqual(report.ready, 0)
        item = report.item("SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION")
        self.assertTrue(item.technical_evidence)
        self.assertFalse(item.app_resolvable)
        self.assertEqual(item.action, rr.ACT_NONE)  # no approval button for an Evidence gap

    def test_actionable_items_point_to_existing_screens(self):
        report = rr.build_report({"x:1": frozenset({"HUMAN:ACCOUNT_MAPPING"}), "x:2": frozenset({"HUMAN:TAX_MAPPING"}),
                                  "x:3": frozenset({"HUMAN:SUBACCOUNT_MAPPING"}), "x:4": frozenset({"HUMAN:VOUCHER_SPLIT_APPROVAL"})}, {})
        actions = {i.key: i.action for i in report.items}
        self.assertEqual(actions["HUMAN:ACCOUNT_MAPPING"], rr.ACT_ACCOUNTS)
        self.assertEqual(actions["HUMAN:TAX_MAPPING"], rr.ACT_TAX)
        self.assertEqual(actions["HUMAN:SUBACCOUNT_MAPPING"], rr.ACT_SUBACCOUNTS)
        self.assertTrue(report.item("HUMAN:SUBACCOUNT_MAPPING").jdl_work)  # JDL registration is JDL-side work
        self.assertTrue(report.item("HUMAN:VOUCHER_SPLIT_APPROVAL").tax_accountant)

    def test_noncredit_negative_and_closing_are_never_resolvable_in_the_app(self):
        noncredit = entry(line(1000, "課対仕入10%｜区分記載｜控除不可"))
        negative = entry(line(-1000, "課対仕入10%｜適格｜100%"), line(2000, None, "CREDIT"))
        report = rr.build_report(
            {"x:425": frozenset({"HUMAN:TAX_MAPPING"}), "x:4012": frozenset({"HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"}),
             "x:9": frozenset({"HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"})}, {"x:425": noncredit, "x:4012": negative, "x:9": entry(line(5))})
        self.assertEqual(report.item(rr.NONCREDIT_KEY).journals, ("425",))
        self.assertEqual(report.item(rr.NEGATIVE_KEY).journals, ("4012",))
        self.assertEqual(report.item(rr.OVER_OTHER_KEY).journals, ("9",))
        for key in (rr.NONCREDIT_KEY, rr.NEGATIVE_KEY):
            item = report.item(key)
            self.assertTrue(item.tax_accountant)
            self.assertFalse(item.app_resolvable)
            self.assertEqual(item.action, rr.ACT_NONE)
        self.assertIn("負の", report.item(rr.NEGATIVE_KEY).title)
        self.assertIn("10%・軽減8%の区別", report.journal("425").notes[0])
        # the original reason code stays visible on the journal
        self.assertEqual(report.journal("4012").codes, ("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED",))

    def test_unknown_codes_are_not_hidden(self):
        report = rr.build_report({"x:1": frozenset({"HUMAN:SOMETHING_NEW"})}, {})
        self.assertEqual(report.item("HUMAN:SOMETHING_NEW").codes, ("HUMAN:SOMETHING_NEW",))


class ControllerReportTest(unittest.TestCase):
    def _controller(self, fixture, root):
        return AccountingConverterController(
            profile_store=fixture.profiles, company_store=fixture.companies,
            preferences_store=ApplicationPreferencesStore(root / "prefs.json"))

    def test_report_follows_the_formal_assessment_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make(directory, card_voucher(39))
            controller = self._controller(fixture, root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            report, comparison = controller.company_resolution_report("company-yayoi", fixture.source)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            formal = assess(fixture)[0]
            self.assertEqual(report.ready, formal.ready_journals)
            self.assertEqual(set(report.journals[0].codes), set(next(iter(formal.journal_blockers.values()))))
            self.assertEqual(report.saved_limit, 16)
            self.assertEqual(report.alternative.limit, 64)  # the trial for the other setting, clearly separate
            self.assertEqual(report.alternative.ready, 1)
            self.assertEqual(report.ready, 0)

    def test_split_approval_only_by_explicit_action_and_not_across_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make(directory, card_voucher(39))
            controller = self._controller(fixture, root)
            report, _ = controller.company_resolution_report("company-yayoi", fixture.source)
            item = report.item(voucher_split.APPROVAL_BLOCKER)
            self.assertEqual(item.action, rr.ACT_SPLIT)
            self.assertTrue(item.app_resolvable)
            limit, briefs = controller.voucher_split_briefs("company-yayoi", fixture.source, item.journals)
            self.assertEqual(limit, 16)
            self.assertTrue(briefs[0]["split"] and briefs[0]["rebuilds_original"])
            # no explicit confirmation: nothing is recorded
            state = controller.approve_voucher_split("company-yayoi", human_approver="a", tax_accountant="b",
                                                     signoff_reference="c", signoff_date=date(2026, 11, 9), explicitly_confirmed=False)
            self.assertIsNotNone(state.developer_error)
            resolved = fixture.resolved()
            self.assertEqual(voucher_split.policy_problems(resolved.profile, resolved.context), ("SPLIT_NOT_APPROVED",))
            # missing sign-off data: nothing is recorded
            state = controller.approve_voucher_split("company-yayoi", human_approver="a", tax_accountant="",
                                                     signoff_reference="c", signoff_date=date(2026, 11, 9), explicitly_confirmed=True)
            self.assertIsNotNone(state.developer_error)
            # explicit, complete: recorded, and the formal diagnosis (not the approval) decides READY
            state = controller.approve_voucher_split("company-yayoi", human_approver="a", tax_accountant="b",
                                                     signoff_reference="c", signoff_date=date(2026, 11, 9), explicitly_confirmed=True)
            self.assertIsNone(state.developer_error, state.user_message)
            report, _ = controller.company_resolution_report("company-yayoi", fixture.source)
            self.assertEqual(report.split_policy_problems, ())
            self.assertIsNone(report.item(voucher_split.APPROVAL_BLOCKER))
            self.assertEqual(report.ready, assess(fixture)[0].ready_journals)
            # changing the row limit invalidates the approval (never borrowed by the other limit)
            CompanyVoucherRowLimitService(fixture.companies, fixture.profiles).set("company-yayoi", 64, confirmed=True)
            fixture._rebind()
            resolved = fixture.resolved()
            self.assertNotEqual(voucher_split.policy_problems(resolved.profile, resolved.context), ())


class FakeController:
    def __init__(self, report, briefs=()):
        self.report, self.briefs, self.approvals = report, briefs, []

    def company_resolution_report(self, company_id, source):
        return self.report, None

    def voucher_split_briefs(self, company_id, source, journal_ids):
        return 64, self.briefs

    def approve_voucher_split(self, company_id, **kwargs):
        self.approvals.append(kwargs)
        return SimpleNamespace(developer_error=None, user_message="")


def brief(split=True):
    return {"journal": "x:1739", "split": split, "why_not": None if split else "NON_POSITIVE_AMOUNT", "rebuilds_original": split,
            "original": {"physical_rows": 66, "explicit_tax": "17015"},
            "parts": [{"jdl_rows": 34, "counterpart_amount": "202759", "explicit_tax": "17015"},
                      {"jdl_rows": 33, "counterpart_amount": "214274", "explicit_tax": "0"}]}


@unittest.skipUnless(PYSIDE6, "PySide6 is not installed")
class QtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _own(self, dialog):
        def cleanup():
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()
        self.addCleanup(cleanup)
        return dialog

    def _report(self):
        entries = {"x:4012": entry(line(-1, "課対仕入10%｜適格｜100%")), "x:425": entry(line(1, "課対仕入10%｜区分記載｜控除不可"))}
        return rr.build_report({
            "x:1739": frozenset({"HUMAN:VOUCHER_SPLIT_APPROVAL"}), "x:4012": frozenset({"HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"}),
            "x:425": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"}),
            "x:3605": frozenset({"SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"}), "x:1": frozenset()}, entries, saved_limit=64)

    def _select(self, dialog, key):
        keys = [dialog.report.items[i].key for i in range(len(dialog.report.items))]
        dialog.item_list.setCurrentRow(keys.index(key))
        self.app.processEvents()

    def test_center_shows_counts_and_buttons_only_where_the_user_can_act(self):
        dialog = self._own(ResolutionCenterDialog(FakeController(self._report(), (brief(),)), "c", Path("s"), {}, None))
        self.assertIn("1", dialog.summary.text())
        self.assertIn("/ 5", dialog.summary.text())
        for key in (rr.NONCREDIT_KEY, rr.NEGATIVE_KEY, "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION", rr.EVIDENCE_KEY):
            self._select(dialog, key)
            self.assertFalse(dialog.action_button.isVisible() and dialog.action_button.isEnabled(), key)
        self._select(dialog, voucher_split.APPROVAL_BLOCKER)
        self.assertFalse(dialog.action_button.isHidden())
        self.assertTrue(dialog.action_button.isEnabled())
        self._select(dialog, rr.NEGATIVE_KEY)
        self.assertIn("負の金額", dialog.detail_text.text())
        self.assertIn("正の金額", dialog.detail_text.text())

    def test_all_blocker_codes_are_in_the_detail_view(self):
        dialog = self._own(ResolutionCenterDialog(FakeController(self._report()), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        dialog.show_details.setChecked(True)
        text = dialog.details.toPlainText()
        self.assertIn("HUMAN:TAX_MAPPING", text)
        self.assertIn("SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", text)  # the other reason of the same journal

    def test_tab_actions_hand_over_to_the_opener_and_dialog_actions_rediagnose(self):
        calls = []
        report = rr.build_report({"x:1": frozenset({"HUMAN:ACCOUNT_MAPPING"}), "x:2": frozenset({"HUMAN:TAX_MAPPING"})}, {})
        controller = FakeController(report)
        dialog = self._own(ResolutionCenterDialog(controller, "c", Path("s"), {
            "ACCOUNTS_TAB": "accounts", "TAX_REVIEW": lambda: calls.append("tax")}, None))
        self._select(dialog, "HUMAN:TAX_MAPPING")
        n = []
        original = controller.company_resolution_report
        controller.company_resolution_report = lambda *a: (n.append(1), original(*a))[1]
        dialog.action_button.click()
        self.assertEqual(calls, ["tax"])
        self.assertEqual(len(n), 1)  # re-diagnosed after the action
        self._select(dialog, "HUMAN:ACCOUNT_MAPPING")
        dialog.action_button.click()
        self.assertEqual(dialog.goto, "accounts")

    def test_approval_dialog_needs_every_field_and_the_explicit_confirmation(self):
        controller = FakeController(self._report(), (brief(),))
        dialog = self._own(VoucherSplitApprovalDialog(controller, "c", Path("s"), ("1739",)))
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.approver.setText("担当者")
        dialog.accountant.setText("税理士")
        dialog.reference.setText("メール 11/9")
        self.assertFalse(dialog.save_button.isEnabled())  # still no explicit confirmation
        dialog.confirm.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertEqual(controller.approvals, [])  # nothing recorded before the click
        self.assertIn("64行", dialog.findChild(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel).text())

    def test_approval_dialog_refuses_when_the_split_is_not_possible(self):
        dialog = self._own(VoucherSplitApprovalDialog(FakeController(self._report(), (brief(split=False),)), "c", Path("s"), ("4012",)))
        for widget, text in ((dialog.approver, "a"), (dialog.accountant, "b"), (dialog.reference, "c")):
            widget.setText(text)
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())


if __name__ == "__main__":
    unittest.main()

"""解決項目モデル・準備状況画面・分割承認の接続。Synthetic data only; Qt tests run offscreen."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

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
    from PySide6.QtWidgets import QApplication, QPushButton
    from accounting_converter.ui_qt.resolution_center import ResolutionCenterDialog, VoucherSplitApprovalDialog
    PYSIDE6 = True
except ModuleNotFoundError:
    PYSIDE6 = False


def line(amount, category=None, side="DEBIT"):
    info = SimpleNamespace(category=category, tax_amount=None) if category else None
    return SimpleNamespace(amount=Decimal(amount), tax_info=info, side=SimpleNamespace(value=side))


def entry(*lines):
    return SimpleNamespace(lines=list(lines))


def flagged_line(row, description, identity="課対仕入10%｜区分記載｜控除不可", amount=1367):
    """A Yayoi 控除不可 source line with every field the tax review shows."""
    return SimpleNamespace(
        amount=Decimal(amount), side=SimpleNamespace(value="DEBIT"), account="消耗品費", sub_account=None,
        source_reference=SimpleNamespace(row_number=row),
        metadata={"journal_row_number": str(row), "journal_row_description": description, "yayoi_journal_number": f"9{row}"},
        tax_info=SimpleNamespace(category=identity, tax_amount=Decimal(0), invoice_classification="区分記載",
                                 metadata={"yayoi_tax_calculation": "内税", "yayoi_purchase_credit": "控除不可"}))


def flagged_entry(*lines, day="2026-01-31"):
    return SimpleNamespace(date=day, lines=[line(500, "課対仕入10%｜適格｜100%"), *lines])


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

    def test_tax_review_facts_are_source_facts_only_and_change_no_decision(self):
        ident = "課対仕入10%｜区分記載｜控除不可"
        src = SimpleNamespace(
            amount=Decimal(1367), side=SimpleNamespace(value="DEBIT"), account="消耗品費", sub_account=None,
            source_reference=SimpleNamespace(row_number=3558),
            metadata={"journal_row_number": "3562", "journal_row_description": "摘要A", "yayoi_journal_number": "64803"},
            tax_info=SimpleNamespace(category=ident, tax_amount=Decimal(0), invoice_classification="区分記載",
                                     metadata={"yayoi_tax_calculation": "内税", "yayoi_purchase_credit": "控除不可"}))
        ordinary = line(500, "課対仕入10%｜適格｜100%")
        e = SimpleNamespace(date="2026-01-31", lines=[ordinary, src])
        blockers = {"x:3558": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"})}
        report = rr.build_report(blockers, {"x:3558": e})
        self.assertEqual((report.ready, report.blocked), (0, 1))  # the facts never create READY
        facts = report.journal("3558").tax_review
        self.assertEqual(len(facts), 1)  # only the flagged line, not the ordinary one
        f = facts[0]
        self.assertEqual((f.source_row, f.yayoi_journal_number, f.tax_identity, f.purchase_credit, f.tax_amount, f.invoice_class),
                         (3562, "64803", ident, "控除不可", "0", "区分記載"))
        self.assertNotIn("誤り", f.state.replace("誤りと確定", ""))  # never states an input mistake as fact
        self.assertIn("残りません", f.not_kept_in_jdl)
        # the technical Evidence gap stays a separate item next to the tax one
        self.assertTrue(report.item(rr.EVIDENCE_KEY).technical_evidence)
        self.assertEqual(report.item(rr.NONCREDIT_KEY).action, rr.ACT_NONE)
        # no flagged line -> nothing is shown
        self.assertEqual(rr.build_report({"x:1": frozenset({"HUMAN:TAX_MAPPING"})}, {"x:1": entry(ordinary)}).journal("1").tax_review, ())

    def test_outlook_separates_direct_derived_independent_and_remaining(self):
        codes = ("HUMAN:TAX_MAPPING", "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT",
                 "SYSTEM_EVIDENCE:MULTIPLE_TAXED_LINES_UNVERIFIED")
        o = rr.outlook_for(codes, frozenset({"HUMAN:VOUCHER_SPLIT_APPROVAL"}))
        self.assertEqual(o.direct, ("HUMAN:TAX_MAPPING",))
        self.assertEqual(o.independent, ("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED",))  # rows are never "derived"
        self.assertEqual(set(o.derived), {"SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", "SYSTEM_EVIDENCE:MULTIPLE_TAXED_LINES_UNVERIFIED"})
        self.assertEqual(o.remaining, ("HUMAN:VOUCHER_SPLIT_APPROVAL",))
        self.assertFalse(o.convertible_after_decision)
        self.assertIn("残る条件", o.headline)
        clear = rr.outlook_for(("HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"), frozenset())
        self.assertTrue(clear.convertible_after_decision)
        self.assertIn("承認前は変換しません", clear.headline)
        # an Evidence gap that survives the what-if stays a technical problem
        gap = rr.outlook_for(("HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:X"), frozenset({"SYSTEM_EVIDENCE:X"}))
        self.assertEqual(gap.technical_remaining, ("SYSTEM_EVIDENCE:X",))
        self.assertFalse(gap.convertible_after_decision)

    def test_outlook_without_a_trial_claims_nothing(self):
        o = rr.outlook_for(("HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"), None)
        self.assertFalse(o.computed)
        self.assertFalse(o.convertible_after_decision)
        self.assertEqual(o.derived, ())
        self.assertEqual(o.remaining, ("SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT",))
        self.assertIn("範囲外", o.headline)
        report = rr.build_report({"x:7": frozenset(o.direct + o.remaining)}, {"x:7": flagged_entry(flagged_line(7, "a"))})
        self.assertFalse(report.journal("7").outlook.computed)  # no trial given -> not computed
        self.assertEqual(report.ready, 0)

    def test_report_attaches_rate_and_other_tax_categories(self):
        e = flagged_entry(flagged_line(3, "a", "課対仕入8%（軽）｜区分記載｜控除不可"), flagged_line(4, "b"))
        report = rr.build_report({"x:9": frozenset({"HUMAN:TAX_MAPPING"})}, {"x:9": e}, tax_decision_trial={"x:9": frozenset()})
        j = report.journal("9")
        self.assertEqual([t.rate for t in j.tax_review], ["軽減8%", "10%"])
        self.assertEqual(j.other_tax, (("課対仕入10%｜適格｜100%", 1),))
        self.assertTrue(j.outlook.convertible_after_decision)
        self.assertEqual(report.ready, 0)  # a what-if never changes READY

    def test_awaiting_tax_decision_only_for_codes_that_vanish_in_the_trial(self):
        e = flagged_entry(flagged_line(1, "a"))
        blockers = {"x:1": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:A"}),
                    "x:2": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:A"}),
                    "x:3": frozenset({"SYSTEM_EVIDENCE:A"})}
        report = rr.build_report(blockers, {"x:1": e, "x:2": e, "x:3": entry(line(5))},
                                 tax_decision_trial={"x:1": frozenset(), "x:2": frozenset({"SYSTEM_EVIDENCE:A"})})
        item = report.item(rr.EVIDENCE_KEY)
        self.assertEqual(item.journals, ("1", "2", "3"))  # nothing hidden
        self.assertEqual(report.awaiting_tax_decision(item), ("1",))  # 2 keeps its gap, 3 has no 控除不可
        no_trial = rr.build_report(blockers, {"x:1": e, "x:2": e, "x:3": entry(line(5))})
        self.assertEqual(no_trial.awaiting_tax_decision(no_trial.item(rr.EVIDENCE_KEY)), ())

    def test_an_approval_is_shown_only_on_the_journal_it_names(self):
        e = flagged_entry(flagged_line(1, "a"))
        record = {"signoff_date": "2026-11-20", "tax_accountant": "税理士B", "signoff_reference": "確認書1"}
        report = rr.build_report({"x:565": frozenset({"HUMAN:TAX_MAPPING"}), "x:3558": frozenset({"HUMAN:TAX_MAPPING"})},
                                 {"x:565": e, "x:3558": e},
                                 noncredit_approvals={"x:565": {"課対仕入10%｜区分記載｜控除不可": record}})
        self.assertEqual(len(report.journal("565").approvals), 1)
        self.assertEqual(report.journal("3558").approvals, ())  # same identity, never inherited

    def test_trial_signoff_is_refused_out_of_scope_and_can_never_be_saved(self):
        from accounting_converter.application import noncredit_approval as nc
        from accounting_converter.domain.mapping import MappingStatus, MappingValue
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStoreError

        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(3))
            resolved = fixture.companies.resolve("company-yayoi")
            self.assertIsNone(nc.signoff_trial_profile(resolved.profile, resolved.context, "company-yayoi"))  # not the Evidence company
            identity = next(iter(nc.NONCREDIT_SOURCES))
            marked = replace(resolved.profile, tax_mappings={**resolved.profile.tax_mappings, identity: MappingValue(
                identity, "", MappingStatus.USER_CONFIRMED, None, {nc.TRIAL_MARKER: "true"})})
            before = {p: p.read_bytes() for p in Path(directory).rglob("*") if p.is_file()}
            with self.assertRaises(ConversionProfileStoreError):
                fixture.profiles.update(marked)
            with self.assertRaises(ConversionProfileStoreError):
                fixture.profiles.to_json_text(marked)
            self.assertEqual(before, {p: p.read_bytes() for p in Path(directory).rglob("*") if p.is_file()})

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
            # explicit and complete but no reviewed journals: no scope, nothing is recorded
            state = controller.approve_voucher_split("company-yayoi", human_approver="a", tax_accountant="b",
                                                     signoff_reference="c", signoff_date=date(2026, 11, 9), explicitly_confirmed=True)
            self.assertIsNotNone(state.developer_error)
            self.assertIn("SPLIT_SCOPE_MISSING", state.user_message)
            # explicit, complete, scoped to the reviewed journals: recorded; the formal diagnosis decides READY
            state = controller.approve_voucher_split("company-yayoi", human_approver="a", tax_accountant="b",
                                                     signoff_reference="c", signoff_date=date(2026, 11, 9), explicitly_confirmed=True,
                                                     source_path=fixture.source, journal_ids=item.journals)
            self.assertIsNone(state.developer_error, state.user_message)
            self.assertEqual(voucher_split.policy_scope(fixture.resolved().profile).kind, voucher_split.SCOPE_JOURNALS)
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
        dialog.context_toggle.setChecked(True)
        self.assertIn("正の金額", dialog.context_text.text())

    def test_ready_only_is_a_separate_button_and_only_when_part_is_ready(self):
        class WithReadyOnly(FakeController):
            def plan_yayoi_ready_only(self, company_id, source):
                raise AssertionError("the plan is computed only when the user opens READYのみ変換")

        dialog = self._own(ResolutionCenterDialog(WithReadyOnly(self._report()), "c", Path("s"), {}, None))
        self.assertFalse(dialog.ready_only_button.isHidden())
        self.assertIn("全件移行ではありません", dialog.ready_only_button.text())
        self.assertIn("変換できません", dialog.summary.text())  # the whole input is still not convertible
        # Without the controller method (or with no READY journal) there is no button.
        self.assertTrue(self._own(ResolutionCenterDialog(FakeController(self._report()), "c", Path("s"), {},
                                                         None)).ready_only_button.isHidden())
        none_ready = rr.build_report({"x:3605": frozenset({"SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"})}, {},
                                     saved_limit=16)
        self.assertTrue(self._own(ResolutionCenterDialog(WithReadyOnly(none_ready), "c", Path("s"), {},
                                                         None)).ready_only_button.isHidden())

    def test_all_blocker_codes_are_in_the_detail_view(self):
        dialog = self._own(ResolutionCenterDialog(FakeController(self._report()), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        dialog.show_details.setChecked(True)
        text = dialog.details.toPlainText()
        self.assertIn("HUMAN:TAX_MAPPING", text)
        self.assertIn("SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", text)  # the other reason of the same journal

    def test_summary_prioritizes_comparison_and_keeps_other_conditions(self):
        base = self._report()
        alt = rr.SettingAlternative(16, 2, ("2",), (), 3)
        dialog = self._own(ResolutionCenterDialog(
            FakeController(replace(base, alternative=alt)), "c", Path("s"), {}, None))
        self.assertIn("READY 1 / 5", dialog.summary.text())
        self.assertIn("BLOCK 4", dialog.summary.text())
        self.assertIn("64行", dialog.summary.text())
        self.assertIn("16行", dialog.next_action.text())
        self.assertIn("条件付き試算", dialog.alternative.text())
        self.assertIn("3件", dialog.alternative.text())
        self.assertFalse(dialog.item_list.horizontalScrollBar().isVisible())
        self._select(dialog, rr.NONCREDIT_KEY)
        self.assertIn("次にすること", dialog.detail_text.text())
        self.assertIn("未検証の仕訳形状", dialog.detail_text.text())
        self.assertIn("税理士", dialog.detail_text.text())
        self._select(dialog, rr.NEGATIVE_KEY)
        self.assertIn("技術", dialog.detail_text.text())
        self.assertIn("税理士", dialog.detail_text.text())
        self._select(dialog, "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION")
        self.assertIn("承認では解除できません", dialog.detail_text.text())

    def test_small_dialog_keeps_actions_and_scrollable_details(self):
        dialog = self._own(ResolutionCenterDialog(FakeController(self._report()), "c", Path("s"), {}, None))
        dialog.resize(580, 420)
        dialog.show()
        self.app.processEvents()
        self.assertFalse(dialog.rediagnose_button.isHidden())
        self.assertFalse(dialog.detail_scroll.isHidden())
        self.assertFalse(dialog.item_list.horizontalScrollBar().isVisible())
        self._select(dialog, rr.NONCREDIT_KEY)
        dialog.show_details.setChecked(True)
        self.assertIn("仕訳 425", dialog.details.toPlainText())

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
        dialog.approval_toggle.setChecked(True)
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
        dialog.approval_toggle.setChecked(True)
        for widget, text in ((dialog.approver, "a"), (dialog.accountant, "b"), (dialog.reference, "c")):
            widget.setText(text)
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())

    def test_bulk_approval_requires_every_journal_to_be_viewed(self):
        first = brief()
        second = dict(brief(), journal="x:1740")
        controller = FakeController(self._report(), (first, second))
        dialog = self._own(VoucherSplitApprovalDialog(controller, "c", Path("s"), ("1739", "1740")))
        dialog.approval_toggle.setChecked(True)
        for widget, value in ((dialog.approver, "担当者"), (dialog.accountant, "税理士"),
                              (dialog.reference, "書面番号A")):
            widget.setText(value)
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIn("1 / 2", dialog.review_progress.text())
        dialog.journal_list.setCurrentRow(1)
        self.assertIn("2 / 2", dialog.review_progress.text())
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertIn("今後", dialog.scope.text())
        self.assertEqual(controller.approvals, [])

    def test_split_table_and_save_remain_visible_in_small_dialog(self):
        dialog = self._own(VoucherSplitApprovalDialog(
            FakeController(self._report(), (brief(),)), "c", Path("s"), ("1739",)))
        dialog.resize(533, 400)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(dialog.parts_table.height(), 60)
        self.assertTrue(dialog.save_button.isVisible())
        self.assertEqual(dialog.parts_table.rowCount(), 2)
        dialog.approval_toggle.setChecked(True)
        self.assertTrue(dialog.approval_panel.isVisible())
        self.assertFalse(dialog.save_button.isEnabled())

    def test_missing_requested_journal_blocks_bulk_approval(self):
        dialog = self._own(VoucherSplitApprovalDialog(
            FakeController(self._report(), (brief(),)), "c", Path("s"), ("1739", "1740")))
        dialog.approval_toggle.setChecked(True)
        for widget in (dialog.approver, dialog.accountant, dialog.reference):
            widget.setText("確認済み")
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(dialog.missing_notice.isHidden())

    # ---------------------------------------------------------------- 税区分の確認（控除不可）
    def _tax_report(self, n_lines=1, description="1/22　販売者　テープ", trial=frozenset()):
        lines = [flagged_line(100 + i, description, amount=1000 + i) for i in range(n_lines)]
        entries = {"x:3558": flagged_entry(*lines), "x:425": flagged_entry(flagged_line(426, "手土産", "課対仕入8%（軽）｜区分記載｜控除不可"), day="2025-08-30")}
        blockers = {
            "x:3558": frozenset({"HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"}),
            "x:425": frozenset({"HUMAN:TAX_MAPPING", "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", "SYSTEM_EVIDENCE:MULTIPLE_TAXED_LINES_UNVERIFIED"}),
            "x:1": frozenset()}
        tr = None if trial is None else {"x:3558": trial, "x:425": frozenset({"HUMAN:VOUCHER_SPLIT_APPROVAL"})}
        return entries, rr.build_report(blockers, entries, saved_limit=16, tax_decision_trial=tr)

    def test_tax_review_shows_the_five_facts_per_journal_without_buttons(self):
        _, report = self._tax_report()
        dialog = self._own(ResolutionCenterDialog(FakeController(report), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        text = dialog.detail_text.text()
        for heading in ("元の税区分", "税率", "確認が必要な理由", "税理士が判断すること", "技術的に残っている問題", "判断後の見通し"):
            self.assertIn(heading, text)
        self.assertIn("仕訳 3558", text)
        self.assertIn("仕訳 425", text)
        self.assertIn("軽減8%", text)
        self.assertIn("誤りと確定したわけではありません", text)
        self.assertNotIn("入力ミスを検出", text)
        self.assertIn("伝票分割の承認", text)  # 425: what remains after the decision
        self.assertFalse(dialog.action_button.isVisible() and dialog.action_button.isEnabled())
        self.assertFalse(any(b.text().startswith(("承認", "税区分を変更")) for b in dialog.findChildren(QPushButton) if b.isVisible()))
        # details are closed first, then show every source field
        self.assertTrue(dialog.tax_detail.isHidden())
        dialog.tax_detail_toggle.setChecked(True)
        detail = dialog.tax_detail.text()
        for value in ("行100", "9100", "課対仕入10%｜区分記載｜控除不可", "内税", "区分記載", "控除不可", "1000", "販売者",
                      "課対仕入10%｜適格｜100% 1明細", "行数", "残りません"):
            self.assertIn(value, detail)
        self.assertIn("監査記録", detail)
        self.assertIn("借方", detail)
        # the Evidence item of the same journals says they wait for the tax decision, without hiding the count
        self._select(dialog, rr.EVIDENCE_KEY)
        evidence = dialog.report.item(rr.EVIDENCE_KEY)
        self.assertEqual(set(evidence.journals), {"3558", "425"})
        self.assertIn("税区分の確定待ち", dialog.detail_text.text())
        self.assertIn("実機確認済みとして扱うわけではありません", dialog.detail_text.text())
        self.assertIn("2件", dialog.item_list.item(dialog.item_list.currentRow()).text())
        self.assertIn("先に「税区分の確認が必要」の税理士判断", dialog.detail_text.text())
        self.assertNotIn("追加の実機確認が必要です（設定や承認では解消しません）", dialog.detail_text.text())

    def test_tax_review_never_reports_an_evidence_gap_as_solved(self):
        _, report = self._tax_report(trial=frozenset({"SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT"}))
        dialog = self._own(ResolutionCenterDialog(FakeController(report), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        text = dialog.detail_text.text()
        self.assertIn("残る実機Evidence不足: 1件（JDL実機で未確認の形があります）", text)
        dialog.show_details.setChecked(True)
        self.assertIn("SYSTEM_EVIDENCE:SHAPE_UNVERIFIED_IN_TAX_CONTEXT", dialog.details.toPlainText())  # raw codes kept
        self.assertNotIn("他のBLOCKは残りません", text)
        _, unknown = self._tax_report(trial=None)
        dialog2 = self._own(ResolutionCenterDialog(FakeController(unknown), "c", Path("s"), {}, None))
        self._select(dialog2, rr.NONCREDIT_KEY)
        self.assertIn("未評価", dialog2.detail_text.text())
        self.assertIn("範囲外", dialog2.detail_text.text())
        self.assertNotIn("他のBLOCKは残りません", dialog2.detail_text.text())

    def test_tax_review_escapes_source_values(self):
        hostile = "<b>太字</b><img src=x onerror=1>&amp;<script>alert(1)</script>"
        entries, report = self._tax_report(description=hostile)
        snapshot = [(l.amount, l.tax_info.category, dict(getattr(l, "metadata", {}))) for l in entries["x:3558"].lines]
        dialog = self._own(ResolutionCenterDialog(FakeController(report), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        dialog.tax_detail_toggle.setChecked(True)
        html = dialog.tax_detail.text()
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<b>太字", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;amp;", html)
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setHtml(html)
        self.assertIn(hostile, doc.toPlainText())  # rendered as literal text, character for character
        self.assertEqual(snapshot, [(l.amount, l.tax_info.category, dict(getattr(l, "metadata", {}))) for l in entries["x:3558"].lines])

    def test_tax_review_with_many_long_lines_scrolls_vertically_only(self):
        _, report = self._tax_report(n_lines=40, description="非常に長い摘要" * 30)
        dialog = self._own(ResolutionCenterDialog(FakeController(report), "c", Path("s"), {}, None))
        dialog.resize(580, 420)
        dialog.show()
        self.app.processEvents()
        self._select(dialog, rr.NONCREDIT_KEY)
        dialog.tax_detail_toggle.setChecked(True)
        self.app.processEvents()
        self.assertEqual(dialog.tax_detail.text().count("元の行 / 弥生の仕訳番号"), 41)
        self.assertFalse(dialog.detail_scroll.horizontalScrollBar().isVisible())
        bar = dialog.detail_scroll.verticalScrollBar()
        self.assertTrue(bar.isVisible())
        self.assertGreater(bar.maximum(), 0)
        self.assertLessEqual(dialog.detail_page.width(), dialog.detail_scroll.viewport().width())
        for widget in (dialog.rediagnose_button, dialog.tax_detail_toggle):
            self.assertFalse(widget.isHidden())
        self.assertGreater(dialog.rediagnose_button.height(), dialog.rediagnose_button.fontMetrics().height())
    def test_tax_review_never_shows_another_journals_approval(self):
        e = flagged_entry(flagged_line(1, "a"))
        record = {"signoff_date": "2026-11-20", "tax_accountant": "税理士B", "signoff_reference": "確認書1"}
        report = rr.build_report({"x:565": frozenset({"HUMAN:TAX_MAPPING"}), "x:3558": frozenset({"HUMAN:TAX_MAPPING"})},
                                 {"x:565": e, "x:3558": e},
                                 noncredit_approvals={"x:565": {"課対仕入10%｜区分記載｜控除不可": record}})
        dialog = self._own(ResolutionCenterDialog(FakeController(report), "c", Path("s"), {}, None))
        self._select(dialog, rr.NONCREDIT_KEY)
        text = dialog.detail_text.text()
        part565, part3558 = text.split("仕訳 3558")[0].split("仕訳 565")[1], text.split("仕訳 3558")[1]
        self.assertIn("確認書1", part565)
        self.assertNotIn("確認書1", part3558)
        self.assertIn("別の仕訳の承認はこの仕訳に適用されません", part3558)


if __name__ == "__main__":
    unittest.main()

"""Yayoi → JDL with the campaign Evidence: diagnosis, conversion, row limit, tax candidates. Synthetic data only."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import csv
import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.adapters.output.jdl import JdlTaxRounding
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application.company_voucher_row_limit import (
    CompanyVoucherRowLimitError,
    CompanyVoucherRowLimitService,
)
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_review import (
    candidate_semantic,
    confirm_tax_identity,
    yayoi_tax_mapping_review,
)
from accounting_converter.domain.mapping import MappingStatus
from tests.test_mf_tax_capability_composition import context as base_context
from tests.test_yayoi_jdl_workflow import OUTSIDE, PURCHASE, SALES, YAYOI, Fixture
from tests.test_yayoi_journal_report_parser import detail

DATE = "令和08年05月10日"


def scoped_context(limit=16, sales=JdlTaxRounding.CEILING, purchase=JdlTaxRounding.HALF_UP):
    return replace(base_context(), sales_tax_rounding=sales, purchase_tax_rounding=purchase, voucher_row_limit=limit)


def sales_voucher(rows: int, voucher: int = 1):
    """One voucher of `rows` physical rows: 現金 / 課税売上10% (a 3D3C / 4D4C shape from the campaign)."""
    return [
        detail(DATE, voucher, debit=(YAYOI["cash"], "", OUTSIDE, 1100, None), credit=(YAYOI["sales"], "", SALES, 1100, 100),
               description=f"売上{k}", number=voucher)
        for k in range(1, rows + 1)
    ]


def make(directory, rows, **context_kwargs) -> Fixture:
    with patch("tests.test_yayoi_jdl_workflow.context", lambda: scoped_context(**context_kwargs)):
        fixture = Fixture(Path(directory), rows)
    fixture.confirm_accounts()
    fixture.confirm_taxes()
    return fixture


def assess(fixture):
    resolved = fixture.resolved()
    return YayoiJournalReportJdlWorkflow().assess(fixture.source, resolved.profile, resolved.context), resolved


class ConversionInScopeTest(unittest.TestCase):
    def test_3d3c_sales_voucher_is_ready_and_written_as_the_rows_that_round_tripped(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3))
            assessment, resolved = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {})
            self.assertEqual(assessment.ready_journals, 1)
            workflow = YayoiJournalReportJdlWorkflow()
            output = Path(directory) / "out" / "jdl.csv"
            prepared = workflow.prepare(input_path=fixture.source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=resolved.available)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            rows = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
            self.assertEqual([r[0] for r in rows], ["1110", "1100", "1101"])
            for row in rows:
                self.assertEqual((row[3], row[13]), ("1111", "6121"))
                self.assertEqual((row[18], row[19], row[20], row[21], row[22]), ("売　上", "10%", "外税", "1100", "100"))
                self.assertEqual((row[8], row[9], row[10], row[12]), ("", "", "", ""))
            self.assertEqual([r[23] for r in rows], ["売上1", "売上2", "売上3"])

    def test_the_sales_account_the_human_picks_decides_whether_the_evidence_applies(self):
        # 売上Y mapped to an account whose 課税売上10% never round-tripped: stays blocked.
        from accounting_converter.domain.mapping import MappingValue

        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3))
            profile = fixture.profiles.get(fixture.resolved().profile.profile_id)
            accounts = dict(profile.account_mappings)
            accounts[YAYOI["sales"]] = MappingValue(
                YAYOI["sales"], "手数料", MappingStatus.USER_CONFIRMED,
                metadata={**accounts[YAYOI["sales"]].metadata, "target_code": "8681",
                          "target_printed_name": "手数料", "target_formal_name": "手数料"})
            fixture.profiles.update(replace(profile, account_mappings=accounts))
            fixture._rebind()
            assessment, _ = assess(fixture)
            self.assertIn("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED", assessment.blocker_counts())
            self.assertEqual(assessment.ready_journals, 0)


class RowLimitDiagnosisTest(unittest.TestCase):
    def test_over_limit_journal_is_a_human_decision_and_never_converts(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(17), limit=16)
            assessment, resolved = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {"HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED": 1})
            workflow = YayoiJournalReportJdlWorkflow()
            output = Path(directory) / "blocked.csv"
            prepared = workflow.prepare(input_path=fixture.source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=True)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            self.assertTrue(any("振替伝票入力行数" in reason and "自動で分割しません" in reason
                                for reason in prepared.summary.blocking_reasons))
            self.assertIsNone(workflow.execute(prepared))
            self.assertFalse(output.exists())

    def test_over_limit_is_reported_whatever_the_mapping_state_and_even_outside_the_scope(self):
        for limit in (2, 16):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                with patch("tests.test_yayoi_jdl_workflow.context", lambda limit=limit: scoped_context(limit=limit)):
                    fixture = Fixture(Path(directory), sales_voucher(3))  # nothing confirmed
                resolved = fixture.resolved()
                counts = YayoiJournalReportJdlWorkflow().assess(fixture.source, resolved.profile, resolved.context).blocker_counts()
                self.assertEqual("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED" in counts, limit == 2)

    def test_unconfirmed_limit_is_a_human_setting_not_an_assumption(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), limit=None)
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {"HUMAN:VOUCHER_ROW_LIMIT_SETTING": 1})

    def test_other_rounding_never_gets_the_campaign_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)
            assessment, _ = assess(fixture)
            counts = assessment.blocker_counts()
            self.assertEqual(assessment.ready_journals, 0)
            self.assertTrue(any(key.startswith("SYSTEM_EVIDENCE:") for key in counts), counts)
            self.assertNotIn("HUMAN:VOUCHER_ROW_LIMIT_SETTING", counts)

    def test_existing_evidence_covers_a_journal_without_any_row_limit(self):
        # The original 2-row fixture (Evidence that existed before): no limit, no rounding recorded.
        with tempfile.TemporaryDirectory() as directory:
            with patch("tests.test_yayoi_jdl_workflow.context", base_context):
                fixture = Fixture(Path(directory), [
                    detail(DATE, 1, debit=(YAYOI["fee"], "", PURCHASE, 1100, 100),
                           credit=(YAYOI["cash"], "", OUTSIDE, 1100, None), invoice="適格", credit_ratio="100%",
                           description="手数料", number=1)])
            fixture.confirm_accounts()
            fixture.confirm_taxes()
            assessment, _ = assess(fixture)
            self.assertEqual(assessment.blocker_counts(), {})


class TaxCandidateTest(unittest.TestCase):
    def test_only_observed_identities_have_a_candidate(self):
        self.assertIs(candidate_semantic("輸出売上"), JdlTaxSemantic.EXPORT_SALES)
        self.assertIs(candidate_semantic("課対仕入8%（軽）｜適格｜100%"), JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL)
        self.assertIs(candidate_semantic("課対仕入10%｜区分記載｜80%経過措置"), JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL)
        self.assertIs(candidate_semantic("対外仕入"), JdlTaxSemantic.NO_TAX)
        # unobserved or unresolved: no candidate, nothing replaced by a normal purchase / 対象外
        for identity in ("課対仕入10%｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜100%",
                         "課対仕入8%（軽）｜適格｜80%経過措置", "輸出売上免税", "課対仕入10%｜適格｜80%経過措置"):
            with self.subTest(identity=identity):
                self.assertIsNone(candidate_semantic(identity))
        self.assertIs(candidate_semantic("課対仕入10%｜適格｜100%"), JdlTaxSemantic.PURCHASE_10_INTERNAL)  # unchanged

    def review(self, ctx, identities):
        from accounting_converter.domain.conversion_profile import ConversionProfile  # noqa: F401
        from types import SimpleNamespace

        profile = SimpleNamespace(tax_mappings={i: None for i in identities})
        return yayoi_tax_mapping_review(profile, ctx, observed_source_values=tuple(identities))

    def test_new_representations_are_confirmable_only_inside_the_scope_and_never_for_deduction_denied(self):
        identities = ("輸出売上", "課対仕入8%（軽）｜適格｜100%", "課対仕入10%｜区分記載｜80%経過措置", "対外仕入",
                      "課対仕入10%｜区分記載｜控除不可")
        inside = {item.source_value: item for item in self.review(scoped_context(), identities).items}
        for identity in identities[:4]:
            self.assertTrue(inside[identity].human_confirmable, identity)
            self.assertEqual(inside[identity].action_owner, "HUMAN")
        self.assertIn("BUDDIES-CAMP-BI-EXPORT", inside["輸出売上"].evidence_id)
        denied = inside["課対仕入10%｜区分記載｜控除不可"]
        self.assertFalse(denied.human_confirmable)
        self.assertEqual(denied.action_owner, "SYSTEM_EVIDENCE")
        # a company with another rounding: the new Evidence does not apply (対外仕入 is a plain 対象外)
        other = {item.source_value: item for item in self.review(
            scoped_context(sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR), identities).items}
        for identity in identities[:3]:
            self.assertFalse(other[identity].human_confirmable, identity)
            self.assertEqual(other[identity].action_owner, "SYSTEM_EVIDENCE")
            self.assertIn("端数処理", other[identity].reason)
        self.assertTrue(other["対外仕入"].human_confirmable)

    def test_confirming_a_new_representation_outside_the_scope_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)
            with self.assertRaises(ValueError):
                confirm_tax_identity(fixture.profiles, fixture.resolved().profile.profile_id, fixture.context,
                                     "輸出売上", JdlTaxSemantic.EXPORT_SALES)
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3))
            saved = confirm_tax_identity(fixture.profiles, fixture.resolved().profile.profile_id, fixture.context,
                                         "輸出売上", JdlTaxSemantic.EXPORT_SALES)
            mapping = saved.tax_mappings["輸出売上"]
            self.assertIs(mapping.status, MappingStatus.USER_CONFIRMED)
            self.assertEqual((mapping.target_value, mapping.metadata["jdl_tax_scope"]), ("", "輸出売"))


class RowLimitServiceTest(unittest.TestCase):
    def test_saving_the_limit_changes_nothing_the_human_already_decided(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), limit=None)
            service = CompanyVoucherRowLimitService(fixture.companies, fixture.profiles)
            before = fixture.resolved()
            self.assertIsNone(service.current("company-yayoi"))
            self.assertEqual(service.set("company-yayoi", 16, confirmed=True), 16)
            after = fixture.resolved()
            self.assertEqual(after.context.voucher_row_limit, 16)
            self.assertEqual(service.current("company-yayoi"), 16)
            self.assertNotEqual(after.profile.profile_id, before.profile.profile_id)  # a new revision
            self.assertEqual(
                {k: (v.target_value, v.status) for k, v in after.profile.tax_mappings.items()},
                {k: (v.target_value, v.status) for k, v in before.profile.tax_mappings.items()})
            self.assertTrue(all(v.status is MappingStatus.USER_CONFIRMED for v in after.profile.tax_mappings.values()))
            self.assertEqual(
                {k: v.target_value for k, v in after.profile.account_mappings.items()},
                {k: v.target_value for k, v in before.profile.account_mappings.items()})
            self.assertEqual(assess(fixture)[0].blocker_counts(), {})  # the unconfirmed-limit blocker is gone
            self.assertTrue(fixture.profiles.get(before.profile.profile_id))  # the old revision is kept

    def test_the_human_must_confirm_and_the_value_must_be_sane(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), limit=None)
            service = CompanyVoucherRowLimitService(fixture.companies, fixture.profiles)
            before = fixture.resolved().context.voucher_row_limit
            for bad in (0, -1, 1000, True, "16", 16.0):
                with self.subTest(bad=bad), self.assertRaises(CompanyVoucherRowLimitError):
                    service.set("company-yayoi", bad, confirmed=True)
            with self.assertRaises(CompanyVoucherRowLimitError):
                service.set("company-yayoi", 16, confirmed=False)
            self.assertEqual(fixture.resolved().context.voucher_row_limit, before)

    def test_tax_setting_reconfirmation_keeps_the_limit(self):
        from accounting_converter.application.company_tax_context_confirmation import CompanyTaxContextConfirmationService

        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3), limit=16)
            # the saved context is not a draft: the service rebuilds it from the previous context
            service = CompanyTaxContextConfirmationService(fixture.companies, fixture.profiles)
            context = service.current_context("company-yayoi")
            self.assertEqual(context.voucher_row_limit, 16)


class WhatIfToolTest(unittest.TestCase):
    def test_what_if_never_touches_the_saved_company_setting_and_classifies_every_journal(self):
        from accounting_converter.tools.yayoi_whatif_readiness import diagnose

        rows = sales_voucher(3, voucher=1) + sales_voucher(17, voucher=2)
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, rows, limit=None)
            files = sorted(p for p in Path(directory).rglob("*") if p.is_file())
            before = {str(p): p.read_bytes() for p in files}
            result = diagnose(fixture.source, Path(directory), "company-yayoi", set_row_limit=16, scenarios=["exact"])
            after = {str(p): p.read_bytes() for p in sorted(p for p in Path(directory).rglob("*") if p.is_file())}
            self.assertEqual(before, after)  # not a byte of the saved setting changed
            self.assertIsNone(fixture.resolved().context.voucher_row_limit)
        self.assertEqual(result["journals"], 2)
        self.assertEqual(result["actual_saved_setting"]["ready"], 0)
        now = result["technical_sizing_now"]["classes"]
        self.assertEqual(now, {"technical_ok_account_restricted": 1, "voucher_row_limit_exceeded": 1})
        self.assertEqual(result["what_if"]["exact"]["classes"]["voucher_row_limit_exceeded"], 1)


try:
    from PySide6.QtWidgets import QApplication, QPushButton

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class VoucherRowLimitGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def review(self, **kwargs):
        from accounting_converter.application.company_mapping_update import CompanyMappingUpdateReview

        return CompanyMappingUpdateReview(
            company_setting_id="company-yayoi", source_path=None, context_path=None, items=(), logical_journal_count=40,
            source_is_yayoi=True, voucher_row_counts=((2, 30), (5, 6), (17, 3), (73, 1)), **kwargs)

    def test_dialog_never_prefills_and_needs_the_value_and_an_acknowledgement(self):
        from types import SimpleNamespace

        from accounting_converter.ui_qt.voucher_row_limit import VoucherRowLimitDialog

        calls = []
        controller = SimpleNamespace(confirm_company_voucher_row_limit=lambda cid, limit, explicitly_confirmed: (
            calls.append((cid, limit, explicitly_confirmed)) or SimpleNamespace(developer_error=None, user_message="")))
        dialog = VoucherRowLimitDialog(controller, "company-yayoi", ((2, 30), (17, 3), (73, 1)), None)
        self.assertEqual(dialog.value.value(), 0)  # "（未入力）": nothing is suggested
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.value.setValue(16)
        self.assertFalse(dialog.save_button.isEnabled())  # acknowledgement missing
        self.assertIn("4仕訳", dialog.over_label.text())  # 17行 and 73行 journals
        dialog.acknowledge.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.save_button.click()
        self.assertEqual(calls, [("company-yayoi", 16, True)])
        self.assertEqual(dialog.saved, 16)

    def test_other_tab_separates_the_setting_the_human_enters_from_what_cannot_be_converted(self):
        from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog

        unconfirmed = CompanyMappingUpdateDialog(
            object(), self.review(scoped_evidence_state="VOUCHER_ROW_LIMIT_UNCONFIRMED"))
        text = unconfirmed.voucher_status_label.text()
        self.assertIn("未確認", text)
        self.assertIn("最長73行", text)
        self.assertIn("入力すると使えます", text)
        self.assertEqual(unconfirmed.tabs.tabText(unconfirmed.category_tabs["other"]), "その他 要確認")
        self.assertIn("振替伝票入力行数", unconfirmed.summary_label.text())
        page = unconfirmed.tabs.widget(unconfirmed.category_tabs["other"])
        self.assertIn("振替伝票入力行数を入力…", [button.text() for button in page.findChildren(QPushButton)])

        confirmed = CompanyMappingUpdateDialog(
            object(), self.review(voucher_row_limit=16, scoped_evidence_state="IN_SCOPE"))
        text = confirmed.voucher_status_label.text()
        self.assertIn("16行以内（確認済み）", text)
        self.assertIn("16行を超える仕訳: 4仕訳", text)
        self.assertIn("自動で分割しません", text)
        self.assertIn("この仕訳は変換されません", text)
        self.assertIn("登録済みの実機Evidenceを使えます", text)
        self.assertIn("振替伝票入力行数を超える仕訳: 4仕訳", confirmed.summary_label.text())

        other = CompanyMappingUpdateDialog(
            object(), self.review(voucher_row_limit=None, scoped_evidence_state="OUT_OF_SCOPE"))
        self.assertIn("新しい実機Evidenceは使えません", other.voucher_status_label.text())

    def test_mf_review_has_no_voucher_section(self):
        from accounting_converter.application.company_mapping_update import CompanyMappingUpdateReview
        from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog

        dialog = CompanyMappingUpdateDialog(object(), CompanyMappingUpdateReview(
            company_setting_id="c", source_path=None, context_path=None, items=(), logical_journal_count=1))
        self.assertIsNone(dialog.voucher_button)


if __name__ == "__main__":
    unittest.main()

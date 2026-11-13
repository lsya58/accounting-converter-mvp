"""Yayoi through the app controller (the layer the Windows screens call). Synthetic data only.

Qt itself is not exercised here; these tests cover what the screens do:
recognize the file, review accounts/subaccounts/taxes with candidates,
confirm, re-assess, and convert only when READY.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.application.mapping_candidates import TargetAccount, rank_candidates
from accounting_converter.application.yayoi_sources import IMPORT
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from accounting_converter.ui.view_models import RecognizedFormat
from tests.test_yayoi_import_format import Company, floor_context, journals, write_import
from tests.test_yayoi_journal_report_parser import build, write
from tests.test_yayoi_jdl_workflow import details


class CandidateRankingTest(unittest.TestCase):
    TARGETS = (
        TargetAccount("6121", "売上高", "売上", "CREDIT"),
        TargetAccount("8681", "支払手数料", "手数料", "DEBIT"),
        TargetAccount("1311", "普通預金", "普通", "DEBIT"),
        TargetAccount("8491", "消耗品費", "消耗品", "DEBIT"),
    )

    def test_kinds_and_basis_are_shown_and_nothing_is_decided(self):
        kinds = lambda name, **kw: [(c.code, c.kind) for c in rank_candidates(name, self.TARGETS, **kw)]  # noqa: E731
        self.assertEqual(kinds("売上高")[0], ("6121", "EXACT"))
        self.assertEqual(kinds("売上高　")[0], ("6121", "NORMALIZED"))
        self.assertEqual(kinds("売上金")[0], ("6121", "ALIAS"))
        self.assertEqual(kinds("消耗品費等")[0], ("8491", "NORMALIZED"))
        self.assertEqual(kinds("事務消耗品費")[0], ("8491", "CONTAINS"))
        self.assertEqual(kinds("全く別の名前"), [])
        # A previously approved target in this company ranks first, even with another name.
        self.assertEqual(kinds("売上高", approved_code="8681")[0], ("8681", "APPROVED"))

    def test_category_conflict_is_warned_not_hidden(self):
        sales_used_as_fee = rank_candidates("手数料収入", self.TARGETS, tax_usage=("JDL_SALES_10_EXTERNAL",))
        fee = next(c for c in sales_used_as_fee if c.code == "8681")
        self.assertIn("逆", fee.warning)  # sales usage vs a debit-side expense account
        self.assertNotIn("正しい", fee.basis)


class ControllerYayoiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def controller(self, company):
        return AccountingConverterController(
            profile_store=company.profiles,
            company_store=company.companies,
            preferences_store=ApplicationPreferencesStore(self.root / "prefs.json"),
        )

    def test_report_format_is_recognized_with_its_own_identity(self):
        source = write(self.root, build(details()))
        company = Company(self.root, "company-r", source, __import__(
            "accounting_converter.application.yayoi_sources", fromlist=["REPORT"]).REPORT, floor_context())
        controller = self.controller(company)
        state = controller.select_file(source)
        self.assertEqual(state.file_recognition.format, RecognizedFormat.YAYOI)
        self.assertIn("仕訳日記帳", state.file_recognition.display_name)
        self.assertEqual(state.file_recognition.journal_count, 2)

    def test_review_confirm_reassess_and_convert_only_when_ready(self):
        source = write_import(self.root, journals())
        company = Company(self.root, "company-i", source, IMPORT, floor_context())
        controller = self.controller(company)
        controller.load_company_settings()
        controller.select_file(source)
        controller.select_company_setting("company-i")
        controller.select_output_file(self.root / "out.csv")

        # 1. Nothing confirmed: Human blockers, no output.
        state = controller.prepare_conversion()
        self.assertFalse(state.conversion_available)
        owners = dict(state.blocker_owner_counts)
        self.assertGreater(owners["HUMAN"], 0)
        self.assertEqual(owners["SYSTEM_IMPLEMENTATION"], 0)

        # 2. The review shows each account once, with its journal count.
        review = controller.review_company_mapping_updates("company-i", source)
        accounts = [item for item in review.items if item.mapping_type == "ACCOUNT"]
        self.assertEqual(len(accounts), len({item.source_value for item in accounts}))
        self.assertTrue(all(item.affected_journal_count > 0 for item in accounts))
        self.assertTrue(all(item.exact_candidate is None for item in accounts))  # nothing pre-decided

        # 3. Taxes: shown with candidates, confirmed one by one through the controller.
        tax = controller.company_tax_mapping_review("company-i")
        self.assertTrue(all(item.action_owner == "HUMAN" for item in tax.items))
        controller.confirm_company_tax_mappings("company-i", tuple(item.source_value for item in tax.items))
        profile = company.profiles.get(company.companies.get("company-i").conversion_profile_id)
        self.assertTrue(all(m.status is MappingStatus.USER_CONFIRMED for m in profile.tax_mappings.values()))

        # 4. Accounts/subaccounts confirmed (as the review dialog saves them), then READY.
        company.profile = profile
        company.confirm_all()
        controller.load_company_settings()
        controller.select_company_setting("company-i")
        state = controller.prepare_conversion()
        self.assertTrue(state.conversion_available, state.messages)
        self.assertEqual(dict(state.blocker_owner_counts), {"HUMAN": 0, "SYSTEM_EVIDENCE": 0, "SYSTEM_IMPLEMENTATION": 0})
        state = controller.execute_conversion(confirmed=True)
        self.assertTrue((self.root / "out.csv").exists(), state.messages)

    def test_review_dialog_save_path_for_yayoi(self):
        """What CompanyMappingUpdateDialog._save calls: selections + explicit confirmations."""
        from accounting_converter.application.yayoi_sources import REPORT
        from tests.test_yayoi_jdl_workflow import YAYOI as WY

        source = write(self.root, build(details(long_description=True)))
        company = Company(self.root, "company-s", source, REPORT, floor_context())
        controller = self.controller(company)
        controller.load_company_settings()
        controller.select_file(source)
        controller.select_company_setting("company-s")
        review = controller.review_company_mapping_updates("company-s", source)
        self.assertIsNone(controller.ensure_selected_tax_requirements(review).developer_error)
        accounts = {item.source_value: item for item in review.items if item.mapping_type == "ACCOUNT"}
        # Candidate for 支払手数料Y → 手数料 (contains), shown with basis, not pre-selected.
        fee = accounts[WY["fee"]]
        self.assertIsNone(fee.exact_candidate)
        self.assertEqual(fee.candidates[0].name, "手数料")
        # Only what the Human selected and confirmed is saved.
        saved = controller.apply_company_mapping_updates(
            review, {fee.key: "手数料"}, {fee.key},
            {review.descriptions[0].key: "振込手数料"}, {review.descriptions[0].key},
        )
        self.assertGreaterEqual(saved, 1)
        profile = company.profiles.get(company.companies.get("company-s").conversion_profile_id)
        self.assertEqual(profile.account_mappings[WY["fee"]].status, MappingStatus.USER_CONFIRMED)
        self.assertNotIn(WY["sales"], profile.account_mappings)  # untouched items stay unconfirmed
        again = controller.review_company_mapping_updates("company-s", source)
        self.assertNotIn(WY["fee"], {i.source_value for i in again.items if i.mapping_type == "ACCOUNT"})
        self.assertEqual(again.descriptions, ())

    def test_reused_on_the_next_file(self):
        source = write_import(self.root, journals())
        company = Company(self.root, "company-n", source, IMPORT, floor_context())
        company.confirm_all()
        controller = self.controller(company)
        controller.load_company_settings()
        (self.root / "m2").mkdir()
        next_month = write_import(self.root / "m2", journals())
        controller.select_file(next_month)
        controller.select_company_setting("company-n")
        controller.select_output_file(self.root / "m2" / "out.csv")
        state = controller.prepare_conversion()
        self.assertTrue(state.conversion_available, state.messages)

    def test_evidence_gaps_are_not_reported_as_human_work(self):
        from tests.test_yayoi_import_format import OUTSIDE, SALES, YAYOI, row

        source = write_import(self.root, [
            row("2110", 9, "R.08/05/20", (YAYOI["supplies"], "", OUTSIDE, 2200, 0), (YAYOI["sales"], "", SALES, 2200, 200), "振替"),
            row("2101", 9, "R.08/05/20", (YAYOI["fee"], "", OUTSIDE, 300, 0), (YAYOI["cash"], "", OUTSIDE, 300, 0), "振替"),
        ])
        company = Company(self.root, "company-e", source, IMPORT, floor_context())
        company.confirm_all()
        controller = self.controller(company)
        controller.load_company_settings()
        controller.select_file(source)
        controller.select_company_setting("company-e")
        controller.select_output_file(self.root / "e.csv")
        state = controller.prepare_conversion()
        self.assertFalse(state.conversion_available)
        self.assertEqual(dict(state.blocker_owner_counts)["HUMAN"], 0)
        self.assertEqual(dict(state.blocker_owner_counts)["SYSTEM_EVIDENCE"], 1)

    def test_yayoi_company_can_be_created_from_a_sample_csv(self):
        source = write(self.root, build(details()))
        company = Company(self.root, "company-x", write_import(self.root, journals()), IMPORT, floor_context())
        controller = self.controller(company)
        profile = controller.create_yayoi_company_draft_profile("新しい顧問先", source)
        self.assertIn("仕訳日記帳", profile.source_format_identity.format_name)
        self.assertTrue(all(m.status is MappingStatus.UNRESOLVED for m in profile.tax_mappings.values()))


if __name__ == "__main__":
    unittest.main()

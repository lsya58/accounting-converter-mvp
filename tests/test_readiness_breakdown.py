"""Readiness breakdown (first vs all reasons, 'only this' counts, wrong-store warnings) and
GUI-controller == CLI-workflow equivalence on the same stored setting. Synthetic values only."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from accounting_converter.application import readiness_breakdown as rb

BLOCKERS = {
    "j1": set(),
    "j2": {"HUMAN:VOUCHER_ROW_LIMIT_SETTING"},
    "j3": {"HUMAN:VOUCHER_ROW_LIMIT_SETTING", "HUMAN:SUBACCOUNT_MAPPING"},
    "j4": {"HUMAN:SUBACCOUNT_MAPPING"},
    "j5": {"HUMAN:SUBACCOUNT_MAPPING", "SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED"},
    "j6": {"SYSTEM_EVIDENCE:VOUCHER_LAYOUT_UNVERIFIED", "HUMAN:TAX_MAPPING"},
    "j7": {"SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION"},
}


class BreakdownTest(unittest.TestCase):
    def rows(self):
        return {row.blocker: row for row in rb.breakdown(BLOCKERS)}

    def test_first_all_and_only_this_are_separate_counts(self):
        row = self.rows()["HUMAN:VOUCHER_ROW_LIMIT_SETTING"]
        self.assertEqual((row.first, row.all, row.only_this), (2, 2, 1))
        sub = self.rows()["HUMAN:SUBACCOUNT_MAPPING"]
        self.assertEqual((sub.first, sub.all, sub.only_this), (2, 3, 1))  # j3 is first-blocked by the row limit

    def test_ready_journals_are_not_counted_and_every_blocked_journal_has_one_first_blocker(self):
        self.assertEqual(sum(row.first for row in rb.breakdown(BLOCKERS)), 6)

    def test_evidence_gaps_are_not_fixable_by_settings(self):
        for blocker in ("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED", "SYSTEM_EVIDENCE:VOUCHER_LAYOUT_UNVERIFIED"):
            _category, action = rb.describe(blocker)
            self.assertIn("実機", action)
        self.assertEqual(rb.describe("SYSTEM_EVIDENCE:TAX_ACCOUNT_UNVERIFIED")[0], "Evidence不足（税）")
        self.assertEqual(rb.describe("SYSTEM_EVIDENCE:VOUCHER_LAYOUT_UNVERIFIED")[0], "Evidence不足（仕訳構造）")

    def test_summary_lines_state_the_fix_and_the_only_this_count(self):
        lines = rb.summary_lines(BLOCKERS)
        self.assertTrue(lines[0].startswith("【会社設定】2仕訳（これだけで止まっている仕訳 1）"))
        self.assertIn("振替伝票入力行数", lines[0])

    def test_trace_of_reference_ready_journals(self):
        trace = rb.trace_ready(["j1", "j2", "j4"], BLOCKERS)
        self.assertEqual(trace["reference_ready"], 3)
        self.assertEqual(trace["still_ready"], 1)
        self.assertEqual(trace["first_blocker"], {"HUMAN:VOUCHER_ROW_LIMIT_SETTING": 1, "HUMAN:SUBACCOUNT_MAPPING": 1})


class StoreCheckTest(unittest.TestCase):
    def check(self, **overrides):
        values = dict(account_mappings=73, subaccount_mappings=7, master_accounts=122, account_blocked_journals=0,
                      voucher_row_limit=16, confirmed_context=True)
        values.update(overrides)
        return rb.store_check(**values)

    def test_a_complete_setting_has_no_warning(self):
        self.assertEqual(self.check(), ())

    def test_a_setting_without_account_approvals_is_flagged_as_possibly_the_wrong_one(self):
        self.assertTrue(any("0件" in w for w in self.check(account_mappings=0)))

    def test_an_unset_row_limit_is_reported_not_filled_in(self):
        self.assertTrue(any("未入力" in w for w in self.check(voucher_row_limit=None)))

    def test_unconfirmed_context_and_empty_master_are_flagged(self):
        warnings = self.check(confirmed_context=False, master_accounts=0)
        self.assertEqual(len(warnings), 2)


STORE = Path("data/private/yayoi_store")
SOURCE = Path("data/private/yayoi_buddies/source.txt")


@unittest.skipUnless(STORE.exists() and SOURCE.exists(), "private data is not present")
class GuiPathEqualsCliPathTest(unittest.TestCase):
    def test_controller_and_workflow_agree_for_every_stored_yayoi_setting(self):
        from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
        from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
        from accounting_converter.ui.controllers import AccountingConverterController

        for company_id in ("company-yayoi-buddies",):
            with tempfile.TemporaryDirectory() as directory:
                profiles = ConversionProfileStore(STORE / "profiles")
                companies = CompanySettingStore(STORE / "companies", profiles)
                resolved = companies.resolve(company_id)
                cli = YayoiJournalReportJdlWorkflow().assess(SOURCE, resolved.profile, resolved.context)
                controller = AccountingConverterController(
                    profile_store=profiles, company_store=companies,
                    preferences_store=ApplicationPreferencesStore(Path(directory) / "prefs.json"))
                controller.load_profiles()
                controller.load_company_settings()
                controller.select_file(SOURCE)
                controller.select_company_setting(company_id)
                controller.select_output_file(Path(directory) / "out.csv")
                state = controller.prepare_conversion()
                self.assertEqual(state.formal_ready_summary, (cli.ready_journals, cli.entry_count))
                # An empty setting must be explained, not just shown as 0.
                if resolved.profile and not resolved.profile.account_mappings:
                    self.assertTrue(any("科目対応が0件" in m for m in state.messages))


if __name__ == "__main__":
    unittest.main()

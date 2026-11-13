"""Regression: D0 preview and D2 tracker on company A (private data only; skipped without it). Nothing is approved
or written to the saved settings; the source is read through a same-bytes copy under the name the EXE read."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

SOURCE = Path("data/private/yayoi_buddies/source.txt")
STORE = Path("data/private/yayoi_buddies/pilot2/verification_20261110/store_copy")
OUTPUT = Path("data/private/yayoi_buddies/ready_only_2479/BUDDIES_READY_ONLY_2479_20250801-20260731_JDL_IMPORT.csv")
COMPANY = "company-f92affc1f3ed43c8aee36380ab612f9d"
SPLIT_ROWS = [425, 503, 1094, 1739, 1805, 2329, 3482, 3569, 4163, 4700, 4873, 5426, 5445, 6075, 6100, 6594, 6621,
              7246, 7265, 7420]


@unittest.skipUnless(SOURCE.exists() and STORE.exists() and OUTPUT.exists(), "private data is not present")
class CompanyAApprovalAndTrackerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from accounting_converter.application import approval_ledger as al
        from accounting_converter.application.yayoi_sources import detect_format
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

        cls.tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.tmp.name) / "バディーズCSV.txt"
        shutil.copyfile(SOURCE, cls.source)
        cls.resolved = CompanySettingStore(STORE / "companies", ConversionProfileStore(STORE / "profiles")).resolve(COMPANY)
        entries = detect_format(cls.source).diagnose(cls.source).entries
        cls.items = {i.item_id: i for i in al.pending_items(entries, cls.resolved.profile, cls.resolved.context, COMPANY)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _preview(self, *ids):
        from accounting_converter.application import approval_ledger as al

        return al.preview(self.source, self.resolved.profile, self.resolved.context, COMPANY,
                          [(self.items[i], None) for i in ids])

    def test_items_and_previews_match_the_block35_plan(self):
        self.assertEqual(sorted(t.source_row for t in self.items["SPLIT-V1"].targets), SPLIT_ROWS)
        self.assertEqual(sorted(i for i in self.items if i.startswith("NONCREDIT-")),
                         ["NONCREDIT-3558", "NONCREDIT-425", "NONCREDIT-565"])
        self.assertFalse(any(t.source_row == 3461 for i in self.items.values() for t in i.targets))  # voucher 1240
        split = self._preview("SPLIT-V1")
        self.assertEqual((split.ready_before, split.block_before, split.ready_after, split.block_after),
                         (2479, 35, 2498, 16))
        row_425 = next(c for c in split.targets if c.source_row == 425)
        self.assertEqual(row_425.state, "BLOCKのまま")
        self.assertIn("HUMAN:TAX_MAPPING", row_425.after)
        both = self._preview("SPLIT-V1", "NONCREDIT-425", "NONCREDIT-565", "NONCREDIT-3558")
        self.assertEqual((both.ready_after, both.block_after, len(both.released)), (2501, 13, 22))
        self.assertEqual((both.newly_blocked, both.outside_scope_changed, both.problems), ((), (), ()))

    def test_tracker_accounts_for_all_2514_journals_and_marks_nothing_migrated(self):
        from accounting_converter.application import migration_tracker as mt

        before = OUTPUT.read_bytes()
        tracker = mt.create_tracker(self.source, OUTPUT, self.resolved.profile, self.resolved.context, COMPANY,
                                    created_by="試験")
        self.assertEqual(len(tracker["journals"]), 35)
        self.assertTrue(all(j["status"] == mt.NOT_STARTED for j in tracker["journals"]))
        integrity = mt.check(tracker, self.source, OUTPUT, self.resolved.profile, self.resolved.context, COMPANY)
        self.assertEqual(integrity["verdict"], "PASS", integrity["problems"])
        self.assertEqual((integrity["counts"]["source_journals"], integrity["counts"]["ready_only_output"]), (2514, 2479))
        final = mt.final_reconciliation(tracker, integrity)
        self.assertEqual(final["verdict"], "MIGRATION_INCOMPLETE")
        self.assertEqual(len(final["open_journals"]), 35)
        self.assertEqual(OUTPUT.read_bytes(), before)


    def test_the_35_are_listed_without_picking_files_and_tracking_starts_only_when_asked(self):
        from accounting_converter.application import migration_tracker as mt
        from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
        from accounting_converter.ui.controllers import AccountingConverterController
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

        work = Path(self.tmp.name) / "work"
        work.mkdir()
        shutil.copyfile(SOURCE, work / "バディーズCSV.txt")                  # the name the EXE read (the audit names it)
        for path in OUTPUT.parent.glob(OUTPUT.name + "*"):
            if path.is_file():
                shutil.copyfile(path, work / path.name)
        profiles = ConversionProfileStore(STORE / "profiles")
        controller = AccountingConverterController(
            profile_store=profiles, company_store=CompanySettingStore(STORE / "companies", profiles),
            preferences_store=ApplicationPreferencesStore(Path(self.tmp.name) / "prefs.json"))
        source = work / "バディーズCSV.txt"
        data = controller.unmigrated_overview(COMPANY, source)
        self.assertEqual((data["total"], data["ready"], data["blocked"]), (2514, 2479, 35))
        self.assertEqual(len(data["rows"]), 35)
        self.assertTrue(all(r.status == "未対応（管理表は未作成）" for r in data["rows"]))
        row_425 = next(r for r in data["rows"] if r.source_row == 425)
        self.assertEqual(row_425.accountant, ("伝票分割の承認（SPLIT-V1）", "控除不可の承認（NONCREDIT-425）"))
        row_1240 = next(r for r in data["rows"] if r.source_row == 3461)           # voucher 1240: no approval releases it
        self.assertEqual((row_1240.accountant, row_1240.voucher), ((), "1240"))
        found = controller.find_ready_only_runs(COMPANY, source, [work])
        self.assertEqual([c.accepted for c in found], [True])
        output = found[0].output
        self.assertEqual(controller.open_migration_run(COMPANY, source, output)["state"], "NO_TRACKER")
        self.assertFalse(list(work.glob("*tracker*")))                              # viewing wrote nothing
        controller.start_migration_tracking(COMPANY, source, output, "試験", explicitly_confirmed=True)
        opened = controller.open_migration_run(COMPANY, source, output)
        self.assertEqual((opened["state"], opened["final"]["verdict"]), ("TRACKED", "MIGRATION_INCOMPLETE"))
        self.assertEqual({j["status"] for j in opened["tracker"]["journals"]}, {mt.NOT_STARTED})
        self.assertEqual(len(opened["tracker"]["journals"]), 35)


if __name__ == "__main__":
    unittest.main()

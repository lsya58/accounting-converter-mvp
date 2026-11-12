"""承認・未移行の管理: controller (read-only) and the Qt dialog (skipped without PySide6; run it on Windows)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.application import migration_tracker as mt
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from tests.test_approval_ledger import Env as ApprovalEnv
from tests.test_approval_ledger import store_digest
from tests.test_noncredit_approval import evidence_covers_test_company
from tests.test_yayoi_ready_only import Run

try:
    from PySide6.QtWidgets import QApplication

    from accounting_converter.ui_qt.migration_status_dialog import MigrationStatusDialog

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

COMPANY = "company-yayoi"


def controller_for(fixture, root: Path):
    return AccountingConverterController(profile_store=fixture.profiles, company_store=fixture.companies,
                                         preferences_store=ApplicationPreferencesStore(root / "prefs.json"))


class ControllerTest(unittest.TestCase):
    def test_items_preview_and_tracker_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            controller = controller_for(env.fixture, env.root)
            digest = store_digest(env.root)
            items = controller.approval_items(COMPANY, env.source)
            self.assertIn("SPLIT-V1", [item.item_id for item, _ in items])
            self.assertTrue(all(state == "未判断" for _, state in items))
            seen = controller.approval_preview(COMPANY, env.source, ["SPLIT-V1"])
            self.assertEqual(seen.ready_after - seen.ready_before, len(seen.released))
            self.assertEqual(store_digest(env.root), digest)
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            run.write()
            tracker = mt.create_tracker(run.source, run.output, run.resolved.profile, run.resolved.context, COMPANY,
                                        created_by="x")
            path = Path(directory) / "tracker.json"
            mt.save(tracker, path)
            controller = controller_for(run.fixture, Path(directory))
            _, integrity, final = controller.migration_tracker_status(COMPANY, run.source, run.output, path)
            self.assertEqual(integrity["verdict"], "PASS")
            self.assertEqual(final["verdict"], "MIGRATION_INCOMPLETE")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_approval_tab_lists_details_and_previews_without_writing(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            digest = store_digest(env.root)
            dialog = MigrationStatusDialog(controller_for(env.fixture, env.root), COMPANY, env.source)
            self.addCleanup(dialog.deleteLater)
            self.assertGreaterEqual(dialog.item_list.count(), 2)
            self.assertIn("会社ID", dialog.item_detail.text())
            self.assertIn("未判断", dialog.item_detail.text())
            dialog.run_preview(["SPLIT-V1"])
            self.assertIn("承認後の予測", dialog.preview_text.text())
            self.assertIn("承認は記録していません", dialog.preview_text.text())
            self.assertGreater(dialog.preview_table.rowCount(), 0)
            self.assertEqual(store_digest(env.root), digest)
            labels = [b.text() for b in dialog.findChildren(type(dialog.preview_button))]
            self.assertFalse(any("承認を記録" in text for text in labels))

    def test_tracker_tab_counts_filters_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            run.write()
            tracker = mt.create_tracker(run.source, run.output, run.resolved.profile, run.resolved.context, COMPANY,
                                        created_by="x")
            path = Path(directory) / "tracker.json"
            mt.save(tracker, path)
            dialog = MigrationStatusDialog(controller_for(run.fixture, Path(directory)), COMPANY, run.source)
            self.addCleanup(dialog.deleteLater)
            dialog.load_tracker(run.output, path)
            self.assertIn("3", dialog.tracker_counts.text())
            self.assertIn("未完了", dialog.tracker_counts.text())
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            dialog.status_filter.setCurrentText(mt.STATES[mt.RECONCILED])
            self.assertEqual(dialog.tracker_table.rowCount(), 0)
            dialog.status_filter.setCurrentText(mt.STATES[mt.NOT_STARTED])
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            dialog._show_journal(0)
            self.assertIn("BLOCKコード", dialog.journal_detail.text())
            self.assertIn("未解決事項", dialog.open_issues.text())
            out = Path(directory) / "sheet.csv"
            self.assertTrue(dialog.export_csv(out))
            self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(mt.load(path), tracker | {})  # the tracker file is not changed by the screen


if __name__ == "__main__":
    unittest.main()

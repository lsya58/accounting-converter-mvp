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

    def _dialog(self, env, **kwargs):
        dialog = MigrationStatusDialog(controller_for(env.fixture, env.root), COMPANY, env.source)
        self.addCleanup(dialog.deleteLater)
        for name, value in kwargs.items():
            setattr(dialog, name, value)
        if kwargs:
            dialog.refresh_items()
        return dialog

    def _select(self, dialog, *needles):
        """Select the list rows whose item ids contain any needle (like the user clicking them)."""
        dialog.item_list.clearSelection()
        for row, entry in enumerate(dialog.entries):
            if entry[0] == "item" and any(n in entry[1].item_id for n in needles):
                dialog.item_list.item(row).setSelected(True)

    def test_the_preview_button_shows_the_result_when_clicked(self):
        """Regression: `clicked` passes `checked` (False); the slot used to treat it as the item list and failed silently."""
        from tests.test_approval_explanation import extras

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            record, catalog = extras(env)
            digest = store_digest(env.root)
            dialog = self._dialog(env, trailing_space_record=record, catalog_path=catalog)
            self.assertEqual(len([e for e in dialog.entries if e[0] == "item"]), 5)
            self.assertEqual([e for e in dialog.entries if e[0] == "guide"], [])
            self._select(dialog, "SPLIT-V1")
            dialog.preview_button.click()                                  # the real button, not run_preview(...)
            self.assertIn("承認した場合の予測", dialog.preview_text.text())
            self.assertIn("承認は記録しておらず", dialog.preview_text.text())
            self.assertEqual(dialog.released_table.rowCount(), 1)
            self.assertEqual(dialog.remaining_table.rowCount(), 1)
            self.assertIn("未承認", dialog.remaining_table.item(0, 4).text())
            self.assertEqual(dialog.released_table.item(0, 1).text(), "1")   # 伝票No. and 日付 are shown
            self.assertIn("控除不可の未承認条件", dialog.preview_text.text())
            self.assertEqual(store_digest(env.root), digest)               # read-only
            self.assertFalse(list(env.root.rglob("*.jsonl")))              # and no ledger entry
            self._select(dialog, "NONCREDIT")
            dialog.preview_button.click()
            self.assertIn("EQUIVALENCE_CONFIRMED", dialog.preview_text.text())   # missing prerequisites are shown

    def test_the_button_never_stays_silent(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            dialog.item_list.clearSelection()
            dialog.item_list.setCurrentRow(-1)
            dialog.preview_button.click()
            self.assertIn("選んでください", dialog.preview_text.text())
            guide_row = next(r for r, e in enumerate(dialog.entries) if e[0] == "guide")
            dialog.item_list.clearSelection()
            dialog.item_list.item(guide_row).setSelected(True)
            dialog.preview_button.click()
            self.assertIn("別の承認経路", dialog.preview_text.text())
            self._select(dialog, "SPLIT-V1")

            def boom(*args, **kwargs):
                raise RuntimeError("synthetic failure")

            dialog.controller.approval_preview_view = boom
            dialog.preview_button.click()
            self.assertIn("試算できませんでした", dialog.preview_text.text())
            self.assertIn("synthetic failure", dialog.preview_text.text())
            self.assertIn("承認は記録されていません", dialog.preview_text.text())

    def test_the_detail_is_in_plain_language_and_keeps_the_technical_information(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            self.assertEqual([e[1].guide_id for e in dialog.entries if e[0] == "guide"], ["TRAILING-SPACE", "POLICY"])
            nc_row = next(r for r, e in enumerate(dialog.entries) if e[0] == "item" and e[1].kind == "NONCREDIT_JOURNAL")
            dialog.item_list.setCurrentRow(nc_row)
            text = dialog.item_detail.text()
            for needle in ("1. 何の取引・仕訳か", "2. 元の弥生での処理", "3. JDLで提案している処理", "4. 変換によって失われる",
                           "5. 税理士に判断してほしいこと", "8. 承認できない場合の対応候補", "9. 現在の承認状態", "未判断",
                           "課対仕入10%", "非仕入"):
                self.assertIn(needle, text)
            self.assertNotIn("EVID-YAYOI", text)                      # technical details are one toggle away
            dialog.technical_toggle.setChecked(True)
            text = dialog.item_detail.text()
            self.assertIn(COMPANY, text)
            self.assertIn("EVID-YAYOI", text)
            labels = [b.text() for b in dialog.findChildren(type(dialog.preview_button))]
            self.assertFalse(any("承認を記録" in label for label in labels))

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

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


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The screen logs failures (log_local_exception) to %LOCALAPPDATA%\\AccountingConverter\\logs. A test must never
        # write into the real application's folder, so the log goes to a temporary one.
        from unittest import mock

        cls._log_dir = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ, {"LOCALAPPDATA": cls._log_dir.name})
        cls._env.start()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls._log_dir.cleanup()

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

    # ---------------------------------------------------------------- D2 tab: no files to pick
    def _d2(self, directory, write=True):
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=write)
        dialog = MigrationStatusDialog(env.controller, COMPANY, env.run.source)
        self.addCleanup(dialog.deleteLater)
        return env, dialog

    def test_the_unmigrated_journals_are_shown_with_one_click_and_no_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory, write=False)             # no READY-only output, no tracker at all
            dialog.refresh_button.click()
            self.assertIn("READY 2", dialog.tracker_counts.text())
            self.assertIn("<b>1</b>", dialog.tracker_counts.text())
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            self.assertEqual(dialog.tracker_table.item(0, 4).text(), "未対応（管理表は未作成）")
            for column in (3, 5, 6, 7):
                self.assertTrue(dialog.tracker_table.item(0, column).text())
            self.assertIn("見つかっていません", dialog.run_banner.text())
            self.assertFalse(dialog.start_button.isEnabled())            # nothing to start management on
            self.assertTrue(dialog.export_button.isEnabled())
            self.assertIn("必要な税理士判断", dialog.journal_detail.text())      # the first journal is shown at once
            self.assertNotIn(COMPANY, dialog.journal_detail.text())       # technical details are behind a toggle
            dialog.tracker_technical_toggle.setChecked(True)
            self.assertIn(COMPANY, dialog.journal_detail.text())
            self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))   # viewing wrote nothing

    def test_switching_to_the_tab_loads_the_list_by_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory, write=False)
            self.assertEqual(dialog.tracker_table.rowCount(), 0)
            dialog.tabs.setCurrentIndex(1)
            self.assertEqual(dialog.tracker_table.rowCount(), 1)

    def test_the_run_next_to_the_source_is_found_and_status_management_starts_only_on_confirmation(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from accounting_converter.application import migration_tracker as mt

        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            dialog.refresh_button.click()
            self.assertIn("状態管理はまだ始まっていません", dialog.run_banner.text())
            self.assertTrue(dialog.start_button.isEnabled())
            tracker_path = mt.tracker_path_for(env.run.output)
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                dialog.start_button.click()
            self.assertFalse(tracker_path.exists())                      # declined: nothing created
            dialog.creator_edit.setText("架空担当")
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as asked:
                dialog.start_button.click()
            self.assertIn(str(tracker_path), asked.call_args.args[2])    # the message names where it will be written
            self.assertTrue(tracker_path.exists())
            self.assertIn("一致しています", dialog.run_banner.text())
            self.assertFalse(dialog.start_button.isEnabled())            # started once: no second start
            self.assertEqual(dialog.tracker_table.item(0, 4).text(), "未対応")   # nothing becomes "migrated" by itself
            self.assertIn("未完了", dialog.tracker_counts.text())
            self.assertEqual((env.overview()["ready"], env.overview()["blocked"]), (2, 1))   # READY / BLOCK unchanged

    def test_an_existing_status_is_kept_when_the_screen_reopens_it(self):
        from accounting_converter.application import migration_tracker as mt

        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x",
                                                           explicitly_confirmed=True)
            tracker = mt.load(path)
            mt.set_status(tracker, tracker["journals"][0]["source_row"], mt.MANUAL_ENTERED_UNRECONCILED, by="x",
                          jdl_entry={"jdl_vouchers": "501", "jdl_date": "2026-05-10", "entered_by": "架空",
                                     "entered_at": "2026-11-20T10:00"})
            mt.save(tracker, path)
            saved = path.read_bytes()
            dialog.refresh_button.click()
            self.assertEqual(dialog.tracker_table.item(0, 4).text(), "手入力済み・未照合")   # not reconciled, not reset
            self.assertIn("未完了", dialog.tracker_counts.text())
            self.assertFalse(dialog.start_button.isEnabled())
            self.assertEqual(path.read_bytes(), saved)

    def test_a_foreign_or_modified_pairing_is_refused_on_the_screen_and_nothing_is_overwritten(self):
        import json

        from tests.test_yayoi_ready_only import _edit_manifest

        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            path = env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x",
                                                           explicitly_confirmed=True)
            tracker = json.loads(path.read_text(encoding="utf-8"))
            tracker["company_id"] = "company-other"                     # a tracker of another company
            path.write_text(json.dumps(tracker), encoding="utf-8")
            saved = path.read_bytes()
            dialog.refresh_button.click()
            self.assertIn("使いません", dialog.run_banner.text())
            self.assertEqual(dialog.tracker_table.item(0, 4).text(), "未対応（管理表は未作成）")   # state not taken from it
            self.assertFalse(dialog.start_button.isEnabled())            # and no "start" that would overwrite it
            self.assertEqual(path.read_bytes(), saved)
            tracker["company_id"] = COMPANY
            path.write_text(json.dumps(tracker), encoding="utf-8")
            _edit_manifest(env.run.output, lambda m: m.update(not_migrated_journals=0))   # a tampered manifest
            dialog.refresh_button.click()
            self.assertIn("検証に失敗", dialog.run_banner.text())
            self.assertIn("改変", dialog.run_banner.text())
            self.assertFalse(dialog.start_button.isEnabled())
            self.assertEqual(dialog.tracker_table.rowCount(), 1)         # the list itself is still shown (from the diagnosis)

    def test_a_changed_output_does_not_reuse_the_old_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            env.run.output.write_bytes(env.run.output.read_bytes() + b"\r\n")
            dialog.refresh_button.click()
            self.assertIn("出力CSVが変更されています", dialog.run_banner.text())
            self.assertEqual(dialog.tracker_table.item(0, 4).text(), "未対応（管理表は未作成）")

    def test_a_folder_named_once_finds_a_run_that_is_not_next_to_the_source(self):
        from accounting_converter.application import migration_tracker as mt

        with tempfile.TemporaryDirectory() as directory:
            from tests.test_unmigrated_view import Env

            env = Env(directory, write=False)
            elsewhere = Path(directory) / "out"
            elsewhere.mkdir()
            env.run.output = elsewhere / "ready_only.csv"
            env.run.write()
            dialog = MigrationStatusDialog(env.controller, COMPANY, env.run.source)
            self.addCleanup(dialog.deleteLater)
            dialog.refresh_button.click()
            self.assertIn("見つかっていません", dialog.run_banner.text())
            dialog.add_folder(elsewhere)                                 # what the folder button does after the picker
            self.assertIn("状態管理はまだ始まっていません", dialog.run_banner.text())
            self.assertEqual(dialog.run_combo.count(), 1)
            self.assertFalse(mt.tracker_path_for(env.run.output).exists())

    def test_filters_and_the_csv_sheet(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            dialog.refresh_button.click()
            dialog.status_filter.setCurrentText("照合済み") if dialog.status_filter.findText("照合済み") >= 0 else None
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            dialog.status_filter.setCurrentText("未対応（管理表は未作成）")
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            out = Path(directory) / "sheet.csv"
            self.assertTrue(dialog.export_csv(out))
            self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))
            from unittest import mock

            from PySide6.QtWidgets import QMessageBox

            with mock.patch.object(QMessageBox, "warning") as warned:   # never a real modal dialog in a test
                self.assertFalse(dialog.export_csv(out))                 # never overwrites
            self.assertTrue(warned.called)


if __name__ == "__main__":
    unittest.main()

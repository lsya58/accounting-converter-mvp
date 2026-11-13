"""承認・未移行の管理: controller (read-only) and the Qt dialog (skipped without PySide6; run it on Windows)."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

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


def wait_idle(dialog, timeout_ms=60000) -> bool:
    """Process events until the dialog's background job (diagnosis / trial) has finished."""
    from tests.test_qt_components import wait_until

    return wait_until(lambda: not dialog.task.busy, timeout_ms)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from accounting_converter.ui_qt.theme import APP_STYLE_SHEET

        cls.app = QApplication.instance() or QApplication([])
        cls._previous_sheet = cls.app.styleSheet()
        cls.app.setStyleSheet(APP_STYLE_SHEET)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._previous_sheet)   # the app-wide sheet must not leak into later test modules

    def _dialog(self, env, **kwargs):
        dialog = MigrationStatusDialog(controller_for(env.fixture, env.root), COMPANY, env.source)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.task.shutdown)
        for name, value in kwargs.items():
            setattr(dialog, name, value)
        if kwargs:
            dialog.refresh_items()
        return dialog

    def _select(self, dialog, *needles):
        """Select the list rows whose item ids contain any needle (like the user clicking them)."""
        dialog.item_list.clearSelection()
        first = True
        for row, entry in enumerate(dialog.entries):
            if entry[0] == "item" and any(n in entry[1].item_id for n in needles):
                if first:
                    dialog.item_list.setCurrentRow(row)
                    first = False
                dialog.item_list.item(row).setSelected(True)

    def _preview(self, dialog, *needles):
        self._select(dialog, *needles)
        dialog.preview_button.click()                                  # the real button, not run_preview(...)
        self.assertTrue(wait_idle(dialog))

    # ---------------------------------------------------------------- D0
    def test_the_trial_is_shown_after_a_real_click_and_writes_nothing(self):
        """Regression: `clicked` passes `checked` (False); the slot used to treat it as the item list."""
        from tests.test_approval_explanation import extras

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            record, catalog = extras(env)
            digest = store_digest(env.root)
            dialog = self._dialog(env, trailing_space_record=record, catalog_path=catalog)
            self.assertEqual(len([e for e in dialog.entries if e[0] == "item"]), 5)
            self.assertEqual([e for e in dialog.entries if e[0] == "guide"], [])
            self._preview(dialog, "SPLIT-V1")
            self.assertTrue(dialog.trial_banner.isVisibleTo(dialog))
            self.assertIn("試算", dialog.trial_banner.text())
            self.assertIn("保存していません", dialog.trial_banner.text())
            self.assertEqual(dialog.preview_message.level, "success")
            self.assertEqual(dialog.released_table.rowCount(), 1)
            self.assertEqual(dialog.remaining_table.rowCount(), 1)
            self.assertIn("未承認", dialog.remaining_table.item(0, 4).text())
            self.assertEqual(dialog.released_table.item(0, 1).text(), "1")   # 伝票No. and 日付 are shown
            self.assertIn("控除不可の未承認条件", dialog.preview_text.text())
            before, after = dialog.metric_now.value.text(), dialog.metric_after.value.text()
            self.assertNotEqual(before, after)
            self.assertEqual(dialog.metric_released.value.text(), "1件")
            self.assertEqual(store_digest(env.root), digest)               # read-only
            self.assertFalse(list(env.root.rglob("*.jsonl")))              # and no ledger entry
            self._preview(dialog, "NONCREDIT")
            self.assertIn("EQUIVALENCE_CONFIRMED", dialog.preview_text.text())   # missing prerequisites are shown

    def test_the_same_numbers_as_the_controller_trial(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            self._preview(dialog, "SPLIT-V1")
            _, view = dialog.controller.approval_preview_view(COMPANY, env.source, ["SPLIT-V1"])
            self.assertEqual(dialog.metric_after.value.text(), f"{view.ready_after:,} ／ {view.block_after:,}")
            self.assertEqual([dialog.released_table.item(r, 0).text() for r in range(dialog.released_table.rowCount())],
                             [str(r.source_row) for r in view.released])

    def test_switching_items_clears_the_previous_trial(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            self._preview(dialog, "SPLIT-V1")
            self.assertEqual(dialog.released_table.rowCount(), 1)
            self._select(dialog, "NONCREDIT")                              # another item, no new click
            self.assertEqual((dialog.released_table.rowCount(), dialog.remaining_table.rowCount()), (0, 0))
            self.assertFalse(dialog.trial_banner.isVisibleTo(dialog))
            self.assertEqual(dialog.metric_after.value.text(), "—")
            self.assertIn("前の試算を消しました", dialog.preview_message.text())
            self.assertEqual(dialog.preview_text.text(), "")

    def test_a_trial_still_running_when_the_selection_changes_is_never_shown(self):
        import threading

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            gate = threading.Event()
            real = dialog.controller.approval_preview_view

            def slow(*args, **kwargs):
                gate.wait(10)
                return real(*args, **kwargs)

            dialog.controller.approval_preview_view = slow
            self._select(dialog, "SPLIT-V1")
            dialog.preview_button.click()
            self.assertTrue(dialog.task.busy)
            self.assertFalse(dialog.preview_button.isEnabled())            # no second run while one is running
            self._select(dialog, "NONCREDIT")                              # switch while it runs
            gate.set()
            self.assertTrue(wait_idle(dialog))
            self.assertEqual(dialog.released_table.rowCount(), 0)          # the SPLIT result was dropped
            self.assertGreaterEqual(dialog.task.dropped, 1)
            self.assertTrue(dialog.preview_button.isEnabled())

    def test_a_result_computed_on_data_that_changed_meanwhile_is_dropped(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            real = dialog.controller.approval_preview_view

            def changes_the_source(*args, **kwargs):
                result = real(*args, **kwargs)
                env.source.write_bytes(env.source.read_bytes() + b"\r\n")   # the file changed during the job
                return result

            dialog.controller.approval_preview_view = changes_the_source
            self._preview(dialog, "SPLIT-V1")
            self.assertEqual(dialog.released_table.rowCount(), 0)
            self.assertIn("破棄しました", dialog.preview_message.text())

    def test_the_button_never_stays_silent(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            dialog.item_list.clearSelection()
            dialog.item_list.setCurrentRow(-1)
            dialog.preview_button.click()
            self.assertIn("選んでください", dialog.preview_message.text())
            guide_row = next(r for r, e in enumerate(dialog.entries) if e[0] == "guide")
            dialog.item_list.clearSelection()
            dialog.item_list.item(guide_row).setSelected(True)
            dialog.preview_button.click()
            self.assertIn("別の承認経路", dialog.preview_message.text())

            def boom(*args, **kwargs):
                raise RuntimeError("synthetic failure")

            dialog.controller.approval_preview_view = boom
            self._preview(dialog, "SPLIT-V1")
            self.assertEqual(dialog.preview_message.level, "error")
            for needle in ("試算できませんでした", "synthetic failure", "承認は記録されていません"):
                self.assertIn(needle, dialog.preview_message.text())

    def test_the_detail_is_layered_and_keeps_every_fact(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            self.assertEqual([e[1].guide_id for e in dialog.entries if e[0] == "guide"], ["TRAILING-SPACE", "POLICY"])
            nc_row = next(r for r, e in enumerate(dialog.entries) if e[0] == "item" and e[1].kind == "NONCREDIT_JOURNAL")
            dialog.item_list.setCurrentRow(nc_row)
            text = dialog.detail_text()
            for needle in ("選択した仕訳・規則の概要", "弥生での処理", "JDLで提案する処理", "失われる情報・変更点",
                           "税理士に判断してほしいこと", "承認の前に必要な確認", "未判断", "課対仕入10%", "非仕入",
                           "承認できない場合の対応候補", "EVID-YAYOI", COMPANY):
                self.assertIn(needle, text)
            self.assertFalse(dialog.details_section.is_expanded())         # Evidence and IDs are one click away
            cards = " ".join(card.body.text() for card in dialog.cards.values())
            self.assertNotIn("EVID-YAYOI", cards)
            self.assertIn("未判断", dialog.item_badge.text())
            self.assertEqual(dialog.item_badge.accessibleName(), "未判断")
            labels = [b.text() for b in dialog.findChildren(type(dialog.preview_button))]
            self.assertFalse(any("承認を記録" in label for label in labels))

    def test_works_at_1024_by_700_with_names_and_keyboard(self):
        from PySide6.QtCore import QPoint, Qt

        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = ApprovalEnv(directory)
            dialog = self._dialog(env)
            dialog.resize(1024, 700)
            dialog.show()
            QApplication.processEvents()
            self.assertLessEqual(dialog.width(), 1024)
            for widget in (dialog.preview_button, dialog.item_list):
                corner = widget.mapTo(dialog, QPoint(widget.width(), widget.height()))
                self.assertTrue(widget.isVisible())
                self.assertLessEqual(corner.x(), dialog.width(), widget.accessibleName())
                self.assertLessEqual(corner.y(), dialog.height(), widget.accessibleName())
            for button in dialog.findChildren(type(dialog.preview_button)):
                self.assertTrue(button.accessibleName(), button.text())
            for table in (dialog.released_table, dialog.remaining_table, dialog.tracker_table):
                self.assertTrue(table.accessibleName())
            self.assertEqual(dialog.preview_button.shortcut().toString(), "Ctrl+T")
            self.assertEqual(dialog.refresh_button.shortcut().toString(), "F5")
            self.assertFalse(dialog.preview_button.autoDefault())          # Enter never starts something by surprise
            dialog.tabs.setCurrentIndex(1)
            self.assertTrue(wait_idle(dialog))
            QApplication.processEvents()
            for widget in (dialog.refresh_button, dialog.start_button, dialog.export_button, dialog.tracker_table):
                corner = widget.mapTo(dialog, QPoint(widget.width(), widget.height()))
                self.assertLessEqual(corner.x(), dialog.width(), widget.accessibleName())
                self.assertGreaterEqual(widget.width(), widget.minimumSizeHint().width(), widget.accessibleName())
            self.assertEqual(dialog.tracker_table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertGreaterEqual(dialog.tracker_table.viewport().height(), 150)   # the list gets the room
            dialog.close()

    # ---------------------------------------------------------------- D2 tab: no files to pick
    def _d2(self, directory, write=True):
        from tests.test_unmigrated_view import Env

        env = Env(directory, write=write)
        dialog = MigrationStatusDialog(env.controller, COMPANY, env.run.source)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.task.shutdown)
        return env, dialog

    def _refresh(self, dialog):
        dialog.refresh_button.click()
        self.assertTrue(wait_idle(dialog))

    def _status(self, dialog, row=0):
        from accounting_converter.ui_qt.migration_status_dialog import STATUS_COLUMN

        return dialog.tracker_table.item(row, STATUS_COLUMN).text()

    def test_the_unmigrated_journals_are_shown_with_one_click_and_no_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory, write=False)             # no READY-only output, no tracker at all
            self._refresh(dialog)
            self.assertIn("READY 2", dialog.tracker_counts.text())
            self.assertIn("<b>1</b>", dialog.tracker_counts.text())
            self.assertEqual((dialog.metric_ready.value.text(), dialog.metric_blocked.value.text()), ("2", "1"))
            self.assertEqual(dialog.metric_state.value.text(), "未完了")
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            self.assertIn("未対応（管理表は未作成）", self._status(dialog))
            self.assertTrue(self._status(dialog).startswith("○"))       # a symbol, never colour alone
            for column in range(3, 8):
                self.assertTrue(dialog.tracker_table.item(0, column).text())
            self.assertIn("見つかっていません", dialog.d2_message.text())
            self.assertFalse(dialog.start_button.isEnabled())            # nothing to start management on
            self.assertTrue(dialog.export_button.isEnabled())
            self.assertIn("必要な税理士判断", dialog.journal_detail.text())   # the first journal is shown at once
            self.assertNotIn(COMPANY, dialog.journal_detail.text())       # technical details are folded away
            self.assertIn(COMPANY, dialog.tracker_technical_body.text())
            self.assertFalse(dialog.tracker_technical.is_expanded())
            self.assertFalse(list(Path(directory).rglob("*migration_tracker*")))   # viewing wrote nothing

    def test_switching_to_the_tab_loads_the_list_by_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory, write=False)
            self.assertEqual(dialog.tracker_table.rowCount(), 0)
            dialog.tabs.setCurrentIndex(1)
            self.assertTrue(wait_idle(dialog))
            self.assertEqual(dialog.tracker_table.rowCount(), 1)

    def test_the_run_next_to_the_source_is_found_and_status_management_starts_only_on_confirmation(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            self._refresh(dialog)
            self.assertIn("状態管理はまだ始まっていません", dialog.d2_message.text())
            self.assertTrue(dialog.start_button.isEnabled())
            self.assertEqual(dialog.start_button.objectName(), "primaryButton")   # the one save action of the tab
            tracker_path = mt.tracker_path_for(env.run.output)
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                dialog.start_button.click()
            self.assertFalse(tracker_path.exists())                      # declined: nothing created
            dialog.creator_edit.setText("架空担当")
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as asked:
                dialog.start_button.click()
            self.assertIn(str(tracker_path), asked.call_args.args[2])    # the message names where it will be written
            self.assertEqual(asked.call_args.args[4], QMessageBox.StandardButton.Cancel)   # default: cancel
            self.assertTrue(wait_idle(dialog))
            self.assertTrue(tracker_path.exists())
            self.assertIn("一致しています", dialog.d2_message.text())
            self.assertFalse(dialog.start_button.isEnabled())            # started once: no second start
            self.assertIn("未対応", self._status(dialog))                # nothing becomes "migrated" by itself
            self.assertNotIn("管理表は未作成", self._status(dialog))
            self.assertIn("未完了", dialog.tracker_counts.text())
            self.assertEqual((env.overview()["ready"], env.overview()["blocked"]), (2, 1))   # READY / BLOCK unchanged

    def test_an_existing_status_is_kept_when_the_screen_reopens_it(self):
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
            self._refresh(dialog)
            self.assertIn("手入力済み・未照合", self._status(dialog))      # not reconciled, not reset
            self.assertTrue(self._status(dialog).startswith("◐"))
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
            self._refresh(dialog)
            self.assertIn("使いません", dialog.d2_message.text())
            self.assertEqual(dialog.d2_message.level, "error")
            self.assertIn("未対応（管理表は未作成）", self._status(dialog))   # state not taken from it
            self.assertFalse(dialog.start_button.isEnabled())            # and no "start" that would overwrite it
            self.assertEqual(path.read_bytes(), saved)
            tracker["company_id"] = COMPANY
            path.write_text(json.dumps(tracker), encoding="utf-8")
            _edit_manifest(env.run.output, lambda m: m.update(not_migrated_journals=0))   # a tampered manifest
            self._refresh(dialog)
            self.assertIn("検証に失敗", dialog.d2_message.text())
            self.assertIn("改変", dialog.d2_message.text())
            self.assertFalse(dialog.start_button.isEnabled())
            self.assertEqual(dialog.tracker_table.rowCount(), 1)         # the list itself is still shown (from the diagnosis)

    def test_a_changed_output_does_not_reuse_the_old_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            env.controller.start_migration_tracking(COMPANY, env.run.source, env.run.output, "x", explicitly_confirmed=True)
            env.run.output.write_bytes(env.run.output.read_bytes() + b"\r\n")
            self._refresh(dialog)
            self.assertIn("出力CSVが変更されています", dialog.d2_message.text())
            self.assertIn("未対応（管理表は未作成）", self._status(dialog))

    def test_a_folder_named_once_finds_a_run_that_is_not_next_to_the_source(self):
        with tempfile.TemporaryDirectory() as directory:
            from tests.test_unmigrated_view import Env

            env = Env(directory, write=False)
            elsewhere = Path(directory) / "out"
            elsewhere.mkdir()
            env.run.output = elsewhere / "ready_only.csv"
            env.run.write()
            dialog = MigrationStatusDialog(env.controller, COMPANY, env.run.source)
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.task.shutdown)
            self._refresh(dialog)
            self.assertIn("見つかっていません", dialog.d2_message.text())
            dialog.add_folder(elsewhere)                                 # what the folder button does after the picker
            self.assertTrue(wait_idle(dialog))
            self.assertIn("状態管理はまだ始まっていません", dialog.d2_message.text())
            self.assertEqual(dialog.run_combo.count(), 1)
            self.assertFalse(mt.tracker_path_for(env.run.output).exists())

    def test_filters_sorting_and_the_csv_sheet(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as directory:
            env, dialog = self._d2(directory)
            self._refresh(dialog)
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            dialog.status_filter.setCurrentText("未対応（管理表は未作成）")
            self.assertEqual(dialog.tracker_table.rowCount(), 1)
            dialog.tracker_table.sortItems(0)                            # sorting keeps the detail in step with the row
            self.assertIn(dialog.tracker_table.item(0, 0).text(), dialog.journal_card.title.text())
            out = Path(directory) / "sheet.csv"
            self.assertTrue(dialog.export_csv(out))
            self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(dialog.d2_message.level, "success")
            with mock.patch.object(QMessageBox, "warning") as warned:   # never a real modal dialog in a test
                self.assertFalse(dialog.export_csv(out))                 # never overwrites
            self.assertTrue(warned.called)


if __name__ == "__main__":
    unittest.main()

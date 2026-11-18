"""UI Phase 5A: deleting a company setting needs its exact name (synthetic companies in a temporary AppData only).

Skipped where PySide6 is not installed; run it on Windows. The real AppData is never touched (_appdata_guard).
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_qt_settings_mapping_pages import COMPANY, PYSIDE6_AVAILABLE, PagesTestBase, listing

if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog

    from accounting_converter.ui import settings_view as sv
    from accounting_converter.ui_qt import main_window as mw

NAME = "架空商事株式会社"


class DeleteDialogTest(PagesTestBase):
    def _dialog(self, name=NAME):
        dialog = mw.CompanyDeleteDialog("company-x", name)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_button_is_enabled_only_for_the_exact_name(self):
        dialog = self._dialog()
        self.assertFalse(dialog.delete_button.isEnabled())                 # initially disabled
        self.assertIn("未入力", dialog.state_label.text())
        for typed in ("架空商事", " " + NAME, NAME + " ", "架空商事株式会社　", "架空商事㈱",
                      "ｶｸｳ", NAME.replace("株式会社", "（株）"), "x"):
            dialog.name_edit.setText(typed)
            self.assertFalse(dialog.delete_button.isEnabled(), repr(typed))   # no trimming / folding
            self.assertIn("一致しません", dialog.state_label.text())
        dialog.name_edit.setText(NAME)
        self.assertTrue(dialog.delete_button.isEnabled())
        dialog.name_edit.setText("")
        self.assertFalse(dialog.delete_button.isEnabled())

    def test_latin_names_are_case_and_width_sensitive(self):
        dialog = self._dialog("ACME Trading")
        for typed in ("acme trading", "ＡＣＭＥ Trading", "ACME  Trading"):
            dialog.name_edit.setText(typed)
            self.assertFalse(dialog.delete_button.isEnabled(), typed)
        dialog.name_edit.setText("ACME Trading")
        self.assertTrue(dialog.delete_button.isEnabled())

    def test_cancel_is_the_default_and_enter_never_deletes(self):
        dialog = self._dialog()
        self.assertTrue(dialog.cancel_button.isDefault())
        self.assertFalse(dialog.delete_button.isDefault())
        self.assertFalse(dialog.delete_button.autoDefault())
        self.assertEqual(dialog.delete_button.objectName(), "dangerButton")    # irreversible: the danger style
        dialog.show()
        dialog.name_edit.setText(NAME)
        dialog.name_edit.setFocus()
        QTest.keyClick(dialog.name_edit, Qt.Key.Key_Return)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)        # Enter = cancel
        dialog.show()
        dialog.delete_button.setFocus()
        QTest.keyClick(dialog.delete_button, Qt.Key.Key_Return)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)        # even with the button focused
        dialog.close()

    def test_the_dialog_names_the_company_and_what_is_deleted_and_kept(self):
        dialog = self._dialog()
        texts = " ".join(label.text() for label in dialog.findChildren(mw.QLabel))
        for part in (NAME, "company-x", "削除されるもの", "jdl-context.json", "削除されないもの", "変換プロファイル",
                     "承認台帳", "JDL側の会社・データ", "作成済みのJDL用CSV", "ほかの会社の設定", "取り消せません"):
            self.assertIn(part, texts)


class DeleteFlowTest(PagesTestBase):
    """Both entries (settings page, settings dialog) on a synthetic company in a temporary AppData."""

    def _typing(self, typed, click=True):
        def exec_(dialog):
            dialog.name_edit.setText(typed)
            if click and dialog.delete_button.isEnabled():
                dialog.delete_button.click()
            return dialog.result() or QDialog.DialogCode.Rejected
        return exec_

    def _companies(self, env):
        return sorted(p.name for p in env.controller.company_store.root_dir.iterdir() if p.is_dir())

    def test_a_wrong_name_or_cancel_deletes_nothing_from_the_page(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            root = Path(directory)
            before = listing(root)
            for typed, click in (("", True), ("違う会社", True), (NAME, False)):
                with self.subTest(typed=typed, click=click), \
                        mock.patch.object(mw.CompanyDeleteDialog, "exec", self._typing(typed, click)):
                    window._settings_action(sv.ACT_DELETE_COMPANY)
                self.assertEqual(listing(root), before)
            self.assertIn(COMPANY, self._companies(env))

    def test_the_exact_name_deletes_only_that_company_setting_and_keeps_the_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            store = env.controller.company_store
            name = store.get(COMPANY).display_name
            profile_files = sorted(p.name for p in env.controller.profile_store.root_dir.iterdir())
            others_before = [c for c in self._companies(env) if c != COMPANY]
            with mock.patch.object(mw.CompanyDeleteDialog, "exec", self._typing(name)):
                window._settings_action(sv.ACT_DELETE_COMPANY)
            self.assertNotIn(COMPANY, self._companies(env))
            self.assertEqual([c for c in self._companies(env) if c != COMPANY], others_before)  # other companies stay
            self.assertEqual(sorted(p.name for p in env.controller.profile_store.root_dir.iterdir()), profile_files)
            self.assertIsNone(env.controller.state.selected_company_setting_id)

    def test_the_settings_dialog_entry_uses_the_same_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory)
            calls = []
            with mock.patch.object(env.controller, "delete_company_setting", lambda cid: calls.append(cid)), \
                    mock.patch.object(mw.CompanyDeleteDialog, "exec", self._typing("違う会社")):
                self.assertFalse(mw.confirm_company_deletion(window, env.controller, COMPANY))
            self.assertEqual(calls, [])
            dialog = mw.SettingsDialog(env.controller, window)
            self.addCleanup(dialog.deleteLater)
            dialog.company_combo.setCurrentIndex(dialog.company_combo.findData(COMPANY))
            with mock.patch.object(env.controller, "delete_company_setting",
                                   lambda cid: calls.append(cid) or env.controller.state), \
                    mock.patch.object(mw.CompanyDeleteDialog, "exec", self._typing("違う会社")):
                dialog._delete_company()
            self.assertEqual(calls, [])
            name = env.controller.company_store.get(COMPANY).display_name
            with mock.patch.object(env.controller, "delete_company_setting",
                                   lambda cid: calls.append(cid) or env.controller.state), \
                    mock.patch.object(mw.CompanyDeleteDialog, "exec", self._typing(name)):
                dialog._delete_company()
            self.assertEqual(calls, [COMPANY])                                 # exactly the selected company


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QDialog

    from accounting_converter.ui_qt.main_window import (
        JdlTaxContextConfirmationDialog,
    )

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


class _Controller:
    def __init__(self, *, succeeds: bool) -> None:
        self.succeeds = succeeds
        self.calls = 0

    def confirm_company_tax_context(
        self, company_setting_id: str, *, explicitly_confirmed: bool, **selection
    ):
        self.calls += 1
        assert company_setting_id == "company-1"
        assert explicitly_confirmed
        return SimpleNamespace(
            user_message=(
                "JDL税設定を保存しました。税区分を確認してください。"
                if self.succeeds
                else "JDL税設定を保存できませんでした。科目対応を確認してください。"
            ),
            developer_error=None if self.succeeds else "SyntheticError",
        )

    def company_tax_context(self, company_setting_id: str):
        return None


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class JdlTaxContextConfirmationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_checkbox_controls_save_and_success_accepts(self) -> None:
        controller = _Controller(succeeds=True)
        dialog = JdlTaxContextConfirmationDialog(controller, "company-1")

        self.assertFalse(dialog.save_button.isEnabled())
        dialog.save_button.click()
        self.assertEqual(controller.calls, 0)

        dialog.confirmed.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.save_button.click()

        self.assertEqual(controller.calls, 1)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_simplified_first_category_is_submitted_explicitly(self) -> None:
        controller = _Controller(succeeds=True)
        dialog = JdlTaxContextConfirmationDialog(controller, "company-1")
        dialog.taxation_method.setCurrentIndex(1)
        self.assertFalse(dialog.credit_method.isVisible())
        self.assertFalse(dialog.confirmed.isChecked())
        dialog.business_category.setCurrentIndex(0)
        dialog.confirmed.setChecked(True)
        dialog.save_button.click()
        self.assertEqual(controller.calls, 1)

    def test_persistence_failure_stays_open_and_shows_error(self) -> None:
        controller = _Controller(succeeds=False)
        dialog = JdlTaxContextConfirmationDialog(controller, "company-1")
        dialog.confirmed.setChecked(True)

        with patch(
            "accounting_converter.ui_qt.main_window.QMessageBox.warning"
        ) as warning:
            dialog.save_button.click()

        self.assertEqual(controller.calls, 1)
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        warning.assert_called_once_with(
            dialog,
            "JDL税設定を保存できませんでした",
            "JDL税設定を保存できませんでした。科目対応を確認してください。",
        )


if __name__ == "__main__":
    unittest.main()

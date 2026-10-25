from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.adapters.output.jdl import (
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlInputTaxCreditMethod,
    JdlSimplifiedBusinessCategory,
    JdlTaxationMethod,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

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
    def __init__(self, *, succeeds: bool, context=None) -> None:
        self.succeeds = succeeds
        self.calls = 0
        self.context = context
        self.selection = None

    def confirm_company_tax_context(
        self, company_setting_id: str, *, explicitly_confirmed: bool, **selection
    ):
        self.calls += 1
        self.selection = selection
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
        return self.context


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
        self.assertFalse(dialog.credit_method.isHidden())
        self.assertTrue(dialog.business_category.isHidden())
        dialog.taxation_method.setCurrentIndex(1)
        self.assertTrue(dialog.credit_method.isHidden())
        self.assertFalse(dialog.credit_method.isEnabled())
        self.assertFalse(dialog.business_category.isHidden())
        self.assertTrue(dialog.business_category.isEnabled())
        self.assertFalse(dialog.confirmed.isChecked())
        dialog.business_category.setCurrentIndex(0)
        dialog.confirmed.setChecked(True)
        dialog.save_button.click()
        self.assertEqual(controller.calls, 1)
        self.assertIs(
            controller.selection["taxation_method"],
            JdlTaxationMethod.SIMPLIFIED,
        )
        self.assertIs(
            controller.selection["input_tax_credit_method"],
            JdlInputTaxCreditMethod.UNCONFIRMED,
        )
        self.assertIs(
            controller.selection["simplified_business_category"],
            JdlSimplifiedBusinessCategory.FIRST,
        )

    def test_standard_proportional_method_is_visible_and_submitted(self) -> None:
        controller = _Controller(succeeds=True)
        dialog = JdlTaxContextConfirmationDialog(controller, "company-1")
        proportional = dialog.credit_method.findData(
            JdlInputTaxCreditMethod.PROPORTIONAL.value
        )
        self.assertGreaterEqual(proportional, 0)
        dialog.accounting_method.setCurrentIndex(1)
        dialog.credit_method.setCurrentIndex(proportional)
        dialog.confirmed.setChecked(True)
        dialog.save_button.click()

        self.assertIs(
            controller.selection["tax_processing_mode"],
            JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        self.assertIs(
            controller.selection["taxation_method"],
            JdlTaxationMethod.STANDARD,
        )
        self.assertIs(
            controller.selection["input_tax_credit_method"],
            JdlInputTaxCreditMethod.PROPORTIONAL,
        )

    def test_changing_credit_method_resets_confirmation(self) -> None:
        dialog = JdlTaxContextConfirmationDialog(
            _Controller(succeeds=True), "company-1"
        )
        dialog.confirmed.setChecked(True)
        dialog.credit_method.setCurrentIndex(1)
        self.assertFalse(dialog.confirmed.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())

    def test_confirmed_context_reopens_checked_and_change_resets_confirmation(self) -> None:
        context = SimpleNamespace(
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            effective_taxation_method=JdlTaxationMethod.SIMPLIFIED,
            effective_input_tax_credit_method=JdlInputTaxCreditMethod.UNCONFIRMED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        )
        dialog = JdlTaxContextConfirmationDialog(
            _Controller(succeeds=True, context=context), "company-1"
        )

        self.assertTrue(dialog.confirmed.isChecked())
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertEqual(
            dialog.taxation_method.currentData(),
            JdlTaxationMethod.SIMPLIFIED.value,
        )
        self.assertEqual(
            dialog.business_category.currentData(),
            JdlSimplifiedBusinessCategory.FIRST.value,
        )

        dialog.business_category.setCurrentIndex(1)
        self.assertFalse(dialog.confirmed.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())

    def test_unconfirmed_context_reopens_unchecked(self) -> None:
        context = SimpleNamespace(
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            effective_taxation_method=JdlTaxationMethod.SIMPLIFIED,
            effective_input_tax_credit_method=JdlInputTaxCreditMethod.UNCONFIRMED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            confirmation_state=JdlContextConfirmationState.UNCONFIRMED,
            provenance=JdlContextProvenance.UNCONFIRMED,
        )
        dialog = JdlTaxContextConfirmationDialog(
            _Controller(succeeds=True, context=context), "company-1"
        )

        self.assertFalse(dialog.confirmed.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())

    def test_switching_back_to_standard_removes_hidden_business_category(self) -> None:
        controller = _Controller(succeeds=True)
        dialog = JdlTaxContextConfirmationDialog(controller, "company-1")
        dialog.taxation_method.setCurrentIndex(1)
        dialog.business_category.setCurrentIndex(4)
        dialog.taxation_method.setCurrentIndex(0)
        self.assertFalse(dialog.credit_method.isHidden())
        self.assertTrue(dialog.business_category.isHidden())
        dialog.confirmed.setChecked(True)
        dialog.save_button.click()
        self.assertIs(
            controller.selection["taxation_method"],
            JdlTaxationMethod.STANDARD,
        )
        self.assertIs(
            controller.selection["input_tax_credit_method"],
            JdlInputTaxCreditMethod.INDIVIDUAL,
        )
        self.assertIsNone(controller.selection["simplified_business_category"])

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

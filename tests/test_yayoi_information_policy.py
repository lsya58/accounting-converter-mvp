"""Yayoi information JDL cannot hold (付箋・生成元・部門): GUI path. Synthetic data only."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.application.yayoi_information_policy import (
    YayoiInformationField,
    YayoiInformationPolicyService,
    information_fields,
)
from accounting_converter.application.yayoi_jdl_workflow import audit_path_for
from accounting_converter.application.yayoi_review import confirmed_optional_fields
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from tests.test_yayoi_jdl_workflow import PURCHASE, YAYOI, Fixture, details
from tests.test_yayoi_journal_report_parser import detail

try:
    from PySide6.QtWidgets import QApplication, QPushButton

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False

STICKY_VALUE = "7"  # a synthetic sticky-note value


def rows_with_sticky():
    return details() + [
        detail("令和08年05月12日", 3, debit=(YAYOI["fee"], "", PURCHASE, 1100, 100),
               credit=(YAYOI["bank"], "口座A", "対象外", 1100, None), invoice="適格", credit_ratio="100%",
               description="手数料", number=3, sticky=STICKY_VALUE),
    ]


class InformationPolicyServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fixture = Fixture(self.root, rows_with_sticky())
        self.fixture.confirm_accounts()
        self.fixture.confirm_taxes()

    def tearDown(self):
        self._tmp.cleanup()

    def controller(self):
        controller = AccountingConverterController(
            profile_store=self.fixture.profiles, company_store=self.fixture.companies,
            preferences_store=ApplicationPreferencesStore(self.root / "prefs.json"),
        )
        controller.load_company_settings()
        controller.select_file(self.fixture.source)
        controller.select_company_setting("company-yayoi")
        return controller

    def profile(self):
        return self.fixture.resolved().profile

    def test_fields_are_listed_from_the_source_and_nothing_is_confirmed_by_default(self):
        fields = information_fields(self.fixture.entries, self.profile())
        self.assertEqual(fields, (YayoiInformationField("付箋1", 1, ""),))

    def test_review_lists_the_field_and_marks_the_source_as_yayoi(self):
        review = self.controller().review_company_mapping_updates("company-yayoi", self.fixture.source)
        self.assertTrue(review.source_is_yayoi)
        self.assertEqual([(field.field, field.journals, field.confirmed) for field in review.information_fields],
                         [("付箋1", 1, False)])
        # Yayoi has no trade-partner field: nothing is counted as one.
        self.assertNotIn("trade_partner", dict(review.optional_field_counts))

    def test_meaning_is_required_and_nothing_changes_on_refusal(self):
        before = self.fixture.companies.get("company-yayoi").conversion_profile_id
        service = YayoiInformationPolicyService(self.fixture.companies, self.fixture.profiles)
        for meanings in ({}, {"付箋1": "  "}):
            with self.assertRaises(ValueError):
                service.confirm("company-yayoi", meanings)
        self.assertEqual(self.fixture.companies.get("company-yayoi").conversion_profile_id, before)

    def test_confirmation_unblocks_the_journal_keeps_the_value_out_of_jdl_and_in_the_audit_file(self):
        controller = self.controller()
        controller.select_output_file(self.root / "out.csv")
        state = controller.prepare_conversion()
        self.assertFalse(state.conversion_available)
        old_profile_id = self.fixture.companies.get("company-yayoi").conversion_profile_id

        state = controller.confirm_yayoi_information_policies("company-yayoi", {"付箋1": "架空の確認印"})
        self.assertIsNone(state.developer_error, state.user_message)
        setting = self.fixture.companies.get("company-yayoi")
        self.assertNotEqual(setting.conversion_profile_id, old_profile_id)  # a new revision, bound atomically
        self.assertEqual(confirmed_optional_fields(self.fixture.profiles.get(setting.conversion_profile_id)),
                         {"付箋1": "架空の確認印"})
        self.assertEqual(confirmed_optional_fields(self.fixture.profiles.get(old_profile_id)), {})

        review = controller.review_company_mapping_updates("company-yayoi", self.fixture.source)
        self.assertEqual([field.meaning for field in review.information_fields], ["架空の確認印"])
        controller.select_company_setting("company-yayoi")
        controller.select_output_file(self.root / "out.csv")
        state = controller.prepare_conversion()
        self.assertTrue(state.conversion_available, state.messages)
        controller.execute_conversion(confirmed=True)
        output = self.root / "out.csv"
        audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
        # Preserved in the audit record, not retained in JDL.
        self.assertIn(STICKY_VALUE, json.dumps(audit, ensure_ascii=False))
        self.assertNotIn("付箋", output.read_bytes().decode("cp932"))


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class InformationPolicyDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_trade_partner_dialog_opens(self):
        """Regression: the dialog referenced an undefined name and never opened."""
        from types import SimpleNamespace

        from accounting_converter.ui_qt.main_window import TradePartnerPolicyDialog

        controller = SimpleNamespace(
            company_trade_partner_policy_state=lambda _cid: SimpleNamespace(confirmed=False, context_compatible=True)
        )
        dialog = TradePartnerPolicyDialog(controller, "company-mf")
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.confirmed.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())

    def yayoi_review(self, fields):
        from accounting_converter.application.company_mapping_update import CompanyMappingUpdateReview

        return CompanyMappingUpdateReview(
            company_setting_id="company-yayoi", source_path=None, context_path=None, items=(),
            logical_journal_count=3, optional_field_blocker_count=3,
            optional_field_counts=(("description_character", 2), ("optional_field", 1)),
            source_is_yayoi=True, information_fields=tuple(fields),
        )

    def test_yayoi_other_tab_offers_the_information_policy_not_trade_partner(self):
        from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog

        dialog = CompanyMappingUpdateDialog(object(), self.yayoi_review([YayoiInformationField("付箋1", 1)]))
        page = dialog.tabs.widget(dialog.category_tabs["other"])
        texts = [button.text() for button in page.findChildren(QPushButton)]
        self.assertIn("JDLに保持されない情報の扱いを確認…", texts)
        self.assertNotIn("取引先情報の扱いを確認", texts)
        self.assertIn("付箋1: 1仕訳 — 未確認", dialog.retention_status_label.text())
        self.assertIn("「摘要」タブ", dialog.retention_status_label.text())
        self.assertIn("JDLに保持されない情報・振替伝票入力行数: 1項目", dialog.summary_label.text())
        self.assertEqual(dialog.tabs.tabText(dialog.category_tabs["other"]), "その他 要確認")

    def test_policy_dialog_requires_meaning_check_and_acknowledgement(self):
        from types import SimpleNamespace

        from accounting_converter.ui_qt.information_policy import YayoiInformationPolicyDialog

        calls = []
        controller = SimpleNamespace(confirm_yayoi_information_policies=lambda cid, meanings: (
            calls.append((cid, dict(meanings))) or SimpleNamespace(developer_error=None, user_message="")))
        fields = (YayoiInformationField("付箋1", 2), YayoiInformationField("生成元", 5),
                  YayoiInformationField("部門", 1, "架空の部門"))
        dialog = YayoiInformationPolicyDialog(controller, "company-yayoi", fields)
        (_f1, sticky_meaning, sticky_check), (_f2, origin_meaning, origin_check), confirmed_row = dialog.rows
        self.assertEqual(confirmed_row[1:], (None, None))  # already confirmed: read-only
        self.assertEqual(sticky_meaning.text(), "")  # nothing pre-filled
        self.assertFalse(sticky_check.isEnabled())
        sticky_meaning.setText("架空の確認印")
        sticky_check.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())  # acknowledgement still missing
        dialog.acknowledge.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        origin_meaning.setText("入力だけして確認しない")
        dialog.save_button.click()
        self.assertEqual(calls, [("company-yayoi", {"付箋1": "架空の確認印"})])
        self.assertEqual(dialog.saved, {"付箋1": "架空の確認印"})
        # Editing the meaning after checking clears the check.
        sticky_meaning.setText("変更")
        self.assertFalse(sticky_check.isChecked())
        self.assertFalse(origin_check.isChecked())


if __name__ == "__main__":
    unittest.main()

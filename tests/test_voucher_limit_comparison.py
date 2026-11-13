"""Read-only production comparisons, using synthetic companies only."""
from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)
import os
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application.company_voucher_row_limit import CompanyVoucherRowLimitService
from accounting_converter.application.voucher_limit_comparison import compare_limits
from tests.test_voucher_split import card_voucher, approve
from tests.test_yayoi_scoped_workflow import make, assess, sales_voucher


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class ComparisonTest(unittest.TestCase):
    def test_read_only_and_same_as_actual_setting_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = make(directory, card_voucher(39))
            resolved = fixture.resolved()
            before = snapshot(root)
            report = compare_limits(fixture.source, resolved.profile, resolved.context)
            self.assertEqual(snapshot(root), before)
            self.assertEqual(report.formal.journal_blockers, assess(fixture)[0].journal_blockers)
            self.assertEqual(report.trials[0].approval_required, 1)
            self.assertEqual((report.journals[0].debit_lines, report.journals[0].credit_lines), (39, 1))
            self.assertEqual(report.trials[1].approval_required, 0)
            CompanyVoucherRowLimitService(fixture.companies, fixture.profiles).set(
                "company-yayoi", 64, confirmed=True)
            self.assertEqual(report.trials[1].assessment.journal_blockers, assess(fixture)[0].journal_blockers)

    def test_controller_path_has_no_state_or_store_mutation(self):
        from accounting_converter.ui.controllers import AccountingConverterController
        from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3))
            root = Path(directory)
            controller = AccountingConverterController(profile_store=fixture.profiles, company_store=fixture.companies,
                preferences_store=ApplicationPreferencesStore(root / "prefs.json"))
            before = snapshot(root)
            state = controller.state
            report = controller.compare_company_voucher_limits("company-yayoi", fixture.source)
            self.assertEqual(report.formal.ready_journals, 1)
            self.assertIs(controller.state, state)
            self.assertEqual(snapshot(root), before)

    def test_split_approval_not_borrowed_by_other_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(73))
            approve(fixture)
            resolved = fixture.resolved()
            report = compare_limits(fixture.source, resolved.profile, resolved.context)
            self.assertEqual(report.trials[0].approval_required, 0)
            self.assertEqual(report.trials[1].assessment.ready_journals, 0)
            from dataclasses import replace
            from accounting_converter.application import voucher_split
            self.assertIn("ROW_LIMIT_DIFFERS_FROM_APPROVAL", voucher_split.policy_problems(
                resolved.profile, replace(resolved.context, voucher_row_limit=64)))

    def test_interim_closing_and_unobserved_layout_stay_blocked(self):
        for rows in (card_voucher(2, closing="中決"), sales_voucher(20)):
            with self.subTest(rows=len(rows)), tempfile.TemporaryDirectory() as directory:
                fixture = make(directory, rows)
                resolved = fixture.resolved()
                report = compare_limits(fixture.source, resolved.profile, resolved.context)
                self.assertEqual(report.both_blocked, 1)

    def test_64_counts_sides_not_physical_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(64))
            resolved = fixture.resolved()
            report = compare_limits(fixture.source, resolved.profile, resolved.context)
            journal = report.journals[0]
            self.assertEqual((journal.debit_lines, journal.credit_lines, journal.physical_rows), (64, 1, 65))
            self.assertTrue(journal.over16)
            self.assertFalse(journal.over64)

    def test_wrong_source_identity_refused(self):
        from dataclasses import replace
        from accounting_converter.application.yayoi_sources import IMPORT
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, sales_voucher(3))
            resolved = fixture.resolved()
            with self.assertRaises(ValueError):
                compare_limits(fixture.source, replace(resolved.profile, source_format_identity=IMPORT.identity()),
                               resolved.context)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class ComparisonQtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_read_only_table_and_filter(self):
        from accounting_converter.ui_qt.voucher_limit_comparison import VoucherLimitComparisonDialog
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(39))
            resolved = fixture.resolved()
            before = snapshot(Path(directory))
            dialog = VoucherLimitComparisonDialog(compare_limits(fixture.source, resolved.profile, resolved.context))
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.table.rowCount(), 1)
            dialog.filter.setCurrentIndex(2)
            self.assertEqual(dialog.table.rowCount(), dialog.report.both_blocked)
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()
            self.assertEqual(snapshot(Path(directory)), before)

    def test_labels_close_button_and_duplicate_reasons(self):
        from PySide6.QtWidgets import QDialogButtonBox
        from accounting_converter.ui_qt.voucher_limit_comparison import (
            VoucherLimitComparisonDialog, reason_labels)
        self.assertEqual(reason_labels({"A", "B", "C"}, lambda c: ("同じ理由" if c != "C" else "別の理由", "")),
                         ["同じ理由", "別の理由"])
        with tempfile.TemporaryDirectory() as directory:
            fixture = make(directory, card_voucher(39))
            resolved = fixture.resolved()
            report = compare_limits(fixture.source, resolved.profile, resolved.context)
            dialog = VoucherLimitComparisonDialog(report)
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Close).text(), "閉じる")
            # The data keeps every code; only the displayed text is de-duplicated.
            self.assertEqual(dialog.report.journals[0].blockers16, report.journals[0].blockers16)
            cell = dialog.table.item(0, 3).toolTip()
            for code in report.journals[0].blockers16:
                self.assertIn(code, cell)
            self.assertFalse(dialog.table.horizontalScrollBar().isVisible() and dialog.width() > 980)
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

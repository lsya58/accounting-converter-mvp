"""UI Phase 5B: the navigation's compact / expanded widths (real clicks and keys; synthetic data only).

Skipped where PySide6 is not installed; run it on Windows. Nothing here saves a setting.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from pathlib import Path

from tests.test_qt_settings_mapping_pages import COMPANY, PYSIDE6_AVAILABLE, PagesTestBase, listing

if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    from accounting_converter.ui import home_view as hv
    from accounting_converter.ui import settings_view as sv
    from accounting_converter.ui_qt import navigation
    from accounting_converter.ui_qt.navigation import NavigationRail


class RailTest(PagesTestBase):
    def _rail(self):
        host = QWidget()
        self.addCleanup(host.deleteLater)
        rail = NavigationRail(hv.NAV_ITEMS, host, compact_items=hv.NAV_COMPACT, pending_mark=hv.NAV_PENDING_MARK)
        rail.set_current(hv.NAV_REVIEW)
        host.show()
        return host, rail

    def test_the_width_changes_the_look_only_never_the_page(self):
        _host, rail = self._rail()
        changes = []
        rail.current_changed.connect(changes.append)
        rail.follow_width(1000)
        self.assertTrue(rail.compact)
        self.assertEqual(rail.width(), navigation.COMPACT_WIDTH)
        self.assertEqual(rail.current, hv.NAV_REVIEW)
        self.assertTrue(rail.buttons[hv.NAV_REVIEW].isChecked())
        self.assertEqual(changes, [])                                   # no page switch, no diagnosis, no save
        for key, label in hv.NAV_ITEMS:
            button = rail.buttons[key]
            symbol, short = hv.NAV_COMPACT[key]
            self.assertTrue(button.text().startswith(symbol + "\n" + short))
            self.assertEqual(button.accessibleName(), label)            # the reader hears the full name
            self.assertIn(label, button.toolTip())                      # and the tooltip shows it
        rail.follow_width(1400)
        self.assertFalse(rail.compact)
        self.assertEqual([rail.buttons[k].text() for k, _ in hv.NAV_ITEMS], [label for _, label in hv.NAV_ITEMS])
        self.assertEqual(rail.current, hv.NAV_REVIEW)

    def test_the_users_choice_holds_and_the_toggle_is_keyboard_reachable(self):
        _host, rail = self._rail()
        rail.follow_width(1400)
        self.assertEqual(rail.toggle.accessibleName(), "ナビゲーションを縮小する")
        rail.toggle.setFocus()
        QTest.keyClick(rail.toggle, Qt.Key.Key_Space)
        self.assertTrue(rail.compact)
        self.assertEqual(rail.toggle.accessibleName(), "ナビゲーションを展開する")
        rail.follow_width(1600)                                         # a wide window does not undo the choice
        self.assertTrue(rail.compact)
        QTest.mouseClick(rail.toggle, Qt.MouseButton.LeftButton)
        self.assertFalse(rail.compact)
        rail.follow_width(900)
        self.assertFalse(rail.compact)
        self.assertEqual(rail.current, hv.NAV_REVIEW)

    def test_the_review_status_stays_visible_in_compact_and_counts_are_not_summed(self):
        _host, rail = self._rail()
        label, description = hv.review_nav_text(2, 22)
        rail.set_status(hv.NAV_REVIEW, label, description)
        rail.set_compact(True, user=True)
        button = rail.buttons[hv.NAV_REVIEW]
        self.assertIn(hv.NAV_PENDING_MARK, button.text())
        self.assertIn("設定2件", button.accessibleName())
        self.assertIn("判断22仕訳", button.accessibleName())
        self.assertNotIn("24", button.accessibleName() + button.toolTip())   # never a summed number
        self.assertIn("合計していません", button.toolTip())
        self.assertNotIn(hv.NAV_PENDING_MARK, rail.buttons[hv.NAV_HOME].text())
        rail.set_status(hv.NAV_REVIEW, *hv.review_nav_text(0, 0))          # nothing pending: no mark
        self.assertNotIn(hv.NAV_PENDING_MARK, button.text())
        rail.set_compact(False, user=True)
        self.assertEqual(button.text(), "要確認")

    def test_up_down_still_move_between_pages_in_compact(self):
        _host, rail = self._rail()
        rail.set_compact(True, user=True)
        rail.buttons[hv.NAV_REVIEW].setFocus()
        QTest.keyClick(rail.buttons[hv.NAV_REVIEW], Qt.Key.Key_Down)
        self.assertEqual(rail.current, hv.NAV_OUTPUT)
        QTest.keyClick(rail.buttons[hv.NAV_OUTPUT], Qt.Key.Key_Up)
        self.assertEqual(rail.current, hv.NAV_REVIEW)


class WindowNavigationTest(PagesTestBase):
    def test_resizing_keeps_the_page_company_and_source_and_starts_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            env, window = self._window(directory, size=(1400, 860))
            self.assertFalse(window.nav.compact)
            self._page(window, hv.NAV_OUTPUT)
            before = listing(Path(directory))
            state = (window.controller.state.selected_company_setting_id, window.controller.state.selected_file)
            calls = []
            original = env.controller.company_resolution_report
            env.controller.company_resolution_report = lambda *a: calls.append(a) or original(*a)
            for width in (1024, 1300, 1024):
                window.resize(width, 700)
                QTest.qWait(20)
                self.assertEqual(window.nav.compact, width < navigation.COMPACT_BELOW)
                self.assertEqual(window.current_page(), hv.NAV_OUTPUT)
                self.assertEqual((window.controller.state.selected_company_setting_id,
                                  window.controller.state.selected_file), state)
            self.assertFalse(window.reasons_task.busy)
            self.assertEqual(calls, [])                                 # no diagnosis because of a resize
            self.assertEqual(listing(Path(directory)), before)          # nothing saved
            self.assertEqual(state[0], COMPANY)
            # every page is still reachable by click and by Ctrl+1..6 in compact
            for number, (key, _label) in enumerate(hv.NAV_ITEMS, start=1):
                self._click(window.nav.buttons[key])
                self.assertEqual(window.current_page(), key)
                QTest.keyClick(window, Qt.Key.Key_1 + ((number % 6)), Qt.KeyboardModifier.ControlModifier)
                self.assertEqual(window.current_page(), hv.NAV_ITEMS[number % 6][0])
            self._idle(window)

    def test_the_settings_page_says_its_count_is_not_the_accountants(self):
        with tempfile.TemporaryDirectory() as directory:
            _env, window = self._window(directory)
            self._page(window, hv.NAV_SETTINGS)
            self.assertEqual(window.settings_page.count_note.text(), sv.COUNT_SCOPE_NOTE)
            self.assertIn("合算もしません", sv.COUNT_SCOPE_NOTE)
            self.assertTrue(window.settings_page.count_note.isVisible())


if __name__ == "__main__":
    unittest.main()

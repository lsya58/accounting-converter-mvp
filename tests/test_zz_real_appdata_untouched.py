"""Runs last: the real application data is exactly as it was before the tests (tests/_appdata_guard.py)."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests import _appdata_guard as guard

TOUCHES_APP = ("PySide6", "accounting_converter.ui_qt", "AccountingConverterController", "AccountingConverterMainWindow",
               "default_profile_store_dir", "default_company_store_dir", "default_preferences_path",
               "default_diagnostic_log_path", "log_local_exception")


class RealApplicationDataTest(unittest.TestCase):
    def test_no_real_file_or_setting_changed(self):
        self.assertEqual(guard.changes(), {}, "a test wrote into the REAL application data (see tests/_appdata_guard.py)")

    def test_no_test_hit_an_unanswered_modal_dialog(self):
        self.assertEqual(guard.UNEXPECTED_MODALS, [],
                         "a test opened a real modal dialog without answering it (patch it explicitly)")

    def test_defaults_point_into_the_temporary_folder(self):
        from accounting_converter.infrastructure.application_preferences import default_preferences_path
        from accounting_converter.infrastructure.company_setting_store import default_company_store_dir
        from accounting_converter.infrastructure.conversion_profile_store import default_profile_store_dir
        from accounting_converter.infrastructure.local_diagnostic_log import default_diagnostic_log_path

        for path in (default_profile_store_dir(), default_company_store_dir(), default_preferences_path(),
                     default_diagnostic_log_path()):
            self.assertTrue(str(path).startswith(str(guard.TEMP_ROOT)), path)

    def test_every_module_that_can_reach_application_data_imports_the_guard(self):
        missing = []
        for path in sorted(Path(__file__).parent.glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            imports = {node.module or "" for node in ast.walk(ast.parse(text)) if isinstance(node, ast.ImportFrom)}
            imports |= {alias.name for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Import)
                        for alias in node.names}
            if any(word in text for word in TOUCHES_APP) and "_appdata_guard" not in text:
                missing.append(path.name)
        self.assertEqual(missing, [], "add `from tests import _appdata_guard  # noqa: F401` at the top")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from accounting_converter.ui.view_models import UserFacingStatus
from accounting_converter.ui_qt.drop_policy import evaluate_csv_drop
from accounting_converter.ui_qt.theme import COLORS, status_visual


class QtGuiContractTests(unittest.TestCase):
    def test_runtime_dependency_and_dual_build_entries_are_declared(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("PySide6>=6.8,<7", project["project"]["dependencies"])
        script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ui_qt\\app.py", script)
        self.assertIn("ui\\app.py", script)
        self.assertIn("--collect-all", script)
        self.assertIn("TkFallback", script)

    def test_single_csv_drop_is_accepted_without_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.csv"
            path.write_bytes(b"synthetic")
            before = path.read_bytes()
            decision = evaluate_csv_drop((path,))

            self.assertTrue(decision.accepted)
            self.assertEqual(decision.accepted_path, path)
            self.assertEqual(path.read_bytes(), before)

    def test_multiple_files_are_rejected(self) -> None:
        decision = evaluate_csv_drop((Path("a.csv"), Path("b.csv")))
        self.assertFalse(decision.accepted)
        self.assertIn("1件", decision.message)

    def test_non_csv_and_directory_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "input.txt"
            text.write_text("synthetic", encoding="ascii")
            self.assertFalse(evaluate_csv_drop((text,)).accepted)
            self.assertFalse(evaluate_csv_drop((root,)).accepted)

    def test_empty_or_nonexistent_drop_is_rejected(self) -> None:
        self.assertFalse(evaluate_csv_drop(()).accepted)
        self.assertFalse(evaluate_csv_drop((Path("missing.csv"),)).accepted)

    def test_visual_tokens_cover_all_presentation_states(self) -> None:
        self.assertEqual(COLORS["surface"], "#FFFFFF")
        for status in UserFacingStatus:
            label, foreground, background = status_visual(status)
            self.assertTrue(label)
            self.assertNotEqual(foreground, background)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounting_converter.infrastructure.local_diagnostic_log import (
    default_diagnostic_log_path,
    log_local_exception,
)


class LocalDiagnosticLogTests(unittest.TestCase):
    def test_windows_path_uses_local_appdata(self) -> None:
        with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\demo\AppData\Local"}):
            self.assertEqual(
                default_diagnostic_log_path(),
                Path(r"C:\Users\demo\AppData\Local")
                / "AccountingConverter"
                / "logs"
                / "application.log",
            )

    def test_exception_is_written_locally_without_accounting_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.log"
            try:
                raise RuntimeError("synthetic dependency failure")
            except RuntimeError as error:
                result = log_local_exception(
                    "jdl_account_pdf_import", error, log_path=path
                )

            content = path.read_text(encoding="utf-8")
            self.assertEqual(result, path)
            self.assertIn("jdl_account_pdf_import", content)
            self.assertIn("RuntimeError", content)
            self.assertIn("synthetic dependency failure", content)
            self.assertNotIn("仕訳", content)

    def test_logging_failure_does_not_hide_original_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unwritable_target = Path(directory) / "already-a-directory"
            unwritable_target.mkdir()
            result = log_local_exception(
                "jdl_account_pdf_import",
                RuntimeError("synthetic"),
                log_path=unwritable_target,
            )
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

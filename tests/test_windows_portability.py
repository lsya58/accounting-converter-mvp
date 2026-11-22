"""Windows portability fixes: export-name conflicts, CRLF sheets and the release manifest order.

The byte-level checks also run on Linux (where they always held); they are the regression tests for Windows,
where the text layer used to turn CRLF into CR CR LF and Path ordering ignored case.
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from accounting_converter.application import subaccount_registration as reg
from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.tools import yayoi_noncredit_probe_check as judge
from accounting_converter.tools import yayoi_subaccount_registration as registration
from accounting_converter.ui import output_conflicts as oc
from scripts.generate_release_manifest import generate_manifest
from tests.test_noncredit_probes import manifest


def assert_crlf_sheet(test: unittest.TestCase, raw: bytes) -> None:
    test.assertTrue(raw.startswith("﻿".encode("utf-8")))
    test.assertNotIn(b"\r\r\n", raw)
    test.assertTrue(raw.endswith(b"\r\n"))
    test.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))  # every line ends in exactly CR LF
    test.assertNotIn(b"\r\n\r\n", raw)                       # no blank row


class OutputConflictTest(unittest.TestCase):
    def test_conversion_checks_the_csv_and_its_audit_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jdl.csv"
            self.assertEqual([p.name for p in oc.conversion_output_paths(output)],
                             ["jdl.csv", "jdl.csv.audit.json", "jdl.csv.audit.json.pending"])
            self.assertEqual(oc.existing_names(oc.conversion_output_paths(output)), ())
            (Path(directory) / "jdl.csv.audit.json").write_text("{}", encoding="utf-8")  # only the companion file
            self.assertEqual(oc.existing_names(oc.conversion_output_paths(output)), ("jdl.csv.audit.json",))

    def test_ready_only_checks_every_file_of_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ready.csv"
            for name in ("ready.csv.excluded.csv", "ready.csv.ready_only.json"):
                (Path(directory) / name).write_text("", encoding="utf-8")
            self.assertEqual(oc.existing_names(ro.run_paths(output)),
                             ("ready.csv.excluded.csv", "ready.csv.ready_only.json"))

    def test_message_is_the_single_refusal_text(self):
        self.assertEqual(oc.EXISTING_FILE_MESSAGE, "既存のファイルは上書きしません。別の名前を選択してください。")
        message = oc.refusal_message(("a.csv", "a.csv.audit.json"))
        self.assertTrue(message.startswith(oc.EXISTING_FILE_MESSAGE))
        self.assertIn("a.csv、a.csv.audit.json", message)
        self.assertEqual(oc.refusal_message(()), oc.EXISTING_FILE_MESSAGE)
        self.assertEqual(oc.existing_names([Path(__file__), Path(__file__)]), (Path(__file__).name,))


class CrlfSheetTest(unittest.TestCase):
    def test_noncredit_reading_sheet_has_single_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data" / "private"
            root.mkdir(parents=True)
            for batch in ("NONCREDIT_A", "NONCREDIT_B10"):
                path = root / f"YAYOI_GAP_{batch}_20260705_NOT_FOR_PRODUCTION.csv"
                path.write_bytes(b"")
                (root / (path.name + ".manifest.json")).write_text(json.dumps(manifest(batch)), encoding="utf-8")
            sheet = root / "readings.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                judge.write_sheet(root, sheet)
            raw = sheet.read_bytes()
            assert_crlf_sheet(self, raw)
            rows = raw.decode("utf-8-sig").split("\r\n")[:-1]
            self.assertEqual(rows[0].split(","), list(judge.HEADER))            # column structure unchanged
            self.assertTrue(all(row for row in rows))

    def test_subaccount_registration_sheet_has_single_crlf(self):
        row = SimpleNamespace(
            category=reg.NEW_REGISTRATION, label="合成", source_parent="合成親", source_name="合成補助",
            jdl_parent_code="9999", journals=2, matched=(), similar_for_reference=(), source_name_fits_jdl=True,
            suggested_new_name="合成補助")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "data" / "private" / "registration.csv"
            args = argparse.Namespace(output=output, company_store=Path(directory), company_id="synthetic",
                                      source=Path(directory) / "source.txt")
            with mock.patch.object(registration.shutil, "copytree"), \
                    mock.patch.object(registration, "_controller", return_value=SimpleNamespace(
                        company_store=SimpleNamespace(resolve=lambda _id: SimpleNamespace(context=None)))), \
                    mock.patch.object(registration, "_review"), \
                    mock.patch.object(registration, "build_rows", return_value=[row, row]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(registration.write(args), 0)
            raw = output.read_bytes()
            assert_crlf_sheet(self, raw)
            lines = raw.decode("utf-8-sig").split("\r\n")[:-1]
            self.assertEqual(len(lines), 3)                                     # header + 2 rows
            self.assertEqual(lines[0].split(","), list(registration.HEADER))
            self.assertEqual({len(line.split(",")) for line in lines}, {len(registration.HEADER)})


class ManifestOrderTest(unittest.TestCase):
    def test_order_is_the_posix_path_string_order_on_every_os(self):
        names = ("AccountingConverter.exe", "_internal/python312.dll", "_internal/PySide6/Qt6Core.dll",
                 "_internal/base_library.zip", "Zeta.txt", "alpha.txt", "_internal/_ssl.pyd", "B/a.txt", "a/B.txt")
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            for name in names:
                path = artifact_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode("utf-8"))
            result = generate_manifest(artifact_dir=artifact_dir, git_commit="a" * 40, project_version="0.1.0",
                                       python_version="3.12", pyinstaller_version="6", dependencies=())
            paths = [item["path"] for item in result["files"]]
            self.assertEqual(paths, sorted(names))                      # code-point order, case-sensitive
            self.assertEqual(paths[0], "AccountingConverter.exe")       # upper case before "_" before lower case
            self.assertLess(paths.index("Zeta.txt"), paths.index("_internal/python312.dll"))
            self.assertLess(paths.index("_internal/python312.dll"), paths.index("alpha.txt"))
            # content unchanged: every file listed once with its own hash and size
            self.assertEqual(len(paths), len(set(paths)))
            for item in result["files"]:
                self.assertEqual(item["size_bytes"], len(item["path"].encode("utf-8")))


if __name__ == "__main__":
    unittest.main()

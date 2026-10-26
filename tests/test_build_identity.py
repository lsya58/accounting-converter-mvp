from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from accounting_converter.application.build_identity import current_build_identity


class BuildIdentityTests(unittest.TestCase):
    def test_reads_packaged_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "release_manifest.json"
            manifest.write_text(
                json.dumps({
                    "project_version": "0.1.0",
                    "git_commit": "a" * 40,
                }),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"ACCOUNTING_CONVERTER_RELEASE_MANIFEST": str(manifest)},
            ):
                result = current_build_identity()

        self.assertEqual(result.version, "0.1.0")
        self.assertEqual(result.commit, "a" * 40)
        self.assertEqual(result.identifier, "0.1.0+aaaaaaaaaaaa")

    def test_missing_or_invalid_manifest_is_visibly_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with patch.dict(
                os.environ,
                {"ACCOUNTING_CONVERTER_RELEASE_MANIFEST": str(missing)},
            ):
                result = current_build_identity()

        self.assertEqual(result.commit, "不明")
        self.assertTrue(result.identifier.endswith("+unverified"))

    def test_packaged_executable_reads_adjacent_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            executable = artifact / "AccountingConverter.exe"
            executable.write_bytes(b"synthetic")
            (artifact / "release_manifest.json").write_text(
                json.dumps({
                    "project_version": "0.1.0",
                    "git_commit": "b" * 40,
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True), patch(
                "accounting_converter.application.build_identity.sys.executable",
                str(executable),
            ):
                result = current_build_identity()

        self.assertEqual(result.commit, "b" * 40)
        self.assertEqual(result.identifier, "0.1.0+bbbbbbbbbbbb")

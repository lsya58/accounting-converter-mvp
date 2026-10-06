from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_release_manifest import (
    BUILD_INFO_NAME,
    MANIFEST_NAME,
    generate_manifest,
    sha256_file,
    write_manifest,
)


class ReleaseManifestTest(unittest.TestCase):
    def test_manifest_records_provenance_and_bundle_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            executable = artifact_dir / "AccountingConverter.exe"
            executable.write_bytes(b"synthetic executable")
            internal = artifact_dir / "_internal" / "python312.dll"
            internal.parent.mkdir()
            internal.write_bytes(b"synthetic runtime")

            manifest = generate_manifest(
                artifact_dir=artifact_dir,
                git_commit="a" * 40,
                project_version="0.1.0",
                python_version="3.12.10",
                pyinstaller_version="6.16.0",
                dependencies=[
                    {"name": "setuptools", "version": "80.0.0"},
                    {"name": "PyInstaller", "version": "6.16.0"},
                ],
                built_at="2026-10-06T00:00:00+00:00",
            )

            self.assertEqual(manifest["executable_sha256"], sha256_file(executable))
            self.assertEqual(manifest["git_commit"], "a" * 40)
            self.assertEqual(len(manifest["files"]), 2)
            self.assertEqual(manifest["files"][0]["path"], "AccountingConverter.exe")
            self.assertNotIn(str(artifact_dir), json.dumps(manifest))

    def test_written_metadata_is_excluded_from_bundle_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_dir = Path(directory)
            (artifact_dir / "AccountingConverter.exe").write_bytes(b"binary")
            manifest = generate_manifest(
                artifact_dir=artifact_dir,
                git_commit="b" * 40,
                project_version="0.1.0",
                python_version="3.12.10",
                pyinstaller_version="6.16.0",
                dependencies=[],
                built_at="2026-10-06T00:00:00+00:00",
            )
            write_manifest(artifact_dir, manifest)

            written = json.loads((artifact_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
            paths = {item["path"] for item in written["files"]}
            self.assertNotIn(MANIFEST_NAME, paths)
            self.assertNotIn(BUILD_INFO_NAME, paths)
            self.assertTrue((artifact_dir / BUILD_INFO_NAME).is_file())

    def test_missing_executable_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "AccountingConverter.exe"):
                generate_manifest(
                    artifact_dir=Path(directory),
                    git_commit="c" * 40,
                    project_version="0.1.0",
                    python_version="3.12.10",
                    pyinstaller_version="6.16.0",
                    dependencies=[],
                )


if __name__ == "__main__":
    unittest.main()

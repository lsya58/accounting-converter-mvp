from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


MANIFEST_NAME = "release_manifest.json"
BUILD_INFO_NAME = "BUILD_INFO.txt"
EXCLUDED_NAMES = {MANIFEST_NAME, BUILD_INFO_NAME}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_manifest(
    artifact_dir: Path,
    git_commit: str,
    project_version: str,
    python_version: str,
    pyinstaller_version: str,
    dependencies: Sequence[dict[str, Any]],
    built_at: str | None = None,
) -> dict[str, Any]:
    executable = artifact_dir / "AccountingConverter.exe"
    if not executable.is_file():
        raise ValueError("AccountingConverter.exe was not found in the artifact directory")
    if len(git_commit) != 40 or any(character not in "0123456789abcdef" for character in git_commit):
        raise ValueError("git_commit must be a lowercase 40-character SHA-1")

    files = []
    for path in sorted(candidate for candidate in artifact_dir.rglob("*") if candidate.is_file()):
        if path.name in EXCLUDED_NAMES:
            continue
        files.append(
            {
                "path": path.relative_to(artifact_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )

    return {
        "schema_version": "1",
        "product": "AccountingConverter",
        "project_version": project_version,
        "git_commit": git_commit,
        "built_at_utc": built_at or datetime.now(timezone.utc).isoformat(),
        "python_version": python_version,
        "pyinstaller_version": pyinstaller_version,
        "build_dependencies": sorted(
            (
                {"name": str(item["name"]), "version": str(item["version"])}
                for item in dependencies
            ),
            key=lambda item: item["name"].casefold(),
        ),
        "executable_sha256": sha256_file(executable),
        "files": files,
    }


def write_manifest(artifact_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path = artifact_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    info = (
        "AccountingConverter build provenance\n"
        f"Git commit: {manifest['git_commit']}\n"
        f"Build time (UTC): {manifest['built_at_utc']}\n"
        f"Python: {manifest['python_version']}\n"
        f"PyInstaller: {manifest['pyinstaller_version']}\n"
        f"AccountingConverter.exe SHA-256: {manifest['executable_sha256']}\n"
        "\nVerify the release_manifest.json file list before distribution.\n"
    )
    (artifact_dir / BUILD_INFO_NAME).write_text(info, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Windows release provenance files.")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--project-version", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--pyinstaller-version", required=True)
    parser.add_argument("--dependencies-json", type=Path, required=True)
    args = parser.parse_args(argv)

    dependencies = json.loads(args.dependencies_json.read_text(encoding="utf-8-sig"))
    if not isinstance(dependencies, list):
        raise ValueError("dependencies JSON must contain a list")
    manifest = generate_manifest(
        artifact_dir=args.artifact_dir,
        git_commit=args.git_commit,
        project_version=args.project_version,
        python_version=args.python_version,
        pyinstaller_version=args.pyinstaller_version,
        dependencies=dependencies,
    )
    write_manifest(args.artifact_dir, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

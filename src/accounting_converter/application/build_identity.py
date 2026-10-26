from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from accounting_converter import __version__


@dataclass(frozen=True)
class BuildIdentity:
    version: str
    commit: str
    identifier: str


def current_build_identity() -> BuildIdentity:
    """Read release provenance without exposing paths or host information."""
    manifest = _release_manifest_path()
    if manifest is not None:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
            version = str(payload["project_version"])
            commit = str(payload["git_commit"])
            if (
                len(commit) == 40
                and all(character in "0123456789abcdef" for character in commit)
            ):
                return BuildIdentity(
                    version=version,
                    commit=commit,
                    identifier=f"{version}+{commit[:12]}",
                )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return BuildIdentity(
        version=__version__,
        commit="不明",
        identifier=f"{__version__}+unverified",
    )


def _release_manifest_path() -> Path | None:
    override = os.environ.get("ACCOUNTING_CONVERTER_RELEASE_MANIFEST")
    if override:
        return Path(override)
    candidates = (
        Path(sys.executable).resolve().parent / "release_manifest.json",
        Path(__file__).resolve().parents[3] / "release_manifest.json",
    )
    return next((path for path in candidates if path.is_file()), None)

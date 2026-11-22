"""Which files an export would create, and which of them already exist (Qt-free, read-only).

The application never overwrites an export (every writer is called with overwrite=False and refuses an
existing file itself). The save dialogs therefore do not ask the operating system's "replace?" question
(that answer could never be honoured); instead the screen checks right after the choice whether the CSV or
any companion file (audit record, excluded list, manifest, temporary files) already exists, and says so
once. The writers' own refusal stays: this is an earlier, friendlier stop, not the protection.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from accounting_converter.application.yayoi_jdl_workflow import audit_path_for, pending_audit_path_for

EXISTING_FILE_MESSAGE = "既存のファイルは上書きしません。別の名前を選択してください。"


def conversion_output_paths(output: Path) -> tuple[Path, ...]:
    """The formal conversion CSV and the audit record files the Yayoi route writes next to it.

    The other routes write only the CSV; checking the audit names for them too is conservative (an
    unrelated file with such a name next to the chosen CSV also stops the choice)."""
    return output, audit_path_for(output), pending_audit_path_for(output)


def existing_names(paths: Iterable[Path]) -> tuple[str, ...]:
    """File names (no folders) of the paths that already exist, in the given order, without repeats."""
    return tuple(dict.fromkeys(path.name for path in paths if path.exists()))


def refusal_message(existing: Iterable[str]) -> str:
    names = tuple(existing)
    return EXISTING_FILE_MESSAGE + (f"（既にあるファイル: {'、'.join(names)}）" if names else "")

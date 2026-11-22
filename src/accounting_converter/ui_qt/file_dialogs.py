"""Save dialogs for exports that are never overwritten.

`QFileDialog.Option.DontConfirmOverwrite` turns off the operating system's "replace?" question, because the
application refuses every existing file anyway (see ui.output_conflicts). The caller receives the chosen
path and the names of the files that already exist, and shows one message. Whether the Windows native
dialog really skips its question is only verified on a real Windows screen, not by the offscreen tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtWidgets import QFileDialog, QWidget

from accounting_converter.ui.output_conflicts import existing_names

SAVE_OPTIONS = QFileDialog.Option.DontConfirmOverwrite


def choose_new_file(
    parent: QWidget | None,
    caption: str,
    file_filter: str,
    *,
    related_paths: Callable[[Path], Iterable[Path]] = lambda path: (path,),
    suffix: str | None = None,
) -> tuple[Path | None, tuple[str, ...]]:
    """(chosen path or None when cancelled, names of the files of that export that already exist)."""
    chosen, _ = QFileDialog.getSaveFileName(parent, caption, "", file_filter, "", SAVE_OPTIONS)
    if not chosen:
        return None, ()
    path = Path(chosen)
    if suffix is not None and path.suffix.lower() != suffix:
        path = path.with_suffix(suffix)
    return path, existing_names(related_paths(path))

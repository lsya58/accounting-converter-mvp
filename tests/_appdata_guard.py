"""Keeps every test away from the real application data, and proves it.

Imported (for its side effect) by every test module that touches the GUI, the controller or default paths. On first
import it:
  1. records the SHA-256 of every file under the REAL application folders (Windows %LOCALAPPDATA% / %APPDATA%
     AccountingConverter, and the Linux ~/.local fallbacks) and, where PySide6 is installed, the real UI settings
     (QSettings, the Windows registry);
  2. points LOCALAPPDATA / APPDATA at a temporary folder and ACCOUNTING_CONVERTER_SETTINGS_FILE at a temporary INI
     file, so default stores, preferences, the diagnostic log, the approval ledger and UI settings all land there;
  3. replaces the blocking Qt dialogs (QMessageBox, QFileDialog, QInputDialog, QDialog.exec) by safe answers
     (No / Cancel / no file) that are RECORDED: a test that wants an answer patches it explicitly (mock.patch).

tests/test_zz_real_appdata_untouched.py runs last and FAILS if any real file or setting changed, or if any test hit a
real modal dialog without answering it. Existing real files are only read, never deleted or rewritten.
"""
from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

_ORIGINAL_ENV = {key: os.environ.get(key) for key in ("LOCALAPPDATA", "APPDATA")}
UNEXPECTED_MODALS: list[str] = []


def real_roots() -> tuple[Path, ...]:
    roots = [Path(value) / "AccountingConverter" for value in _ORIGINAL_ENV.values() if value]
    home = Path.home()
    roots += [home / ".local" / "share" / "accounting-converter", home / ".local" / "state" / "AccountingConverter"]
    return tuple(dict.fromkeys(roots))


def file_digests() -> dict[str, str]:
    found = {}
    for root in real_roots():
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            try:
                found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:   # a file another process holds open: compare the error instead
                found[str(path)] = f"unreadable:{type(error).__name__}"
    return found


def native_settings() -> dict[str, str] | None:
    """The real UI settings (registry on Windows); None where PySide6 is not installed."""
    try:
        from PySide6.QtCore import QSettings
    except ModuleNotFoundError:
        return None
    settings = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, "AccountingConverter",
                         "AccountingConverter")
    return {key: repr(settings.value(key)) for key in sorted(settings.allKeys())}


BEFORE_FILES = file_digests()
BEFORE_SETTINGS = native_settings()

_TEMP = Path(tempfile.mkdtemp(prefix="ac_test_appdata_"))
os.environ["LOCALAPPDATA"] = str(_TEMP / "Local")
os.environ["APPDATA"] = str(_TEMP / "Roaming")
os.environ["ACCOUNTING_CONVERTER_SETTINGS_FILE"] = str(_TEMP / "settings.ini")
TEMP_ROOT = _TEMP
atexit.register(lambda: shutil.rmtree(_TEMP, ignore_errors=True))


def changes() -> dict:
    """What changed in the real application data since the first import (empty when nothing did)."""
    after = file_digests()
    result = {
        "added": sorted(set(after) - set(BEFORE_FILES)),
        "removed": sorted(set(BEFORE_FILES) - set(after)),
        "changed": sorted(k for k in set(after) & set(BEFORE_FILES) if after[k] != BEFORE_FILES[k]),
    }
    settings = native_settings()
    if BEFORE_SETTINGS is not None and settings != BEFORE_SETTINGS:
        result["settings"] = sorted(set(settings or {}) ^ set(BEFORE_SETTINGS)
                                    | {k for k in set(settings or {}) & set(BEFORE_SETTINGS)
                                       if settings[k] != BEFORE_SETTINGS[k]})
    return {k: v for k, v in result.items() if v}


def _install_modal_guard() -> None:
    try:
        from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
    except ModuleNotFoundError:
        return

    def answer(name, value):
        def respond(*_args, **_kwargs):
            UNEXPECTED_MODALS.append(name)
            return value
        return staticmethod(respond)

    no, ok = QMessageBox.StandardButton.No, QMessageBox.StandardButton.Ok
    for name, value in (("question", no), ("warning", ok), ("information", ok), ("critical", ok)):
        setattr(QMessageBox, name, answer(f"QMessageBox.{name}", value))
    for name, value in (("getOpenFileName", ("", "")), ("getSaveFileName", ("", "")),
                        ("getOpenFileNames", ([], "")), ("getExistingDirectory", "")):
        setattr(QFileDialog, name, answer(f"QFileDialog.{name}", value))
    for name, value in (("getText", ("", False)), ("getItem", ("", False)), ("getInt", (0, False))):
        setattr(QInputDialog, name, answer(f"QInputDialog.{name}", value))

    def dialog_exec(self, *_args):
        UNEXPECTED_MODALS.append(f"{type(self).__name__}.exec")
        return int(QDialog.DialogCode.Rejected)

    QDialog.exec = dialog_exec
    QMessageBox.exec = dialog_exec


_install_modal_guard()

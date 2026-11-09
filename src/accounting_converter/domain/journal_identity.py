"""Stable journal identity for Evidence matching.

Evidence must follow the journal's accounting content, not where it came from.
The identity therefore excludes file name, path, physical row numbers and
source-local transaction numbers: re-exporting the same journal under another
file name keeps the identity, while any change to date, sides, accounts,
subaccounts, amounts, tax fields or descriptions produces a new one.
"""
from __future__ import annotations

import hashlib
import json
from typing import Sequence

from .journal import JournalEntry

JOURNAL_CONTENT_IDENTITY_KEY = "source_journal_content_sha256"


def journal_content_identity(source_format: str, date_iso: str, rows: Sequence[Sequence[str]]) -> str:
    payload = {"format": source_format, "date": date_iso, "rows": [list(row) for row in rows]}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_journal_identity(entry: JournalEntry) -> str | None:
    value = entry.metadata.get(JOURNAL_CONTENT_IDENTITY_KEY)
    return value if isinstance(value, str) and len(value) == 64 else None


# Each line of a parsed Yayoi journal also carries its journal's content identity, so that a decision taken for ONE
# journal (e.g. the 控除不可 sign-off, application/noncredit_approval.py) can be checked where only the line is at hand.
LINE_JOURNAL_IDENTITY_KEY = "line_journal_content_sha256"


def stamp_line_journal_identity(entry: JournalEntry) -> JournalEntry:
    identity = stable_journal_identity(entry)
    if identity is not None:
        for line in entry.lines:
            line.metadata = {**line.metadata, LINE_JOURNAL_IDENTITY_KEY: identity}
    return entry


def line_journal_identity(line) -> str | None:
    value = (getattr(line, "metadata", None) or {}).get(LINE_JOURNAL_IDENTITY_KEY)
    return value if isinstance(value, str) and len(value) == 64 else None

"""Source-neutral record of information a source carries beyond accounts, amounts and tax.

Why this exists: each existing source keeps such information under its own metadata keys
(Money Forward: ``moneyforward_tags`` / ``moneyforward_memos`` / ``moneyforward_trade_partner``;
Yayoi: ``yayoi_optional_values`` / ``yayoi_closing`` …). A target that cannot hold a value has to
know that the value exists, never silently drop it (fail-closed). New sources fill the keys below;
existing sources are NOT rewritten (their parsers and outputs stay byte-identical) and are read
through `legacy_source_fields`, read-only.

- entry.metadata[ENTRY_SOURCE_FIELDS_KEY]: tuple[SourceFieldValue, ...]
    every non-empty source value that is not an account / subaccount / department / amount /
    tax category / tax amount / date / description of the common model, including columns the
    parser does not know (``known=False``). Nothing is dropped.
- entry.metadata[ENTRY_CLOSING_ADJUSTMENT_KEY]: str
    the source's raw closing-adjustment marker (決算整理). Its meaning is source-specific and is
    NOT interpreted here; a target needs its own Evidence before writing a closing entry.
- entry.metadata[ENTRY_SOURCE_FORMAT_KEY]: str
    stable key of the exact source format variant the entry was read from.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .journal import JournalEntry

ENTRY_SOURCE_FIELDS_KEY = "journal_source_fields"
ENTRY_CLOSING_ADJUSTMENT_KEY = "journal_closing_adjustment"
ENTRY_SOURCE_FORMAT_KEY = "journal_source_format"


class SourceFieldScope(str, Enum):
    JOURNAL = "JOURNAL"  # one value for the whole journal (e.g. 管理番号)
    ROW = "ROW"  # one value per physical row
    DEBIT = "DEBIT"  # belongs to the debit side of a row
    CREDIT = "CREDIT"  # belongs to the credit side of a row


@dataclass(frozen=True)
class SourceFieldValue:
    field: str  # the source's own column / field name, verbatim
    value: str
    scope: SourceFieldScope
    row_number: int | None = None
    known: bool = True  # False: the parser does not know this column's meaning


def source_fields(entry: JournalEntry) -> tuple[SourceFieldValue, ...]:
    """Values recorded under the neutral key (sources that fill it)."""
    values = entry.metadata.get(ENTRY_SOURCE_FIELDS_KEY, ())
    return tuple(value for value in values if isinstance(value, SourceFieldValue))


def legacy_source_fields(entry: JournalEntry) -> tuple[SourceFieldValue, ...]:
    """Read-only view of the source-specific keys of the EXISTING sources.

    Only reads what the existing parsers already put on the entry; it does not change them and is
    not used by any existing conversion path. Covers the keys the existing JDL loss rules look at.
    """
    found: list[SourceFieldValue] = list(source_fields(entry))
    metadata = entry.metadata
    for key, field in (("moneyforward_tags", "タグ"), ("moneyforward_memos", "メモ")):
        for item in metadata.get(key, ()) or ():
            if isinstance(item, dict) and item.get("value"):
                found.append(SourceFieldValue(field, str(item["value"]), SourceFieldScope.ROW, item.get("row_number")))
    for line in entry.lines:
        partner = line.metadata.get("moneyforward_trade_partner")
        if partner:
            found.append(SourceFieldValue(
                "取引先", str(partner), SourceFieldScope(line.side.value), line.source_reference.row_number,
            ))
    for item in metadata.get("yayoi_optional_values", ()) or ():
        if isinstance(item, (tuple, list)) and len(item) == 3 and item[2]:
            row, name, value = item
            found.append(SourceFieldValue(str(name), str(value), SourceFieldScope.ROW, row if isinstance(row, int) else None))
    return tuple(found)


def closing_adjustment_marker(entry: JournalEntry) -> str | None:
    value = entry.metadata.get(ENTRY_CLOSING_ADJUSTMENT_KEY)
    return value if isinstance(value, str) and value else None

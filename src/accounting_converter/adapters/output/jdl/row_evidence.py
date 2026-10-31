"""JDL target Evidence for row-specific descriptions.

Which (debit lines, credit lines, physical rows) shapes JDL IBEX 出納帳 35.5 was
shown, by real Import and re-export, to keep with one description per physical
row and unchanged row order. This is a property of JDL, not of the source: any
source that fills the common row semantics (domain.journal_rows) can use it.
"""
from __future__ import annotations

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.journal_rows import (
    PhysicalRow,
    journal_physical_rows,
    physical_row_shape,
)

JDL_ROW_DESCRIPTION_VERIFIED_SHAPES = frozenset(
    {
        (1, 3, 3),
        (1, 2, 2),
        (2, 2, 2),
        (2, 1, 2),
        (2, 3, 3),
        (4, 6, 6),
        (4, 6, 10),
        (5, 7, 7),
        (5, 7, 12),
        (5, 8, 8),
        (5, 8, 13),
        (10, 9, 10),  # 0877 10D9C row descriptions, strict PASS
    }
)


def jdl_row_description_rows(
    entry: JournalEntry,
    *,
    additional_shapes: frozenset[tuple[int, int, int]] = frozenset(),
) -> tuple[PhysicalRow, ...] | None:
    """Physical rows when their shape has JDL row-description Evidence.

    additional_shapes is only for NOT_FOR_PRODUCTION probe generation.
    """
    rows = journal_physical_rows(entry)
    if rows is None:
        return None
    if physical_row_shape(rows) not in JDL_ROW_DESCRIPTION_VERIFIED_SHAPES | additional_shapes:
        return None
    return rows

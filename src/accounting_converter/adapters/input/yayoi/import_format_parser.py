"""Strict parser for the Yayoi 弥生インポート形式 (25 columns, identifier flags).

Built on the existing observed AE19 parser (flags 2000/2111 single row,
2110 → 2100* → 2101 multi-row), and adds what the JDL workflow needs:

- common row semantics (row number and row description per physical row),
  so rows with different descriptions are kept instead of rejected;
- a unique journal id (voucher numbers can repeat) and a content identity
  that does not depend on the file name or voucher number;
- detection of information JDL cannot keep (付箋, 生成元, 期日, 番号, 仕訳メモ)
  and of closing entries; and fail-closed checks on values whose meaning is
  not observed (タイプ, 調整).

Unlike the 仕訳日記帳 report, there are no 請求書区分 / 仕入税額控除 columns:
the invoice attribute is part of the 税区分 name itself, so the tax identity
is the 税区分 as written.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.journal_identity import (
    JOURNAL_CONTENT_IDENTITY_KEY,
    journal_content_identity,
)
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
)

from .observed_parser import (
    YayoiObservedSingleRecordParser,
    YayoiObservedSingleRecordParserError,
    YayoiObservedSingleRecordRow,
)

SOURCE_FORMAT = "yayoi_import_format"
# Official meaning: タイプ 0=仕訳 1=出金 2=入金 3=振替伝票; 調整 yes/no.
# Only values seen in real exports are accepted.
OBSERVED_TYPE = frozenset({"0", "3"})
OBSERVED_ADJUSTMENT = frozenset({"no"})
# Fields with no place in the JDL import; a value other than the empty/default one is reported.
OPTIONAL_TEXT_FIELDS = ("番号", "期日", "生成元", "仕訳メモ")
OPTIONAL_FLAG_FIELDS = ("付箋1", "付箋2")
_IDENTITY_EXCLUDED_POSITIONS = {2}  # 伝票No.


class YayoiImportFormatParseError(YayoiObservedSingleRecordParserError):
    pass


@dataclass(frozen=True)
class YayoiImportFormatResult:
    entries: tuple[JournalEntry, ...]
    issues: tuple[str, ...]
    detail_rows: int

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def rejected_journals(self) -> int:
        return 0 if self.ok else 1


class YayoiImportFormatParser(YayoiObservedSingleRecordParser):
    def parse_path(self, path: Path) -> tuple[JournalEntry, ...]:
        try:
            return super().parse_path(path)
        except YayoiObservedSingleRecordParserError as exc:
            raise YayoiImportFormatParseError(str(exc)) from exc

    def diagnose(self, path: Path) -> YayoiImportFormatResult:
        """Whole-file fail-closed: any issue rejects every journal."""
        try:
            rows = self.record_count(path)
        except YayoiObservedSingleRecordParserError as exc:
            return YayoiImportFormatResult((), (str(exc),), 0)
        try:
            return YayoiImportFormatResult(self.parse_path(path), (), rows)
        except YayoiImportFormatParseError as exc:
            return YayoiImportFormatResult((), (str(exc),), rows)

    def _entry_from_rows(
        self,
        file_name: str,
        rows: tuple[YayoiObservedSingleRecordRow, ...],
    ) -> JournalEntry:
        first = rows[0]
        optional: dict[str, int] = {}
        optional_values: list[tuple[int, str, str]] = []
        for row in rows:
            if row.value(self._position("タイプ")) not in OBSERVED_TYPE:
                raise YayoiObservedSingleRecordParserError(
                    f"Yayoi import row {row.row_number} has unobserved タイプ"
                )
            if row.value(self._position("調整")) not in OBSERVED_ADJUSTMENT:
                raise YayoiObservedSingleRecordParserError(
                    f"Yayoi import row {row.row_number} has unobserved 調整"
                )
            for name in OPTIONAL_TEXT_FIELDS:
                if row.value(self._position(name)):
                    optional[name] = optional.get(name, 0) + 1
                    optional_values.append((row.row_number, name, row.value(self._position(name))))
            for name in OPTIONAL_FLAG_FIELDS:
                flag = row.value(self._position(name))
                if flag and not (flag.isdigit() and int(flag) == 0):  # blank / 0 / 000 = none
                    optional[name] = optional.get(name, 0) + 1
                    optional_values.append((row.row_number, name, row.value(self._position(name))))
        entry_id = f"yayoi-import:{file_name}:{first.row_number}"
        lines = []
        for row in rows:
            for line in self._lines_from_row(file_name, row):
                lines.append(replace(line, metadata={
                    **line.metadata,
                    LINE_ROW_KEY: row.row_number,
                    LINE_ROW_DESCRIPTION_KEY: row.value(self._position("摘要")),
                }))
        if not lines:
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi import row {first.row_number} produced no journal lines"
            )
        descriptions = {row.value(self._position("摘要")) for row in rows}
        journal_date = self._date(first.value(self._position("取引日付")), first.row_number)
        entry = JournalEntry(
            id=entry_id,
            source_reference=replace(lines[0].source_reference, row_number=first.row_number),
            date=journal_date,
            description=(next(iter(descriptions)) or None) if len(descriptions) == 1 else None,
            lines=lines,
            metadata={
                "source": SOURCE_FORMAT,
                "identifier_flags": tuple(row.value(1) for row in rows),
                ROW_ORDER_KEY: tuple(row.row_number for row in rows),
                JOURNAL_CONTENT_IDENTITY_KEY: journal_content_identity(
                    SOURCE_FORMAT,
                    journal_date.isoformat(),
                    tuple(
                        tuple(
                            value.strip() for position, value in enumerate(row.columns, 1)
                            if position not in _IDENTITY_EXCLUDED_POSITIONS
                        )
                        for row in rows
                    ),
                ),
                "yayoi_voucher_number": first.value(self._position("伝票No.")),
                "yayoi_closing": first.value(self._position("決算")),
                "yayoi_type": tuple(dict.fromkeys(row.value(self._position("タイプ")) for row in rows)),
                "yayoi_optional_fields": optional,
                # (row, field, value): kept for the audit record of what JDL cannot hold.
                "yayoi_optional_values": tuple(optional_values),
            },
        )
        if not entry.is_balanced():
            raise YayoiObservedSingleRecordParserError(
                f"Yayoi import journal starting at row {first.row_number} is not balanced"
            )
        return entry


def looks_like_yayoi_import_format(path: Path) -> bool:
    """True when the first record starts with a Yayoi identifier flag (no report preamble)."""
    head = path.read_bytes()[:16]
    return any(head.startswith(flag) for flag in (
        b"2000,", b"2110,", b"2111,", b'"2000",', b'"2110",', b'"2111",'
    ))

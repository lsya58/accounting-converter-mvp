"""Strict parser for the Yayoi 「仕訳日記帳」 report exported in 汎用形式.

This is a report export, not the Yayoi import format: it has a preamble
(帳票名 / 書式名 / 事業所名 / 処理日時 / 検索条件 / 集計期間 / 当日仕訳), a
`[表題行]` header with 31 columns, `[明細行]` detail rows, and `[日次合計行]` /
`[月度合計行]` totals. There are no 2000/2111/2110 identifier flags.

Observed rules (real export, 2026-11-01):
- CP932, CRLF, comma-delimited, standard CSV quoting, no BOM.
- Dates are 令和YY年MM月DD日.
- One journal = consecutive detail rows with the same date and 伝票No.
  伝票No. alone is not unique (it is reused on other dates).
- A detail row carries a debit side, a credit side, or both. An absent side
  has every column empty except 税区分 = 対象外.
- 税額 is explicit and already reflects the export's own rules (rounding,
  and for 経過措置 rows the purchase-credit ratio). It is kept as given.
- Daily and monthly totals equal the sums of the detail rows above them.

`parse_path` is fail-closed: any issue raises. `diagnose` returns the journals
that parsed cleanly plus every issue, for analysis only (never formal output).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.domain.journal_identity import (
    JOURNAL_CONTENT_IDENTITY_KEY,
    stamp_line_journal_identity,
    journal_content_identity,
)
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
)

SOURCE_FORMAT = "yayoi_journal_report_generic"
REPORT_NAME = "仕訳日記帳"
FORMAT_NAME = "汎用形式"
PREAMBLE_KEYS = ("帳票名", "書式名", "事業所名", "処理日時", "検索条件", "集計期間", "当日仕訳")
HEADER = (
    "[表題行]", "日付", "伝票No.", "決算", "調整", "付箋1", "付箋2", "タイプ", "生成元",
    "借方勘定科目", "借方補助科目", "借方部門", "借方税区分", "借方税計算区分", "借方金額", "借方税額",
    "貸方勘定科目", "貸方補助科目", "貸方部門", "貸方税区分", "貸方税計算区分", "貸方金額", "貸方税額",
    "摘要", "請求書区分", "仕入税額控除", "期日", "番号", "仕訳メモ", "作業日付", "仕訳番号",
)
COL = {name: index for index, name in enumerate(HEADER)}
DETAIL, DAILY_TOTAL, MONTHLY_TOTAL = "[明細行]", "[日次合計行]", "[月度合計行]"
ABSENT_SIDE_TAX = "対象外"
# Only the values observed in the real export have a known meaning.
OBSERVED_ADJUSTMENT = frozenset({"NO"})
OBSERVED_TYPE = frozenset({"[振伝]"})
_REIWA = re.compile(r"令和(\d{2})年(\d{2})月(\d{2})日")
_SIDES = {
    Side.DEBIT: ("借方勘定科目", "借方補助科目", "借方部門", "借方税区分", "借方税計算区分", "借方金額", "借方税額"),
    Side.CREDIT: ("貸方勘定科目", "貸方補助科目", "貸方部門", "貸方税区分", "貸方税計算区分", "貸方金額", "貸方税額"),
}
# Fields with no place in the JDL 30-column import (kept as optional metadata).
OPTIONAL_FIELDS = ("付箋1", "付箋2", "生成元", "期日", "番号", "仕訳メモ")
# Content identity excludes provenance: row ids, work date and voucher number.
_IDENTITY_EXCLUDED = {"[表題行]", "伝票No.", "作業日付", "仕訳番号"}

YAYOI_INVOICE_CLASS_KEY = "yayoi_invoice_class"
YAYOI_PURCHASE_CREDIT_KEY = "yayoi_purchase_credit"
YAYOI_TAX_CALCULATION_KEY = "yayoi_tax_calculation"


class YayoiJournalReportParseError(ValueError):
    def __init__(self, issues: tuple["YayoiJournalReportIssue", ...]) -> None:
        self.issues = issues
        codes = sorted({issue.code for issue in issues})
        super().__init__(f"Yayoi journal report has {len(issues)} issue(s): {', '.join(codes)}")


@dataclass(frozen=True)
class YayoiJournalReportIssue:
    code: str
    row_number: int | None
    detail: str = ""


@dataclass(frozen=True)
class YayoiJournalReportResult:
    entries: tuple[JournalEntry, ...]
    issues: tuple[YayoiJournalReportIssue, ...]
    detail_rows: int
    period: tuple[date, date] | None
    provenance: dict[str, object] = field(default_factory=dict)
    rejected_journals: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class _Row:
    number: int
    values: tuple[str, ...]

    def get(self, name: str) -> str:
        return self.values[COL[name]]


def yayoi_source_tax_identity(tax: str, invoice_class: str, purchase_credit: str) -> str:
    """Source tax identity used for Human mapping.

    The same 税区分 with a different 請求書区分 / 仕入税額控除 (for example a
    経過措置 80% purchase) is a different tax treatment, so it must be a
    different mapping key and never ride on the ordinary purchase mapping.
    """
    if not invoice_class and not purchase_credit:
        return tax
    return f"{tax}｜{invoice_class or '-'}｜{purchase_credit or '-'}"


def parse_reiwa_date(value: str) -> date | None:
    match = _REIWA.fullmatch(value)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(2018 + year, month, day)
    except ValueError:
        return None


class YayoiJournalReportParser:
    def parse_path(self, path: Path) -> tuple[JournalEntry, ...]:
        result = self.diagnose(path)
        if not result.ok:
            raise YayoiJournalReportParseError(result.issues)
        return result.entries

    def diagnose(self, path: Path) -> YayoiJournalReportResult:
        raw = path.read_bytes()
        try:
            text = raw.decode("cp932", errors="strict")
        except UnicodeDecodeError as exc:
            return YayoiJournalReportResult((), (YayoiJournalReportIssue("ENCODING", None, exc.reason),), 0, None)
        if raw.startswith(b"\xef\xbb\xbf"):
            return YayoiJournalReportResult((), (YayoiJournalReportIssue("BOM", None),), 0, None)
        records = list(csv.reader(io.StringIO(text, newline="")))
        issues: list[YayoiJournalReportIssue] = []
        provenance, period, body_start = self._preamble(records, issues)
        if body_start is None:
            return YayoiJournalReportResult((), tuple(issues), 0, None, provenance)
        details: list[_Row] = []
        bad_rows: set[int] = set()
        running = [0, 0, 0, 0]
        monthly = [0, 0, 0, 0]
        for index in range(body_start, len(records)):
            number = index + 1
            values = tuple(records[index])
            kind = values[0] if values else ""
            if len(values) != len(HEADER):
                issues.append(YayoiJournalReportIssue("COLUMN_COUNT", number, str(len(values))))
                continue
            row = _Row(number, values)
            if kind == DETAIL:
                details.append(row)
                for position, name in enumerate(("借方金額", "借方税額", "貸方金額", "貸方税額")):
                    amount = self._int(row.get(name))
                    running[position] += amount or 0
                    monthly[position] += amount or 0
            elif kind in {DAILY_TOTAL, MONTHLY_TOTAL}:
                totals = [self._int(row.get(name)) or 0 for name in ("借方金額", "借方税額", "貸方金額", "貸方税額")]
                expected = running if kind == DAILY_TOTAL else monthly
                if totals != expected:
                    issues.append(YayoiJournalReportIssue(
                        "DAILY_TOTAL_MISMATCH" if kind == DAILY_TOTAL else "MONTHLY_TOTAL_MISMATCH", number,
                    ))
                if kind == DAILY_TOTAL:
                    running = [0, 0, 0, 0]
                else:
                    monthly = [0, 0, 0, 0]
            else:
                issues.append(YayoiJournalReportIssue("ROW_TYPE_UNKNOWN", number))
        if running != [0, 0, 0, 0]:
            issues.append(YayoiJournalReportIssue("TRAILING_ROWS_WITHOUT_DAILY_TOTAL", None))

        groups: list[list[_Row]] = []
        seen_keys: set[tuple[str, str]] = set()
        for row in details:
            key = (row.get("日付"), row.get("伝票No."))
            if groups and (groups[-1][0].get("日付"), groups[-1][0].get("伝票No.")) == key:
                groups[-1].append(row)
                continue
            if key in seen_keys:
                issues.append(YayoiJournalReportIssue("NONCONSECUTIVE_VOUCHER", row.number))
                bad_rows.add(row.number)
            seen_keys.add(key)
            groups.append([row])

        entries: list[JournalEntry] = []
        rejected = 0
        for group in groups:
            entry, group_issues = self._entry(path.name, group, period)
            issues.extend(group_issues)
            if entry is None or group_issues or any(row.number in bad_rows for row in group):
                rejected += 1
                continue
            entries.append(entry)
        return YayoiJournalReportResult(
            tuple(entries), tuple(issues), len(details), period, provenance, rejected,
        )

    def _preamble(self, records, issues):
        provenance: dict[str, object] = {}
        values: dict[str, tuple[str, ...]] = {}
        index = 0
        while index < len(records) and records[index] and records[index][0] in PREAMBLE_KEYS:
            values[records[index][0]] = tuple(records[index][1:])
            index += 1
        if index >= len(records) or tuple(records[index]) != HEADER:
            issues.append(YayoiJournalReportIssue("HEADER", index + 1))
            return provenance, None, None
        missing = [key for key in PREAMBLE_KEYS if key not in values]
        if missing:
            issues.append(YayoiJournalReportIssue("PREAMBLE", None, ",".join(missing)))
        if values.get("帳票名", ("",))[:1] != (REPORT_NAME,):
            issues.append(YayoiJournalReportIssue("REPORT_TYPE", None))
        if values.get("書式名", ("",))[:1] != (FORMAT_NAME,):
            issues.append(YayoiJournalReportIssue("REPORT_FORMAT", None))
        if any(values.get("検索条件", ())):
            # A filtered report would silently omit journals.
            issues.append(YayoiJournalReportIssue("FILTERED_REPORT", None))
        period_values = values.get("集計期間", ())
        start = parse_reiwa_date(period_values[0]) if len(period_values) > 0 else None
        end = parse_reiwa_date(period_values[1]) if len(period_values) > 1 else None
        if start is None or end is None or start > end:
            issues.append(YayoiJournalReportIssue("PERIOD", None))
            period = None
        else:
            period = (start, end)
        company = (values.get("事業所名") or ("",))[0]
        provenance.update({
            "report": REPORT_NAME,
            "format": FORMAT_NAME,
            # The company name itself is never stored; only a hash to detect mixing files.
            "company_sha256": hashlib.sha256(company.encode("utf-8")).hexdigest(),
            "period_note": period_values[2] if len(period_values) > 2 else "",
        })
        return provenance, period, index + 1

    def _entry(self, file_name: str, rows: list[_Row], period):
        issues: list[YayoiJournalReportIssue] = []
        first = rows[0]
        journal_date = parse_reiwa_date(first.get("日付"))
        if journal_date is None:
            return None, [YayoiJournalReportIssue("DATE_FORMAT", first.number)]
        if period is not None and not period[0] <= journal_date <= period[1]:
            issues.append(YayoiJournalReportIssue("DATE_OUT_OF_PERIOD", first.number))
        entry_id = f"yayoi-report:{file_name}:{first.number}"
        reference = SourceReference(file_name, first.number, first.get("伝票No."))
        lines: list[JournalLine] = []
        optional: dict[str, int] = defaultdict(int)
        optional_values: list[tuple[int, str, str]] = []
        for row in rows:
            row_lines = 0
            # 請求書区分 / 仕入税額控除 are row-level columns but describe the side
            # that carries the tax amount; they must belong to exactly one side.
            taxed_sides = [side for side in (Side.DEBIT, Side.CREDIT) if row.get(_SIDES[side][6])]
            invoice_side = None
            if row.get("請求書区分") or row.get("仕入税額控除"):
                if len(taxed_sides) != 1:
                    issues.append(YayoiJournalReportIssue("INVOICE_SIDE_AMBIGUOUS", row.number))
                    continue
                invoice_side = taxed_sides[0]
            for side in (Side.DEBIT, Side.CREDIT):
                line, issue = self._line(file_name, entry_id, row, side, side is invoice_side)
                if issue is not None:
                    issues.append(issue)
                elif line is not None:
                    lines.append(line)
                    row_lines += 1
            if row_lines == 0 and not any(issue.row_number == row.number for issue in issues):
                issues.append(YayoiJournalReportIssue("EMPTY_ROW", row.number))
            for name in OPTIONAL_FIELDS:
                if row.get(name):
                    optional[name] += 1
                    optional_values.append((row.number, name, row.get(name)))
            if row.get("調整") not in OBSERVED_ADJUSTMENT:
                issues.append(YayoiJournalReportIssue("ADJUSTMENT_UNOBSERVED", row.number))
            if row.get("タイプ") not in OBSERVED_TYPE:
                issues.append(YayoiJournalReportIssue("TYPE_UNOBSERVED", row.number))
        if issues:
            return None, issues
        entry = JournalEntry(
            id=entry_id,
            source_reference=reference,
            date=journal_date,
            lines=lines,
            description=rows[0].get("摘要") or None if len({row.get("摘要") for row in rows}) == 1 else None,
            metadata={
                "source": SOURCE_FORMAT,
                ROW_ORDER_KEY: tuple(row.number for row in rows),
                JOURNAL_CONTENT_IDENTITY_KEY: journal_content_identity(
                    SOURCE_FORMAT,
                    journal_date.isoformat(),
                    tuple(
                        tuple(value for name, value in zip(HEADER, row.values) if name not in _IDENTITY_EXCLUDED)
                        for row in rows
                    ),
                ),
                "yayoi_voucher_number": first.get("伝票No."),
                "yayoi_closing": first.get("決算"),
                "yayoi_adjustment": tuple(dict.fromkeys(row.get("調整") for row in rows)),
                "yayoi_type": tuple(dict.fromkeys(row.get("タイプ") for row in rows)),
                "yayoi_journal_numbers": tuple(row.get("仕訳番号") for row in rows),
                "yayoi_optional_fields": dict(optional),
                "yayoi_optional_values": tuple(optional_values),
            },
        )
        if not entry.is_balanced():
            return None, [YayoiJournalReportIssue("UNBALANCED_JOURNAL", first.number)]
        return stamp_line_journal_identity(entry), []

    def _line(self, file_name, entry_id, row: _Row, side: Side, carries_invoice: bool):
        account, sub, department, tax, calculation, amount_raw, tax_raw = (row.get(name) for name in _SIDES[side])
        if not account:
            if sub or department or calculation or amount_raw or tax_raw or tax not in {"", ABSENT_SIDE_TAX}:
                return None, YayoiJournalReportIssue("SIDE_INCOMPLETE", row.number, side.value)
            return None, None
        amount = self._int(amount_raw)
        if amount is None:
            return None, YayoiJournalReportIssue("AMOUNT_FORMAT", row.number, side.value)
        tax_amount = None
        if tax_raw:
            tax_amount = self._int(tax_raw)
            if tax_amount is None:
                return None, YayoiJournalReportIssue("TAX_AMOUNT_FORMAT", row.number, side.value)
            if not tax:
                return None, YayoiJournalReportIssue("TAX_AMOUNT_WITHOUT_TAX_CATEGORY", row.number, side.value)
        invoice_class = row.get("請求書区分") if carries_invoice else ""
        purchase_credit = row.get("仕入税額控除") if carries_invoice else ""
        tax_info = None
        if tax:
            tax_info = TaxInfo(
                category=yayoi_source_tax_identity(tax, invoice_class, purchase_credit),
                tax_amount=Decimal(tax_amount) if tax_amount is not None else None,
                invoice_classification=invoice_class or None,
                metadata={
                    "source_format": SOURCE_FORMAT,
                    YAYOI_TAX_CALCULATION_KEY: calculation,
                    YAYOI_INVOICE_CLASS_KEY: invoice_class,
                    YAYOI_PURCHASE_CREDIT_KEY: purchase_credit,
                },
            )
        return JournalLine(
            side=side,
            account=account,
            amount=Decimal(amount),
            source_reference=SourceReference(file_name, row.number, row.get("伝票No.")),
            sub_account=sub or None,
            department=department or None,
            tax_info=tax_info,
            metadata={
                LINE_ROW_KEY: row.number,
                LINE_ROW_DESCRIPTION_KEY: row.get("摘要"),
                "yayoi_journal_number": row.get("仕訳番号"),
            },
        ), None

    @staticmethod
    def _int(value: str) -> int | None:
        if value == "":
            return None
        if not re.fullmatch(r"-?\d+", value):
            return None
        try:
            return int(Decimal(value))
        except InvalidOperation:
            return None

"""freee 税抜経理: tell the separate 仮払消費税 / 仮受消費税 row apart from the taxable lines (diagnosis only).

Why: under 税抜経理 freee appends a consumption-tax row to each journal (E5B-2A: the eight existing journals,
10 -> 18 rows; E5B-2B: two newly registered ones). That row carries the SAME 税区分 / 税率 / 軽減 / 内税 as the
line it belongs to, so a reader that treats every line with a taxable 税区分 as a taxable line counts the tax
twice: once as the tax of the base line, and again as one more taxable purchase / sale of its own amount.

How: a row is the tax row of its journal only when EVERY condition below holds. The account name and the
freee code (181 / 361 in the sample) are one condition among many, never enough on their own:

1. 新CSV with 消費税経理処理方法 = 税抜経理 (the 旧CSV has no such column: never decided, UNDETERMINABLE);
2. it is the LAST physical row of a journal of two rows or more, one side only, the other side all blank
   (the observed 新CSV blank-side representation);
3. its 税区分 is taxable, purchase on the debit / sale on the credit; 税金額 present as a column and blank;
   備考 blank; 税率 and 内税・外税 present;
4. (side, account, freee code) is one the Evidence showed for a tax row;
5. every other line: 税金額 blank; not a tax-row account; on the same side taxable with exactly the same
   (税区分, 税率, 軽減税率有無, 内税・外税) — the base lines (>= 1); on the other side 対象外;
6. 0 < tax row amount < sum of the base lines.

Otherwise a 税抜経理 journal is UNIDENTIFIED (blocks). Nothing is computed: no tax is derived from a rate,
the rounding rule is unverified, and an aggregated tax row (one row for several base lines, E5B-01 / 02) is
never allocated to its lines. Evidence: adapters.input.freee.journal_csv E5B2A / E5B2B observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from accounting_converter.adapters.input.freee.journal_csv import (
    BLANK_SIDE_NEW_ALL_EMPTY,
    BLANK_SIDE_OLD_ZERO_PLACEHOLDER,
    BLANK_SIDES_KEY,
    LINE_ACCOUNT_CODE_KEY,
    LINE_SIDE_DESCRIPTION_KEY,
    OBSERVED_TAX_LINE_ACCOUNTS,
    TAX_ACCOUNTING_METHOD_KEY,
)
from accounting_converter.application.freee_tax_hint import tax_hint
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side
from accounting_converter.domain.journal_rows import LINE_ROW_KEY, ROW_ORDER_KEY

TAX_EXCLUSIVE = "税抜経理"
TAX_INCLUSIVE = "税込経理"

# Blockers (owner:code), used by application.freee_diagnosis.
BLOCKER_UNIDENTIFIED = "SYSTEM_EVIDENCE:FREEE_TAX_LINE_UNIDENTIFIED"
BLOCKER_UNDETERMINABLE = "SYSTEM_EVIDENCE:FREEE_TAX_LINE_UNDETERMINABLE"
BLOCKER_AGGREGATED = "SYSTEM_EVIDENCE:FREEE_TAX_LINE_AGGREGATED"
BLOCKER_JDL_UNVERIFIED = "SYSTEM_EVIDENCE:FREEE_TAX_LINE_JDL_UNVERIFIED"


class TaxLineStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"  # 新CSV 税込経理 (E4, E5B第1回: no tax row), or 旧CSV without a tax-row form
    IDENTIFIED = "IDENTIFIED"  # exactly the observed structure
    UNIDENTIFIED = "UNIDENTIFIED"  # 税抜経理, but not exactly the observed structure: BLOCK
    UNDETERMINABLE = "UNDETERMINABLE"  # no 税込/税抜 information and a row of the tax-row form: BLOCK


@dataclass(frozen=True)
class TaxLineClassification:
    status: TaxLineStatus
    tax_line: int | None = None  # index into entry.lines
    base_lines: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()  # failed conditions (codes only, no customer values)

    @property
    def aggregated(self) -> bool:
        """One tax row for several base lines: its amount is never allocated to them."""
        return self.status is TaxLineStatus.IDENTIFIED and len(self.base_lines) > 1

    def blockers(self) -> tuple[str, ...]:
        if self.status is TaxLineStatus.UNIDENTIFIED:
            return (BLOCKER_UNIDENTIFIED,)
        if self.status is TaxLineStatus.UNDETERMINABLE:
            return (BLOCKER_UNDETERMINABLE,)
        if self.status is TaxLineStatus.IDENTIFIED:
            return (BLOCKER_JDL_UNVERIFIED, *((BLOCKER_AGGREGATED,) if self.aggregated else ()))
        return ()


_NOT_APPLICABLE = TaxLineClassification(TaxLineStatus.NOT_APPLICABLE)


def _tax_key(line: JournalLine) -> tuple:
    info = line.tax_info
    meta = info.metadata if info is not None else {}
    return (info.category if info else None, meta.get("freee_tax_rate_raw"), meta.get("freee_reduced_rate_raw"),
            meta.get("freee_tax_inclusion_raw"))


def _taxed(line: JournalLine) -> bool:
    return line.tax_info is not None and tax_hint(line.tax_info.category).taxed


def _last_row_line(entry: JournalEntry, blank_representation: str) -> tuple[int | None, str | None]:
    """(index of the only line of the last row, failure code)."""
    rows = tuple(entry.metadata.get(ROW_ORDER_KEY, ()) or ())
    if len(rows) < 2:
        return None, "SINGLE_ROW_JOURNAL"
    last = rows[-1]
    indexes = [i for i, line in enumerate(entry.lines) if line.metadata.get(LINE_ROW_KEY) == last]
    if len(indexes) != 1:
        return None, "LAST_ROW_NOT_ONE_SIDED"
    other = Side.CREDIT if entry.lines[indexes[0]].side is Side.DEBIT else Side.DEBIT
    blanks = {(row, side, rep) for row, side, rep in entry.metadata.get(BLANK_SIDES_KEY, ()) or ()}
    if (last, other.value, blank_representation) not in blanks:
        return None, "LAST_ROW_OTHER_SIDE_NOT_BLANK"
    return indexes[0], None


def classify_tax_lines(entry: JournalEntry) -> TaxLineClassification:
    method = entry.metadata.get(TAX_ACCOUNTING_METHOD_KEY)
    if method == TAX_INCLUSIVE:
        return _NOT_APPLICABLE
    if method is None:
        return _without_method(entry)
    if method != TAX_EXCLUSIVE:  # an unobserved value: also FREEE_VALUE_UNOBSERVED
        return TaxLineClassification(TaxLineStatus.UNDETERMINABLE, reasons=("TAX_ACCOUNTING_METHOD_UNOBSERVED",))
    return _tax_exclusive(entry)


def _without_method(entry: JournalEntry) -> TaxLineClassification:
    """旧CSV: no 消費税経理処理方法 and no 税金額 column. A journal whose last row has the tax-row form (one side,
    taxable, same 税区分 as another line on that side — E5B-2B 旧CSV) cannot be told from an ordinary 2-line
    journal (E5B第1回 E5B-01 has the same form under 税込経理): UNDETERMINABLE, whatever the account name."""
    # The blank side is "" / 0 / 対象外 in the 旧CSV; a 新CSV whose 消費税経理処理方法 is blank has all-empty sides.
    for representation in (BLANK_SIDE_OLD_ZERO_PLACEHOLDER, BLANK_SIDE_NEW_ALL_EMPTY):
        index, _failure = _last_row_line(entry, representation)
        if index is not None:
            break
    else:
        return _NOT_APPLICABLE
    candidate = entry.lines[index]
    if not _taxed(candidate):
        return _NOT_APPLICABLE
    same = [i for i, line in enumerate(entry.lines)
            if i != index and line.side is candidate.side and _taxed(line)
            and line.tax_info.category == candidate.tax_info.category]
    if not same:
        return _NOT_APPLICABLE
    return TaxLineClassification(TaxLineStatus.UNDETERMINABLE, reasons=("TAX_ACCOUNTING_METHOD_NOT_IN_EXPORT",))


def _tax_exclusive(entry: JournalEntry) -> TaxLineClassification:
    def unidentified(*codes: str) -> TaxLineClassification:
        return TaxLineClassification(TaxLineStatus.UNIDENTIFIED, reasons=tuple(sorted(set(codes))))

    if not any(_taxed(line) for line in entry.lines):
        return unidentified("NO_TAXED_LINE_UNOBSERVED")
    index, failure = _last_row_line(entry, BLANK_SIDE_NEW_ALL_EMPTY)
    if index is None:
        return unidentified(failure or "NO_TAX_ROW")
    tax = entry.lines[index]
    failed: list[str] = []
    info = tax.tax_info
    hint = tax_hint(info.category if info is not None else None)
    expected_kind = "PURCHASE_TAXABLE" if tax.side is Side.DEBIT else "SALES_TAXABLE"
    if info is None or hint.kind != expected_kind:
        failed.append("TAX_ROW_CATEGORY_NOT_TAXED_FOR_ITS_SIDE")
    else:
        meta = info.metadata
        if info.tax_amount is not None or not meta.get("tax_amount_blank"):
            failed.append("TAX_ROW_TAX_AMOUNT_NOT_BLANK")
        if not meta.get("freee_tax_rate_raw") or not meta.get("freee_tax_inclusion_raw"):
            failed.append("TAX_ROW_RATE_OR_INCLUSION_MISSING")
    if tax.metadata.get(LINE_SIDE_DESCRIPTION_KEY, "") != "":
        failed.append("TAX_ROW_DESCRIPTION_NOT_BLANK")
    if (tax.side.value, tax.account, tax.metadata.get(LINE_ACCOUNT_CODE_KEY, "")) not in OBSERVED_TAX_LINE_ACCOUNTS:
        failed.append("TAX_ROW_ACCOUNT_UNOBSERVED")
    tax_accounts = {(side, account) for side, account, _ in OBSERVED_TAX_LINE_ACCOUNTS}
    tax_codes = {code for _, _, code in OBSERVED_TAX_LINE_ACCOUNTS}
    key = _tax_key(tax)
    base: list[int] = []
    for i, line in enumerate(entry.lines):
        if i == index:
            continue
        if line.tax_info is not None and (line.tax_info.tax_amount is not None
                                          or not line.tax_info.metadata.get("tax_amount_blank")):
            failed.append("OTHER_LINE_TAX_AMOUNT_NOT_BLANK")
        if (line.side.value, line.account) in tax_accounts or line.metadata.get(LINE_ACCOUNT_CODE_KEY) in tax_codes:
            failed.append("SECOND_TAX_ACCOUNT_LINE")
        if line.side is tax.side:
            if _taxed(line) and _tax_key(line) == key:
                base.append(i)
            else:
                failed.append("SAME_SIDE_LINE_WITH_OTHER_TAX")  # mixed rates / categories: unobserved
        elif line.tax_info is None or line.tax_info.category != "対象外":
            failed.append("OTHER_SIDE_LINE_NOT_OUT_OF_SCOPE")
    if not base:
        failed.append("NO_BASE_LINE")
    elif not (Decimal(0) < tax.amount < sum((entry.lines[i].amount for i in base), Decimal(0))):
        failed.append("TAX_ROW_AMOUNT_OUT_OF_RANGE")
    if failed:
        return unidentified(*failed)
    return TaxLineClassification(TaxLineStatus.IDENTIFIED, tax_line=index, base_lines=tuple(base))

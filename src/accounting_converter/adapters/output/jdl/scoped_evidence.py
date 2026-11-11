"""JDL target Evidence valid for ONE exact company scope (what JDL received, not the source).

The campaign probes ran on a JDL company with these settings, so the Evidence
applies only to a company with the same settings:

    JDL IBEX 出納帳 35.5 / 税抜 / 原則課税 / 一括比例配分 /
    端数処理 売上=切上げ・仕入=四捨五入 / 振替伝票入力行数=16

A different rounding, another row limit, or an unconfirmed row limit is never
treated as covered.

振替伝票入力行数 (rows per voucher; JDL IBEX 出納帳 35.5 offers 16 and 64): 16 is the setting all
cases up to round 4 ran with. Another setting is in scope only when `ROW_LIMIT_SCOPES` holds real
Evidence for it (its own limit, what JDL counts, and per category the control that carried the 16-row
Evidence over, see the registry). Until then a company set to it is VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED:
blocked, never assumed to behave like 16. Once verified, the Evidence that applies under that setting is
its own cases (e.g. layouts of 17..64 rows) plus only the carried categories of the 16-row Evidence; the
16-row scope never uses cases recorded under 64. The Evidence that existed before (other companies, other
settings) is not changed and is tried first; this module only adds what the
campaign proved.

What a registered case proves, and what is applied (nothing else):
- layout: the physical-row layout (B/D/C runs) that round-tripped;
- cells: a taxed (side, JDL tax cell) is covered only in a layout where that cell
  round-tripped; untaxed lines are covered by the layout alone;
- row pair: a physical row whose debit AND credit both carry tax is covered only
  if such a row round-tripped;
- accounts: per (side, cell) the target accounts that round-tripped (account
  independence is decided by the caller with the existing ≥3-account rule);
- explicit tax: per (side, cell, relation, account) the amount relations that
  were kept unchanged by JDL Import.
Subaccounts, descriptions and the master identity are validated by the existing
checks; the probes used no-subaccount accounts and this module does not widen
what was observed for them.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from enum import Enum
from typing import Sequence

from accounting_converter.domain.journal_rows import PhysicalRow
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

from .models import (
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlInputTaxCreditMethod,
    JdlTargetContext,
    JdlTaxationMethod,
    JdlTaxRounding,
)
from .scoped_evidence_registry import (
    JDL_TAX_RELATION_AUTHORIZED_PEERS,
    JDL_TAX_SETTING_PEERS,
    ROW_LIMIT_SCOPES,
    SCOPED_CASES,
    RowLimitScopeEvidence,
    ScopedCase,
)
from .tax_semantics import JdlTaxSemantic

SCOPE_ID = "JDL-35-5-TAX-EXCL-PROP-SALES-CEIL-PURCH-HALFUP-VOUCHER-ROWS-16"
SCOPED_ROUTE_ID = "JDL-35-5-SCOPED-CAPABILITY-COMPOSITION-V1"
SCOPE_SALES_ROUNDING = JdlTaxRounding.CEILING
SCOPE_PURCHASE_ROUNDING = JdlTaxRounding.HALF_UP
SCOPE_VOUCHER_ROW_LIMIT = 16

# Real JDL Evidence of the limit itself (2026-11-05): 16 rows imported and
# re-exported; 17, 25, 50 and 73 rows rejected at Import.
VOUCHER_ROW_LIMIT_EVIDENCE_ID = "EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001"
# Settings JDL IBEX 出納帳 35.5 offers for 振替伝票入力行数 (会社情報: 16行以内 / 64行以内).
JDL_ROW_LIMIT_CHOICES = (16, 64)


def scope_id_for(row_limit: int) -> str:
    """The scope id of a row-limit setting (16 keeps the original id)."""
    return SCOPE_ID if row_limit == SCOPE_VOUCHER_ROW_LIMIT else SCOPE_ID.rsplit("-", 1)[0] + f"-{row_limit}"


COUNTING_RULES = frozenset({"PHYSICAL_ROWS", "LINES_PER_SIDE"})
CARRY_CATEGORIES = frozenset({"LAYOUT", "TAX_RELATION", "SUBACCOUNT", "CLOSING"})
# Amount relations re-observed by the LAYOUT control itself (no fraction, no amount, exact 8% / 80%).
_LAYOUT_RELATIONS = frozenset({"", "NONE", "EXACT"})


def verified_row_limits() -> frozenset[int]:
    return frozenset({SCOPE_VOUCHER_ROW_LIMIT, *(
        limit for limit, record in ROW_LIMIT_SCOPES.items()
        if record.limit == limit and record.counts in COUNTING_RULES and record.limit_evidence_id)})


def carries(row_limit: int | None, category: str) -> bool:
    """Whether this category of the 16-row Evidence applies under this 振替伝票入力行数."""
    if row_limit == SCOPE_VOUCHER_ROW_LIMIT:
        return True
    if row_limit not in verified_row_limits() or category not in CARRY_CATEGORIES:
        return False
    return category in dict(ROW_LIMIT_SCOPES[row_limit].carried)


def counted_rows(rows: Sequence[PhysicalRow], row_limit: int | None) -> int:
    """What is compared with the limit: CSV physical rows, unless real Evidence showed JDL counts lines per side."""
    record = ROW_LIMIT_SCOPES.get(row_limit) if row_limit in verified_row_limits() else None
    if record is not None and record.counts == "LINES_PER_SIDE":
        return max(sum(r.debit is not None for r in rows), sum(r.credit is not None for r in rows))
    return len(rows)


def exceeds_row_limit(rows: Sequence[PhysicalRow], row_limit: int | None) -> bool:
    return row_limit is not None and counted_rows(rows, row_limit) > row_limit


def row_limit_evidence_ids(row_limit: int) -> tuple[str, ...]:
    """Evidence that this company setting behaves as registered (empty = not verified)."""
    if row_limit == SCOPE_VOUCHER_ROW_LIMIT:
        return (VOUCHER_ROW_LIMIT_EVIDENCE_ID,)
    if row_limit not in verified_row_limits():
        return ()
    record = ROW_LIMIT_SCOPES[row_limit]
    return (record.limit_evidence_id, *(evidence for _category, evidence in record.carried))

CELL_SEMANTIC = {
    "S10": JdlTaxSemantic.SALES_10_EXTERNAL,
    "P10": JdlTaxSemantic.PURCHASE_10_INTERNAL,
    "NP": JdlTaxSemantic.NON_TAXABLE_PURCHASE,
    "NS": JdlTaxSemantic.NON_TAXABLE_SALES,
    "XS": JdlTaxSemantic.EXPORT_SALES,
    "R8": JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL,
    "T80": JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL,
}
SEMANTIC_CELL = {semantic.value: cell for cell, semantic in CELL_SEMANTIC.items()}
SEMANTIC_CELL[JdlTaxSemantic.NO_TAX.value] = "NO"
# Cells that carry no tax amount (blank in the CSV).
NO_AMOUNT_CELLS = frozenset({"NO", "NP", "NS", "XS"})
_ROUNDING_MODE = {
    JdlTaxRounding.FLOOR: ROUND_DOWN,
    JdlTaxRounding.HALF_UP: ROUND_HALF_UP,
    JdlTaxRounding.CEILING: ROUND_UP,
}


class ScopeState(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    # Everything matches except that the Human has not entered the company's
    # 振替伝票入力行数 yet. Never assumed.
    VOUCHER_ROW_LIMIT_UNCONFIRMED = "VOUCHER_ROW_LIMIT_UNCONFIRMED"
    # Everything matches, the Human entered a row limit (e.g. 64), but no real JDL round proves that
    # setting yet. Blocked; the 16-row Evidence is not used for it.
    VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED = "VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


def scope_state(context: JdlTargetContext) -> ScopeState:
    same_settings = bool(
        context.product == "JDL IBEX 出納帳"
        and context.version == "35.5"
        and context.tax_processing_mode is JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED
        and context.effective_taxation_method is JdlTaxationMethod.STANDARD
        and context.effective_input_tax_credit_method is JdlInputTaxCreditMethod.PROPORTIONAL
        and context.confirmation_state is JdlContextConfirmationState.CONFIRMED
        and context.provenance is JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT
        and context.sales_tax_rounding is SCOPE_SALES_ROUNDING
        and context.purchase_tax_rounding is SCOPE_PURCHASE_ROUNDING
    )
    if not same_settings:
        return ScopeState.OUT_OF_SCOPE
    if context.voucher_row_limit is None:
        return ScopeState.VOUCHER_ROW_LIMIT_UNCONFIRMED
    if context.voucher_row_limit in verified_row_limits():
        return ScopeState.IN_SCOPE
    return ScopeState.VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED


def semantic_evidence_applies(context: JdlTargetContext) -> bool:
    """True when the new tax cells (輸出売・軽減8%・10%免80) may be offered for confirmation.

    The row limit is a company setting the Human can still enter, so an
    unconfirmed or unverified limit does not hide the candidate (the journals
    stay blocked); a different rounding does.
    """
    return scope_state(context) is not ScopeState.OUT_OF_SCOPE


# ---------------------------------------------------------------- derived views
def cases_for(row_limit: int) -> tuple[ScopedCase, ...]:
    """The cases that apply under this 振替伝票入力行数 (empty for an unverified setting)."""
    if row_limit not in verified_row_limits():
        return ()
    own = tuple(case for case in SCOPED_CASES if case.row_limit_scope == row_limit)
    if row_limit == SCOPE_VOUCHER_ROW_LIMIT:
        return own
    if not carries(row_limit, "LAYOUT"):
        return own
    keep_relations = carries(row_limit, "TAX_RELATION")
    carried = []
    for case in SCOPED_CASES:
        if case.row_limit_scope != SCOPE_VOUCHER_ROW_LIMIT or len(case.rows) > SCOPE_VOUCHER_ROW_LIMIT:
            continue
        if not keep_relations:
            # The rounding relations were not re-observed under this setting: keep the case's layout and cells,
            # but its explicit tax amounts no longer authorize anything (the relation is dropped, not widened).
            case = ScopedCase(case.case_id, case.evidence_id, case.layout, case.rows,
                              tuple(t if t[3] in _LAYOUT_RELATIONS else (*t[:3], "UNCARRIED") for t in case.taxed),
                              case.row_limit_scope)
        carried.append(case)
    return tuple(carried) + own


def _build(cases: Sequence[ScopedCase]):
    layout_cells: dict[str, set] = defaultdict(set)
    layout_ids: dict[str, list[str]] = defaultdict(list)
    row_pairs: set = set()
    cell_accounts: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    relation_accounts: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for case in cases:
        layout_ids[case.layout].append(case.evidence_id)
        for debit, credit in case.rows:
            row_pairs.add((debit, credit))
        for side, cell, account, relation in case.taxed:
            layout_cells[case.layout].add((side, cell))
            cell_accounts[(side, cell)][account].append(case.evidence_id)
            if relation not in {"", "NONE", "UNCARRIED"}:
                relation_accounts[(side, cell, relation)][account].append(case.evidence_id)
        layout_cells[case.layout]  # a layout of untaxed rows is registered too
    return (
        {k: frozenset(v) for k, v in layout_cells.items()},
        {k: tuple(dict.fromkeys(v)) for k, v in layout_ids.items()},
        frozenset(row_pairs),
        {k: {a: tuple(dict.fromkeys(ids)) for a, ids in v.items()} for k, v in cell_accounts.items()},
        {k: {a: tuple(dict.fromkeys(ids)) for a, ids in v.items()} for k, v in relation_accounts.items()},
    )


_VIEWS: dict[int, tuple] = {}


def views(row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> tuple:
    """(LAYOUT_CELLS, LAYOUT_EVIDENCE_IDS, ROW_PAIRS, CELL_ACCOUNTS, RELATION_ACCOUNTS) under this setting."""
    if row_limit not in _VIEWS:
        _VIEWS[row_limit] = _build(cases_for(row_limit))
    return _VIEWS[row_limit]


def reset_views() -> None:
    """Drop cached views (only after the registry data was swapped, e.g. a dry-run forecast or a test)."""
    _VIEWS.clear()


# The 16-row views (the original module-level names; tools and tests read them).
LAYOUT_CELLS, LAYOUT_EVIDENCE_IDS, ROW_PAIRS, CELL_ACCOUNTS, RELATION_ACCOUNTS = views(SCOPE_VOUCHER_ROW_LIMIT)


# ---------------------------------------------------------------- pure checks
def layout_of(rows: Sequence[PhysicalRow]) -> str:
    runs: list[list] = []
    for row in rows:
        kind = "B" if row.debit is not None and row.credit is not None else "D" if row.debit is not None else "C"
        if runs and runs[-1][0] == kind:
            runs[-1][1] += 1
        else:
            runs.append([kind, 1])
    return "".join(f"{kind}{count}" for kind, count in runs)


def placement_gaps(layout: str, row_cells: Sequence[tuple[str, str]],
                   row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> tuple[str, ...]:
    """Account-free gaps of a journal whose rows carry these cells ("-" = no line).

    VOUCHER_LAYOUT_UNVERIFIED  the layout never round-tripped;
    VOUCHER_TAX_PLACEMENT_UNVERIFIED  a taxed cell that never round-tripped in
    this layout, or a row with tax on both sides that never round-tripped.
    """
    layout_cells, _ids, row_pairs, _accounts, _relations = views(row_limit)
    if layout not in layout_cells:
        return ("VOUCHER_LAYOUT_UNVERIFIED",)
    observed = layout_cells[layout]
    for debit, credit in row_cells:
        if (debit, credit) not in row_pairs:
            if debit not in {"NO", "-"} and credit not in {"NO", "-"}:
                return ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",)
        for side, cell in (("DEBIT", debit), ("CREDIT", credit)):
            if cell not in {"NO", "-"} and (side, cell) not in observed:
                return ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",)
    return ()


# A written tax of 0 where the exact tax is a fraction and the roundings disagree (e.g. 売上10% 外税 1 yen: floor 0,
# company 切上げ 1). Every FLOOR / HALF_LOW / FLOOR_HIGH case that round-tripped wrote a tax > 0, and company A's
# READY-only round trip (2026-11-11) re-exported such a written 0 as 1. So a written 0 is its own relation: never
# registered, hence never covered (BLOCK EXPLICIT_TAX_ZERO_UNVERIFIED) until a real round trip registers it.
ZERO_RELATION = "ZERO"
_ZERO_GUARDED = frozenset({"FLOOR", "HALF_LOW", "FLOOR_HIGH"})


def relation_of(cell: str, amount: Decimal, written: Decimal | None) -> str | None:
    """How the written tax relates to the amount for this scope's rounding.

    "" no question (every rounding agrees, or floor == company rounding);
    COMPANY / FLOOR / EXACT / NONE as in the registry; for 軽減8% / 10%免80 with a
    fractional exact value HALF_LOW (written = floor = half-up), HALF_HIGH (written =
    half-up > floor) and FLOOR_HIGH (written = floor < half-up). ZERO: written 0 that
    would otherwise be FLOOR / HALF_LOW / FLOOR_HIGH (unobserved, see ZERO_RELATION).
    None = a relation that was never observed (never allowed).
    """
    relation = _relation_of(cell, amount, written)
    if relation in _ZERO_GUARDED and written == 0:
        return ZERO_RELATION
    return relation


def _relation_of(cell: str, amount: Decimal, written: Decimal | None) -> str | None:
    if cell in NO_AMOUNT_CELLS:
        return "NONE" if written in (None, Decimal("0")) else None
    if written is None:
        return None
    if cell in {"S10", "P10"}:
        raw = amount * 10 / 110
        floor, up, half = (raw.quantize(Decimal(1), rounding=mode) for mode in (ROUND_DOWN, ROUND_UP, ROUND_HALF_UP))
        company_mode = _ROUNDING_MODE[SCOPE_SALES_ROUNDING if cell == "S10" else SCOPE_PURCHASE_ROUNDING]
        company = raw.quantize(Decimal(1), rounding=company_mode)
        if floor == up == half == written or written == floor == company:
            return ""
        if written == company:
            return "COMPANY"
        if written == floor:
            return "FLOOR"
        return None
    if cell in {"R8", "T80"}:
        exact = amount * 8 / 108 if cell == "R8" else amount * 10 / 110 * Decimal("0.8")
        if written == exact:
            return "EXACT"
        # A fractional exact value: only describes how the written tax relates to it.
        # Allowed to be used only if such a relation was round-tripped (registry data).
        floor, half = (exact.quantize(Decimal(1), rounding=mode) for mode in (ROUND_DOWN, ROUND_HALF_UP))
        if written == half:
            return "HALF_LOW" if floor == half else "HALF_HIGH"
        if written == floor:
            return "FLOOR_HIGH"
        return None
    return None


def relation_accounts(side: str, cell: str, relation: str,
                      row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> dict[str, tuple[str, ...]]:
    return views(row_limit)[4].get((side, cell, relation), {})


def layout_evidence_ids(layout: str, row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> tuple[str, ...]:
    return views(row_limit)[1].get(layout, ())


def cell_accounts(row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> dict:
    return views(row_limit)[3]


# Independence policy for the explicit-tax RELATION gate (separate from the
# (side, cell) coverage gate, which the caller unions with Evidence that
# existed before). Mirrors the general >=3-account rule used elsewhere for
# this Evidence family; 課税売上10% on the credit side stays account-specific
# regardless of how many accounts round-tripped, same as the pre-existing rule.
# The pre-existing P10/COMPANY rule reaches an unprobed account only when its
# code is in the reviewed authorization subset of PDF-matching accounts.
# New R8/T80 relations remain exact-account only even if three probes happen
# to share printed tax defaults. PDF metadata alone never grants permission.
RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS = 3
RELATION_ACCOUNT_SPECIFIC_ONLY = frozenset({("CREDIT", "S10")})


def relation_covers_account(side: str, cell: str, relation: str, account: str,
                            row_limit: int = SCOPE_VOUCHER_ROW_LIMIT) -> bool:
    """Whether (side, cell, relation) may be used on this account.

    relation in {"", "NONE"}: no amount question; the layout/cell gate already
    decided coverage. Otherwise: round-tripped on this exact account, or
    independent: not account-specific, and the account is in the explicit
    authorization subset for that relation. Currently only P10/COMPANY has
    such a subset; PDF-derived peers for other relations are metadata only.
    The single source of truth for this check: both composition and the
    output stage call it, so they can never disagree.
    """
    if relation in {"", "NONE"}:
        return True
    observed = relation_accounts(side, cell, relation, row_limit)
    if account in observed:
        return True
    if len(observed) < RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS or (side, cell) in RELATION_ACCOUNT_SPECIFIC_ONLY:
        return False
    return account in JDL_TAX_RELATION_AUTHORIZED_PEERS.get((side, cell, relation), frozenset())

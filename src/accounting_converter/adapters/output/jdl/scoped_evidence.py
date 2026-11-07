"""JDL target Evidence valid for ONE exact company scope (what JDL received, not the source).

The campaign probes ran on a JDL company with these settings, so the Evidence
applies only to a company with the same settings:

    JDL IBEX 出納帳 35.5 / 税抜 / 原則課税 / 一括比例配分 /
    端数処理 売上=切上げ・仕入=四捨五入 / 振替伝票入力行数=16

A different rounding, another row limit, or an unconfirmed row limit is never
treated as covered. The Evidence that existed before (other companies, other
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
from .scoped_evidence_registry import JDL_TAX_SETTING_PEERS, SCOPED_CASES, ScopedCase
from .tax_semantics import JdlTaxSemantic

SCOPE_ID = "JDL-35-5-TAX-EXCL-PROP-SALES-CEIL-PURCH-HALFUP-VOUCHER-ROWS-16"
SCOPED_ROUTE_ID = "JDL-35-5-SCOPED-CAPABILITY-COMPOSITION-V1"
SCOPE_SALES_ROUNDING = JdlTaxRounding.CEILING
SCOPE_PURCHASE_ROUNDING = JdlTaxRounding.HALF_UP
SCOPE_VOUCHER_ROW_LIMIT = 16

# Real JDL Evidence of the limit itself (2026-11-05): 16 rows imported and
# re-exported; 17, 25, 50 and 73 rows rejected at Import.
VOUCHER_ROW_LIMIT_EVIDENCE_ID = "EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001"

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
    if context.voucher_row_limit == SCOPE_VOUCHER_ROW_LIMIT:
        return ScopeState.IN_SCOPE
    return ScopeState.OUT_OF_SCOPE


def semantic_evidence_applies(context: JdlTargetContext) -> bool:
    """True when the new tax cells (輸出売・軽減8%・10%免80) may be offered for confirmation.

    The row limit is a company setting the Human can still enter, so an
    unconfirmed limit does not hide the candidate; a different rounding does.
    """
    return scope_state(context) is not ScopeState.OUT_OF_SCOPE


# ---------------------------------------------------------------- derived views
def _build():
    layout_cells: dict[str, set] = defaultdict(set)
    layout_ids: dict[str, list[str]] = defaultdict(list)
    row_pairs: set = set()
    cell_accounts: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    relation_accounts: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for case in SCOPED_CASES:
        layout_ids[case.layout].append(case.evidence_id)
        for debit, credit in case.rows:
            row_pairs.add((debit, credit))
        for side, cell, account, relation in case.taxed:
            layout_cells[case.layout].add((side, cell))
            cell_accounts[(side, cell)][account].append(case.evidence_id)
            if relation not in {"", "NONE"}:
                relation_accounts[(side, cell, relation)][account].append(case.evidence_id)
        layout_cells[case.layout]  # a layout of untaxed rows is registered too
    return (
        {k: frozenset(v) for k, v in layout_cells.items()},
        {k: tuple(dict.fromkeys(v)) for k, v in layout_ids.items()},
        frozenset(row_pairs),
        {k: {a: tuple(dict.fromkeys(ids)) for a, ids in v.items()} for k, v in cell_accounts.items()},
        {k: {a: tuple(dict.fromkeys(ids)) for a, ids in v.items()} for k, v in relation_accounts.items()},
    )


LAYOUT_CELLS, LAYOUT_EVIDENCE_IDS, ROW_PAIRS, CELL_ACCOUNTS, RELATION_ACCOUNTS = _build()


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


def placement_gaps(layout: str, row_cells: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Account-free gaps of a journal whose rows carry these cells ("-" = no line).

    VOUCHER_LAYOUT_UNVERIFIED  the layout never round-tripped;
    VOUCHER_TAX_PLACEMENT_UNVERIFIED  a taxed cell that never round-tripped in
    this layout, or a row with tax on both sides that never round-tripped.
    """
    if layout not in LAYOUT_CELLS:
        return ("VOUCHER_LAYOUT_UNVERIFIED",)
    observed = LAYOUT_CELLS[layout]
    for debit, credit in row_cells:
        if (debit, credit) not in ROW_PAIRS:
            if debit not in {"NO", "-"} and credit not in {"NO", "-"}:
                return ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",)
        for side, cell in (("DEBIT", debit), ("CREDIT", credit)):
            if cell not in {"NO", "-"} and (side, cell) not in observed:
                return ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",)
    return ()


def relation_of(cell: str, amount: Decimal, written: Decimal | None) -> str | None:
    """How the written tax relates to the amount for this scope's rounding.

    "" no question (every rounding agrees, or floor == company rounding);
    COMPANY / FLOOR / EXACT / NONE as in the registry; for 軽減8% / 10%免80 with a
    fractional exact value HALF_LOW (written = floor = half-up), HALF_HIGH (written =
    half-up > floor) and FLOOR_HIGH (written = floor < half-up). None = a relation that
    was never observed (never allowed).
    """
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


def relation_accounts(side: str, cell: str, relation: str) -> dict[str, tuple[str, ...]]:
    return RELATION_ACCOUNTS.get((side, cell, relation), {})


# Independence policy for the explicit-tax RELATION gate (separate from the
# (side, cell) coverage gate, which the caller unions with Evidence that
# existed before). Mirrors the general >=3-account rule used elsewhere for
# this Evidence family; 課税売上10% on the credit side stays account-specific
# regardless of how many accounts round-tripped, same as the pre-existing rule.
# The rule reaches an unprobed account only when the company's JDL 科目一覧 prints
# the same tax defaults (課区・税区・入力) for it as for at least three accounts the
# relation round-tripped on (`JDL_TAX_SETTING_PEERS`, generated from the PDF). An
# account with other defaults is covered only where it round-tripped itself.
RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS = 3
RELATION_ACCOUNT_SPECIFIC_ONLY = frozenset({("CREDIT", "S10")})


def relation_covers_account(side: str, cell: str, relation: str, account: str) -> bool:
    """Whether (side, cell, relation) may be used on this account.

    relation in {"", "NONE"}: no amount question; the layout/cell gate already
    decided coverage. Otherwise: round-tripped on this exact account, or
    independent: not account-specific, and the account prints the same JDL tax
    defaults as at least three accounts the relation round-tripped on.
    The single source of truth for this check: both composition and the
    output stage call it, so they can never disagree.
    """
    if relation in {"", "NONE"}:
        return True
    observed = relation_accounts(side, cell, relation)
    if account in observed:
        return True
    if len(observed) < RELATION_ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS or (side, cell) in RELATION_ACCOUNT_SPECIFIC_ONLY:
        return False
    return account in JDL_TAX_SETTING_PEERS.get((side, cell, relation), frozenset())

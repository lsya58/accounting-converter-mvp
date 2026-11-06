"""Compose a journal from the campaign Evidence (only inside its exact scope).

Tried by `moneyforward_tax_excluded_evidence.match_evidence_for_occurrence`
only AFTER the existing MF / ACT composition failed, so every journal the
existing Evidence already covers keeps its evidence, profile and output rows.

A journal is released only when ALL of these hold (each cites its Evidence):
1. the company scope matches exactly (rounding, voucher row limit, tax context);
2. the physical-row count does not exceed the company's voucher row limit;
3. the layout, the taxed cells and the rows round-tripped (scoped_evidence);
4. every taxed line's (side, tax cell, target account) round-tripped —
   the existing MF capabilities and the campaign's are united, and a
   capability observed on fewer than three accounts stays account-specific
   (課税売上10% on the credit side is always account-specific);
5. every explicit tax amount is one of the relations JDL kept unchanged, on
   an account where that relation was observed. Nothing is assumed about how
   JDL treats an unobserved amount.
Anything else returns a gap code; fail-closed. The Human's account, subaccount
and tax confirmations are separate and still required.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from accounting_converter.adapters.output.jdl import JdlEvidenceProfile, JdlTargetContext
from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.journal_rows import journal_physical_rows

GAP_ROW_LIMIT_EXCEEDED = "VOUCHER_ROW_LIMIT_EXCEEDED"
GAP_ROW_LIMIT_UNCONFIRMED = "VOUCHER_ROW_LIMIT_UNCONFIRMED"
_RELATION_GAP = {
    "COMPANY": "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED",
    "FLOOR": "EXPLICIT_TAX_KEEP_UNVERIFIED",
}


@dataclass(frozen=True)
class ScopedLine:
    side: str
    account: str
    cell: str
    amount: Decimal
    written_tax: Decimal | None


def united_capabilities() -> dict[tuple[str, str], ev.TaxLineCapability]:
    """Existing MF capabilities united with the campaign's, per (side, JDL semantic)."""
    accounts: dict[tuple[str, str], set] = {}
    evidence: dict[tuple[str, str], list] = {}
    for key, capability in ev.LINE_CAPABILITIES.items():
        accounts.setdefault(key, set()).update(capability.verified_accounts)
        evidence.setdefault(key, []).extend(capability.evidence_ids)
    for (side, cell), by_account in scoped.CELL_ACCOUNTS.items():
        key = (side, scoped.CELL_SEMANTIC[cell].value)
        accounts.setdefault(key, set()).update(by_account)
        evidence.setdefault(key, []).extend(i for ids in by_account.values() for i in ids)
    return {
        key: ev.TaxLineCapability(key[0], key[1], frozenset(accounts[key]), tuple(dict.fromkeys(evidence[key])))
        for key in accounts
    }


UNITED_CAPABILITIES = united_capabilities()


def line_gaps(line: ScopedLine) -> tuple[list[str], list[str]]:
    """(gaps, supporting Evidence ids) for one taxed line (account level)."""
    if line.cell == "NO":
        capability = ev.LINE_CAPABILITIES.get((line.side, JdlTaxSemantic.NO_TAX.value))
        if capability is None or not capability.covers(line.account):
            return ["TAX_SIDE_UNVERIFIED" if capability is None else "TAX_ACCOUNT_UNVERIFIED"], []
        return [], list(capability.evidence_ids)
    semantic = scoped.CELL_SEMANTIC[line.cell].value
    capability = UNITED_CAPABILITIES.get((line.side, semantic))
    if capability is None:
        return ["TAX_SIDE_UNVERIFIED"], []
    if not capability.covers(line.account):
        return ["TAX_ACCOUNT_UNVERIFIED"], []
    support = list(capability.evidence_ids)
    relation = scoped.relation_of(line.cell, line.amount, line.written_tax)
    if relation is None:
        return ["EXPLICIT_TAX_AMOUNT_UNVERIFIED"], support
    # Single source of truth shared with the output stage (scoped.relation_covers_account),
    # so composition and preflight can never disagree about which account this applies to.
    if not scoped.relation_covers_account(line.side, line.cell, relation, line.account):
        return [_RELATION_GAP.get(relation, "EXPLICIT_TAX_AMOUNT_UNVERIFIED")], support
    if relation not in {"", "NONE"}:
        for ids in scoped.relation_accounts(line.side, line.cell, relation).values():
            support.extend(ids)
    return [], support


def journal_gaps(
    context: JdlTargetContext,
    rows,
    cell_of,
) -> tuple[list[str], list[str]] | None:
    """Gaps and supporting Evidence for the rows of one journal.

    cell_of(line) -> ScopedLine | None for a JournalLine (None = unknown semantic).
    Returns None when a line's tax meaning is unknown (unmapped / not a cell):
    nothing can be said, and above all nothing may be released."""
    gaps: list[str] = []
    support: list[str] = []
    limit = context.voucher_row_limit
    if limit is not None and len(rows) > limit:
        return [GAP_ROW_LIMIT_EXCEEDED], []  # nothing else matters: JDL rejects the voucher
    row_cells = []
    lines: list[ScopedLine] = []
    for row in rows:
        pair = []
        for line in (row.debit, row.credit):
            scoped_line = cell_of(line) if line is not None else None
            if line is not None and scoped_line is None:
                return None  # unmapped / unknown semantic: the Human or the existing gaps decide
            pair.append(scoped_line.cell if scoped_line is not None else "-")
            if scoped_line is not None:
                lines.append(scoped_line)
        row_cells.append(tuple(pair))
    layout = scoped.layout_of(rows)
    placement = scoped.placement_gaps(layout, row_cells)
    gaps.extend(placement)
    if not placement:
        support.extend(scoped.LAYOUT_EVIDENCE_IDS[layout])
    for line in lines:
        line_issue, line_support = line_gaps(line)
        gaps.extend(line_issue)
        support.extend(line_support)
    return gaps, support


def compose_scoped(
    source: JournalEntry,
    signature: tuple[tuple[str, str, str, str], ...],
    *,
    has_partner: bool,
    context: JdlTargetContext,
) -> tuple[ev.MfTaxExcludedPatternEvidence | None, tuple[str, ...] | None]:
    """(evidence, None) when covered; (None, gaps) when the scope applies but is not
    covered; (None, None) when the scope does not apply (the existing gaps stand)."""
    state = scoped.scope_state(context)
    if state is scoped.ScopeState.OUT_OF_SCOPE or has_partner:
        return None, None
    rows = journal_physical_rows(source)
    if rows is None:
        return None, None
    info = {
        id(line): (account, sub, tax)
        for line, (_side, account, sub, tax) in zip(source.lines, signature, strict=True)
    }
    # Same Human gap compose_capabilities enforces: a blank subaccount on a
    # parent the JDL master requires one for is never released automatically
    # by this Evidence (which round-tripped on no-subaccount accounts only).
    if any(
        not sub and account and context.parent_has_subaccounts(code=account)
        for account, sub, _tax in info.values()
    ):
        return None, ("SUBACCOUNT_REQUIRED_BY_MASTER",)

    def cell_of(line):
        account, _sub, tax = info[id(line)]
        cell = scoped.SEMANTIC_CELL.get(tax)
        if cell is None or not account:
            return None
        explicit = line.tax_info.tax_amount if line.tax_info else None
        if cell in {"S10", "P10"} and explicit is None:
            explicit = ev.ten_percent_tax_amount(line.amount)  # what would be written
        return ScopedLine(line.side.value, account, cell, line.amount, explicit)

    found = journal_gaps(context, rows, cell_of)
    if found is None:
        return None, None
    gaps, support = found
    if state is scoped.ScopeState.VOUCHER_ROW_LIMIT_UNCONFIRMED:
        return None, tuple(dict.fromkeys([*gaps, GAP_ROW_LIMIT_UNCONFIRMED]))
    if gaps:
        return None, tuple(dict.fromkeys(gaps))
    return (
        ev.MfTaxExcludedPatternEvidence(
            scoped.SCOPED_ROUTE_ID,
            signature,
            JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL,
            False,
            tuple(dict.fromkeys([*support, scoped.VOUCHER_ROW_LIMIT_EVIDENCE_ID])),
        ),
        None,
    )


def structural_gaps(source: JournalEntry, taxed_value, context: JdlTargetContext) -> tuple[str, ...] | None:
    """Account-free structural gaps (layout, placement, row limit) for the structural diagnosis.

    taxed_value(line) -> JDL semantic value or None. None result = scope does not apply
    (use the existing shape rules)."""
    state = scoped.scope_state(context)
    if state is scoped.ScopeState.OUT_OF_SCOPE:
        return None
    rows = journal_physical_rows(source)
    if rows is None:
        return None
    gaps: list[str] = []
    limit = context.voucher_row_limit
    if limit is not None and len(rows) > limit:
        return (GAP_ROW_LIMIT_EXCEEDED,)
    row_cells = []
    for row in rows:
        pair = []
        for line in (row.debit, row.credit):
            if line is None:
                pair.append("-")
                continue
            value = taxed_value(line)
            if value is None:
                return None
            cell = scoped.SEMANTIC_CELL.get(value)
            if cell is None:
                return None
            pair.append(cell)
        row_cells.append(tuple(pair))
    gaps.extend(scoped.placement_gaps(scoped.layout_of(rows), row_cells))
    if state is scoped.ScopeState.VOUCHER_ROW_LIMIT_UNCONFIRMED:
        gaps.append(GAP_ROW_LIMIT_UNCONFIRMED)
    return tuple(dict.fromkeys(gaps))

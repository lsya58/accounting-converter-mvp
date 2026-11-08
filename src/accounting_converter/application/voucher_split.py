"""Split a Yayoi journal that exceeds the JDL 振替伝票入力行数 into several JDL vouchers: Human-approved only.

JDL Evidence `EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001`: with 振替伝票入力行数 16 a CSV voucher of 16
rows imports; 17 / 25 / 50 / 73 rows are rejected at Import ("伝票内の仕訳数が多すぎます"). So such a journal can
only reach JDL as more than one voucher. Which split is acceptable is an accounting decision, so nothing here
runs unless the Human has recorded, for this company, the tax accountant's agreement to this exact rule.

The only rule (SINGLE_COUNTERPART_BALANCED_V1). A journal qualifies when ALL hold:
  - its physical rows exceed the company's confirmed row limit;
  - one side has exactly ONE line (the counterpart, e.g. 未払金 / 未払費用) and it carries no tax (対象外,
    mapped to JDL 対象外) and sits on the first physical row;
  - every other line is on the other side, one per physical row (the first row may also hold one of them);
  - it is not a closing entry, every amount is positive.
Split: keep the other lines in their original order, cut them into the fewest parts of at most (limit - 1) lines,
as equal as possible (earlier parts take the extra line). Each part gets the counterpart line with exactly the sum
of its lines (same account, subaccount, tax, row and description). Nothing else changes: no line is moved
between sides, no amount or tax of the other lines changes, no line is added (no dummy account), no tax is
allocated (the counterpart has none). Part 1 keeps the original first row; later parts carry the counterpart on
its own row. Every part must then pass the existing JDL Evidence by itself (assess); an unverified part blocks the
original journal. The audit file records the split and that the parts rebuild the original exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal

from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.journal_identity import JOURNAL_CONTENT_IDENTITY_KEY
from accounting_converter.domain.journal_rows import LINE_ROW_KEY, ROW_ORDER_KEY, journal_physical_rows
from accounting_converter.domain.mapping import MappingStatus, MappingValue

RULE = "SINGLE_COUNTERPART_BALANCED_V1"
POLICY_KEY = "yayoi_voucher_split:" + RULE
SPLIT_OF_KEY = "voucher_split_of"            # chunk entry metadata: original journal id
SPLIT_PART_KEY = "voucher_split_part"        # (k, n)
COUNTERPART_TAX_IDENTITY = "対象外"


@dataclass(frozen=True)
class SplitPlan:
    journal_id: str
    counterpart_side: str
    counterpart_row: int
    counterpart_amount: Decimal
    parts: tuple[tuple[int, ...], ...]   # per part: source row numbers of the other-side lines


def ineligible_reason(entry: JournalEntry, row_limit: int | None) -> str | None:
    """None when the journal qualifies for the rule; else a short reason code."""
    if row_limit is None or row_limit < 2:
        return "ROW_LIMIT_UNCONFIRMED"
    rows = journal_physical_rows(entry)
    if rows is None:
        return "ROW_SEMANTICS_MISSING"
    from accounting_converter.adapters.output.jdl.scoped_evidence import exceeds_row_limit

    if not exceeds_row_limit(rows, row_limit):
        return "WITHIN_LIMIT"
    if entry.metadata.get("yayoi_closing"):
        return "CLOSING_ENTRY"
    debits = [line for line in entry.lines if line.side is Side.DEBIT]
    credits = [line for line in entry.lines if line.side is Side.CREDIT]
    if len(credits) == 1 and len(debits) > 1:
        anchor, others = credits[0], debits
    elif len(debits) == 1 and len(credits) > 1:
        anchor, others = debits[0], credits
    else:
        return "MORE_THAN_ONE_LINE_ON_BOTH_SIDES"
    info = anchor.tax_info
    if info is not None and (info.category or "") not in {"", COUNTERPART_TAX_IDENTITY}:
        return "COUNTERPART_TAXED"
    if info is not None and info.tax_amount not in (None, Decimal(0)):
        return "COUNTERPART_TAXED"
    if anchor.metadata.get(LINE_ROW_KEY) != rows[0].row_number:
        return "COUNTERPART_NOT_ON_FIRST_ROW"
    if any(line.amount <= 0 for line in entry.lines):
        return "NON_POSITIVE_AMOUNT"
    other_side = others[0].side
    for row in rows:
        mine = row.debit if other_side is Side.DEBIT else row.credit
        theirs = row.credit if other_side is Side.DEBIT else row.debit
        if theirs is not None and theirs is not anchor:
            return "COUNTERPART_SIDE_HAS_MORE_ROWS"
        if mine is None and theirs is not anchor:
            return "EMPTY_ROW"
    return None


def plan_split(entry: JournalEntry, row_limit: int) -> SplitPlan | None:
    if ineligible_reason(entry, row_limit) is not None:
        return None
    rows = journal_physical_rows(entry)
    debits = [line for line in entry.lines if line.side is Side.DEBIT]
    anchor = [line for line in entry.lines if line.side is (Side.CREDIT if len(debits) > 1 else Side.DEBIT)][0]
    other_rows = tuple(row.row_number for row in rows
                       if (row.debit if anchor.side is Side.CREDIT else row.credit) is not None)
    per_part = row_limit - 1
    parts_count = -(-len(other_rows) // per_part)
    base, extra = divmod(len(other_rows), parts_count)
    parts, cursor = [], 0
    for index in range(parts_count):
        size = base + (1 if index < extra else 0)
        parts.append(other_rows[cursor: cursor + size])
        cursor += size
    return SplitPlan(entry.id, anchor.side.value, rows[0].row_number, anchor.amount, tuple(parts))


def split_entry(entry: JournalEntry, plan: SplitPlan) -> tuple[JournalEntry, ...]:
    anchor = next(line for line in entry.lines if line.side.value == plan.counterpart_side)
    by_row = {line.metadata[LINE_ROW_KEY]: line for line in entry.lines if line is not anchor}
    chunks = []
    total = len(plan.parts)
    for number, rows in enumerate(plan.parts, start=1):
        others = [by_row[row] for row in rows]
        portion = sum((line.amount for line in others), Decimal(0))
        counterpart = replace(anchor, amount=portion, metadata=dict(anchor.metadata))
        lines = sorted([counterpart, *others], key=lambda line: (line.metadata[LINE_ROW_KEY], line.side is Side.CREDIT))
        order = tuple(sorted({line.metadata[LINE_ROW_KEY] for line in lines}))
        chunks.append(replace(
            entry,
            id=f"{entry.id}#part{number}of{total}",
            lines=lines,
            metadata={
                **entry.metadata,
                ROW_ORDER_KEY: order,
                JOURNAL_CONTENT_IDENTITY_KEY: f"{entry.metadata.get(JOURNAL_CONTENT_IDENTITY_KEY)}#part{number}of{total}",
                SPLIT_OF_KEY: entry.id,
                SPLIT_PART_KEY: (number, total),
            },
        ))
    problems = reconstruction_problems(entry, tuple(chunks), plan)
    if problems:  # never hand over parts that do not rebuild the original
        raise ValueError(f"{entry.id}: split does not rebuild the original: {problems}")
    return tuple(chunks)


def _line_key(line) -> tuple:
    info = line.tax_info
    return (line.side.value, line.account, line.sub_account, line.department, line.amount,
            info.category if info else None, info.tax_amount if info else None,
            line.metadata.get(LINE_ROW_KEY), line.metadata.get("journal_row_description"))


def reconstruction_problems(original: JournalEntry, chunks: tuple[JournalEntry, ...], plan: SplitPlan,
                            row_limit: int | None = None) -> list[str]:
    """Empty when the parts rebuild the original journal exactly (the check the audit file records)."""
    problems = []
    anchor = next(line for line in original.lines if line.side.value == plan.counterpart_side)
    originals = sorted(_line_key(line) for line in original.lines if line is not anchor)
    seen, portions = [], []
    for chunk in chunks:
        if chunk.date != original.date:
            problems.append("DATE_CHANGED")
        if chunk.debit_total() != chunk.credit_total():
            problems.append("PART_NOT_BALANCED")
        rows = journal_physical_rows(chunk)
        if rows is None:
            problems.append("PART_ROWS_INVALID")
        elif row_limit is not None and len(rows) > row_limit:
            problems.append("PART_OVER_LIMIT")
        counterparts = [line for line in chunk.lines if line.side.value == plan.counterpart_side]
        if len(counterparts) != 1:
            problems.append("PART_COUNTERPART_COUNT")
            continue
        portion = counterparts[0]
        if _line_key(replace(portion, amount=anchor.amount)) != _line_key(anchor):
            problems.append("COUNTERPART_CHANGED")
        portions.append(portion.amount)
        seen.extend(_line_key(line) for line in chunk.lines if line is not portion)
    if sorted(seen) != originals:
        problems.append("LINES_NOT_PRESERVED_EXACTLY_ONCE")
    if sum(portions, Decimal(0)) != anchor.amount:
        problems.append("COUNTERPART_SUM_DIFFERS")
    return sorted(set(problems))


# ---------------------------------------------------------------- Human approval (company scoped)
def approve_split_policy(store, profile_id: str, company_setting_id: str, context, *, human_approver: str,
                         tax_accountant: str, signoff_reference: str, signoff_date: date):
    """Record the Human's statement that the tax accountant accepted this rule for this company and row limit."""
    problems = []
    if context is None or context.voucher_row_limit is None:
        problems.append("ROW_LIMIT_UNCONFIRMED")
    if not all(isinstance(v, str) and v.strip() for v in (human_approver, tax_accountant, signoff_reference)) \
            or not isinstance(signoff_date, date):
        problems.append("SIGNOFF_MISSING")
    if problems:
        raise ValueError("伝票分割の承認はできません: " + ", ".join(problems))
    profile = store.get(profile_id)
    policies = dict(profile.loss_policy_mappings)
    policies[POLICY_KEY] = MappingValue(POLICY_KEY, RULE, MappingStatus.USER_CONFIRMED, metadata={
        "rule": RULE,
        "company_setting_id": company_setting_id,
        "profile_id": profile_id,
        "voucher_row_limit": str(context.voucher_row_limit),
        "human_approver": human_approver.strip(),
        "tax_accountant": tax_accountant.strip(),
        "signoff_reference": signoff_reference.strip(),
        "signoff_date": signoff_date.isoformat(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    })
    return store.update(replace(profile, loss_policy_mappings=policies, updated_at=datetime.now(timezone.utc)))


def policy_problems(profile, context) -> tuple[str, ...]:
    policy = (getattr(profile, "loss_policy_mappings", None) or {}).get(POLICY_KEY)
    if policy is None or policy.status is not MappingStatus.USER_CONFIRMED or policy.target_value != RULE:
        return ("SPLIT_NOT_APPROVED",)
    meta = policy.metadata or {}
    problems = []
    if context is None or context.voucher_row_limit is None or meta.get("voucher_row_limit") != str(context.voucher_row_limit):
        problems.append("ROW_LIMIT_DIFFERS_FROM_APPROVAL")
    if meta.get("profile_id") != getattr(profile, "profile_id", None) or meta.get("rule") != RULE:
        problems.append("APPROVAL_INVALID")
    if not all(str(meta.get(k, "")).strip() for k in ("human_approver", "tax_accountant", "signoff_reference", "signoff_date")):
        problems.append("SIGNOFF_MISSING")
    return tuple(problems)


def counterpart_mapped_to_no_tax(entry: JournalEntry, plan: SplitPlan, profile, context) -> bool:
    """The counterpart has no Yayoi tax, or its Yayoi 対象外 is confirmed as JDL 対象外 for this company."""
    from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    anchor = next(line for line in entry.lines if line.side.value == plan.counterpart_side)
    if anchor.tax_info is None or not anchor.tax_info.category:
        return True
    return ev.target_tax_semantic(anchor, profile, context) == JdlTaxSemantic.NO_TAX.value


APPROVAL_BLOCKER = "HUMAN:VOUCHER_SPLIT_APPROVAL"


def apply_split(entries, profile, context, *, assume_approved: bool = False) -> list[JournalEntry]:
    """Entries with every qualifying over-limit journal replaced by its parts (only with a valid approval).

    assume_approved: diagnosis only (assess), to tell "the parts are verified, only the approval is missing" from
    "a part has no Evidence". The conversion path never passes it.
    """
    if profile is None or context is None or (policy_problems(profile, context) and not assume_approved):
        return list(entries)
    result = []
    for entry in entries:
        plan = plan_split(entry, context.voucher_row_limit)
        if plan is None or not counterpart_mapped_to_no_tax(entry, plan, profile, context):
            result.append(entry)
            continue
        result.extend(split_entry(entry, plan))
    return result


def audit_record(entry: JournalEntry, profile, context) -> dict | None:
    """What the audit file keeps for a split journal (None when the journal is not split)."""
    if profile is None or context is None or policy_problems(profile, context):
        return None
    plan = plan_split(entry, context.voucher_row_limit)
    if plan is None or not counterpart_mapped_to_no_tax(entry, plan, profile, context):
        return None
    chunks = split_entry(entry, plan)
    meta = profile.loss_policy_mappings[POLICY_KEY].metadata
    problems = reconstruction_problems(entry, chunks, plan, context.voucher_row_limit)
    return {
        "rule": RULE,
        "voucher_row_limit": context.voucher_row_limit,
        "original_physical_rows": len(journal_physical_rows(entry)),
        "counterpart": {"side": plan.counterpart_side, "row": plan.counterpart_row,
                        "amount": str(plan.counterpart_amount)},
        "parts": [{"part": k, "jdl_voucher_rows": len(journal_physical_rows(chunk)),
                   "source_rows": list(rows), "counterpart_amount": str(
                       next(l.amount for l in chunk.lines if l.side.value == plan.counterpart_side))}
                  for k, (rows, chunk) in enumerate(zip(plan.parts, chunks), start=1)],
        "reconstruction": "PASS" if not problems else "FAIL:" + ",".join(problems),
        "human_approver": meta.get("human_approver", ""),
        "tax_accountant": meta.get("tax_accountant", ""),
        "tax_accountant_signoff_reference": meta.get("signoff_reference", ""),
        "tax_accountant_signoff_date": meta.get("signoff_date", ""),
    }

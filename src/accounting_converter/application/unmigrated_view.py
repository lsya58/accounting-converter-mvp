"""The journals a READY-only run leaves out, in plain language (read-only; works with or without a tracker).

The rows come from the production READY-only plan (the same diagnosis that decided READY / BLOCK), so they can be
shown before any tracker exists. A tracker, when it belongs to exactly this run, only adds the working status. Nothing
here approves anything, changes a status or changes a READY / BLOCK decision."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from accounting_converter.application import approval_ledger as al
from accounting_converter.application import migration_tracker as mt
from accounting_converter.application import voucher_split as vs
from accounting_converter.application.resolution_report import rule_for_code

ROW_LIMIT_CODE = "HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED"
NO_TRACKER_STATUS = "未対応（管理表は未作成）"
CSV_HEADER = ("元の行", "伝票No.", "日付", "BLOCK理由", "現在の状態", "必要な税理士判断", "技術的な未解決条件", "次に必要な作業")


@dataclass(frozen=True)
class UnmigratedRow:
    source_row: int
    voucher: str
    date: str
    debit_total: str
    reasons: tuple[str, ...]        # plain titles of every BLOCK code
    codes: tuple[str, ...]
    status: str                     # tracker status label, or NO_TRACKER_STATUS
    status_code: str | None
    accountant: tuple[str, ...]     # decisions only the tax accountant can make
    technical: tuple[str, ...]      # conditions that need Evidence / implementation / manual work
    next_steps: tuple[str, ...]
    plan: str = ""
    owner: str = ""


def _decisions(row, codes, items) -> list[str]:
    out = []
    for item in items:
        if not any(t.source_row == row for t in item.targets):
            continue
        if item.kind == al.KIND_SPLIT and (vs.APPROVAL_BLOCKER in codes or ROW_LIMIT_CODE in codes):
            # a journal with another open condition reports the row limit instead of "approval pending", but the split
            # approval is still one of the things it needs (the split item names this journal)
            out.append(f"伝票分割の承認（{item.item_id}）")
        elif item.kind == al.KIND_NONCREDIT and "HUMAN:TAX_MAPPING" in codes:
            out.append(f"控除不可の承認（{item.item_id}）")
    for code in codes:
        rule = rule_for_code(code)
        if rule.tax_accountant and not rule.technical_evidence and rule.title not in out and code not in ("HUMAN:TAX_MAPPING", vs.APPROVAL_BLOCKER, ROW_LIMIT_CODE):
            out.append(rule.title)
    return out


def build_rows(plan, items, tracker: dict | None = None) -> tuple[UnmigratedRow, ...]:
    """One row per excluded journal, in source order. `tracker` (already verified against this run) adds the status."""
    tracked = {j["source_row"]: j for j in (tracker or {}).get("journals", ())}
    rows = []
    for item in plan.excluded:
        codes = tuple(item.blockers)
        titles = tuple(dict.fromkeys(rule_for_code(c).title for c in codes))
        accountant = _decisions(item.source_row, codes, items)
        technical = tuple(dict.fromkeys(
            rule_for_code(c).title for c in codes
            if c.startswith(("SYSTEM_EVIDENCE:", "SYSTEM_IMPLEMENTATION:")) or rule_for_code(c).technical_evidence
            or rule_for_code(c).jdl_work or (not rule_for_code(c).tax_accountant and c.startswith("HUMAN:")
                                              and c not in ("HUMAN:TAX_MAPPING", vs.APPROVAL_BLOCKER))))
        steps = []
        if accountant:
            steps.append("税理士の判断を得て、承認を記録・適用する（台帳CLI）→ 再診断 → READY-only出力を作り直す")
        steps.extend(dict.fromkeys(rule_for_code(c).todo for c in codes if rule_for_code(c).todo
                                   and rule_for_code(c).todo not in steps))
        steps.append("JDLで手入力する場合は、未移行管理表に入力と照合を記録する（手入力だけでは移行完了になりません）")
        found = tracked.get(item.source_row)
        status = mt.STATES.get(found["status"], found["status"]) if found else NO_TRACKER_STATUS
        rows.append(UnmigratedRow(
            item.source_row, item.voucher, item.date, str(item.debit_total), titles, codes, status,
            found["status"] if found else None, tuple(accountant), technical, tuple(steps),
            (found or {}).get("plan", ""), (found or {}).get("owner", "")))
    return tuple(rows)


def rows_csv(rows) -> bytes:
    """The management sheet for people (UTF-8 BOM), from the rows as shown."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        writer.writerow((r.source_row, r.voucher, r.date, " / ".join(r.reasons), r.status, " / ".join(r.accountant),
                         " / ".join(r.technical), " / ".join(r.next_steps)))
    return buffer.getvalue().encode("utf-8-sig")

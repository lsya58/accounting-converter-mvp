"""Yayoi → JDL round-trip check: Yayoi source ↔ formal JDL CSV ↔ JDL re-export.

Prints counts and pass/fail only (no names, descriptions or amounts).

1. source ↔ candidate: journal and physical-row counts, every line as
   (date, side, JDL account code, JDL subaccount code, amount, tax amount),
   row descriptions, journal structure, debit/credit/tax totals.
2. candidate ↔ re-export (when given): the existing strict JDL comparator
   (only known JDL canonical normalizations allowed).
3. information not written to JDL: the audit file must exist, match the
   candidate's SHA-256 and list exactly the journals the assessment reports.

PASS only when every section has zero missing / extra / unexpected items.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.moneyforward_description_replacement import (
    MoneyForwardDescriptionReplacementPolicy,
)
from accounting_converter.application.yayoi_jdl_workflow import verify_non_retained_audit
from accounting_converter.application.yayoi_sources import detect_format, format_for_identity_key
from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, LINE_ROW_KEY
from accounting_converter.domain.mapping import is_confirmed_parent_only
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools import mf_full_e2e_compare

TAXED = {JdlTaxSemantic.PURCHASE_10_INTERNAL.value, JdlTaxSemantic.SALES_10_EXTERNAL.value}


def _decimal(value: str) -> Decimal:
    return Decimal(value or "0")


def candidate_view(path: Path):
    rows = mf_full_e2e_compare._rows(path)
    groups = mf_full_e2e_compare._groups(rows)
    lines, descriptions, structure = Counter(), Counter(), Counter()
    for group in groups:
        debit = sum(1 for row in group if row[3])
        credit = sum(1 for row in group if row[13])
        structure[(group[0][2], debit, credit, len(group))] += 1
        for row in group:
            descriptions[(row[2], row[23])] += 1
            if row[3]:
                lines[(row[2], "DEBIT", row[3], row[6].zfill(4) if row[6] else "", _decimal(row[11]), _decimal(row[12]))] += 1
            if row[13]:
                lines[(row[2], "CREDIT", row[13], row[16].zfill(4) if row[16] else "", _decimal(row[21]), _decimal(row[22]))] += 1
    return len(groups), len(rows), lines, descriptions, structure


def _subaccount_code(profile, account: str, sub: str | None) -> str:
    if not sub:
        return ""
    for key, value in profile.subaccount_context_mappings.items():
        if key.parent_account == account and key.source_value == sub:
            if is_confirmed_parent_only(value):
                return ""  # parent only: JDL gets a blank subaccount, the name is in the audit file
            return str(value.metadata.get("output_code", "")).zfill(4)
    return "?"


def source_view(source: Path, profile, context):
    source_format = format_for_identity_key(profile.source_format_identity.stable_key) or detect_format(source)
    # The JDL vouchers expected: a Human-approved split turns one journal into its parts (voucher_split).
    from accounting_converter.application.voucher_split import apply_split

    from accounting_converter.application.closing_entries import mark_closing

    entries = MoneyForwardDescriptionReplacementPolicy(profile).apply(
        apply_split(mark_closing(source_format.read(source), profile, context), profile, context)).entries
    lines, descriptions, structure = Counter(), Counter(), Counter()
    rows = 0
    for entry in entries:
        from accounting_converter.application.closing_entries import JDL_DATE_KEY

        day = entry.metadata.get(JDL_DATE_KEY) or entry.date.strftime("%Y%m%d")
        by_row: dict[int, list] = {}
        for line in entry.lines:
            by_row.setdefault(int(line.metadata[LINE_ROW_KEY]), []).append(line)
            mapping = profile.account_mappings.get(line.account)
            code = str(mapping.metadata.get("target_code", "?")) if mapping else "?"
            semantic = ev.target_tax_semantic(line, profile, context) if line.tax_info else JdlTaxSemantic.NO_TAX.value
            tax = Decimal("0")
            if semantic in TAXED:
                explicit = line.tax_info.tax_amount
                tax = explicit if explicit is not None else ev.ten_percent_tax_amount(line.amount)
            lines[(day, line.side.value, code, _subaccount_code(profile, line.account, line.sub_account),
                   Decimal(line.amount), tax)] += 1
        rows += len(by_row)
        for row_lines in by_row.values():
            descriptions[(day, row_lines[0].metadata.get(LINE_ROW_DESCRIPTION_KEY) or entry.description or "")] += 1
        debit = sum(1 for line in entry.lines if line.side.value == "DEBIT")
        structure[(day, debit, len(entry.lines) - debit, len(by_row))] += 1
    return entries, len(entries), rows, lines, descriptions, structure


def _diff(expected: Counter, actual: Counter) -> dict[str, int]:
    return {"missing": sum((expected - actual).values()), "extra": sum((actual - expected).values())}


def check(source: Path, profile, context, candidate: Path, reexport: Path | None) -> dict:
    entries, source_journals, source_rows, s_lines, s_desc, s_struct = source_view(source, profile, context)
    c_journals, c_rows, c_lines, c_desc, c_struct = candidate_view(candidate)
    totals = {
        side: (sum(k[4] for k, n in s_lines.items() for _ in range(n) if k[1] == side),
               sum(k[4] for k, n in c_lines.items() for _ in range(n) if k[1] == side))
        for side in ("DEBIT", "CREDIT")
    }
    tax_totals = (sum(k[5] * n for k, n in s_lines.items()), sum(k[5] * n for k, n in c_lines.items()))
    source_vs_candidate = {
        "journals_equal": source_journals == c_journals,
        "physical_rows_equal": source_rows == c_rows,
        "lines_account_subaccount_amount_tax_date": _diff(s_lines, c_lines),
        "row_descriptions": _diff(s_desc, c_desc),
        "journal_structure": _diff(s_struct, c_struct),
        "debit_total_equal": totals["DEBIT"][0] == totals["DEBIT"][1],
        "credit_total_equal": totals["CREDIT"][0] == totals["CREDIT"][1],
        "tax_total_equal": tax_totals[0] == tax_totals[1],
    }
    source_ok = (
        all(source_vs_candidate[k] for k in ("journals_equal", "physical_rows_equal", "debit_total_equal",
                                             "credit_total_equal", "tax_total_equal"))
        and all(not any(v.values()) for v in source_vs_candidate.values() if isinstance(v, dict))
    )
    preservation = verify_non_retained_audit(source, candidate, profile, context)
    result = {
        "source": {"journals": source_journals, "physical_rows": source_rows},
        "candidate": {"journals": c_journals, "physical_rows": c_rows},
        "source_vs_candidate": source_vs_candidate,
        "information_not_in_jdl": preservation,
        "information_fully_retained": preservation["verdict"] == "NOT_NEEDED",
    }
    if reexport is None:
        result["candidate_vs_reexport"] = "NOT_RUN (no re-export given)"
        reexport_ok = None
    else:
        try:
            comparison = mf_full_e2e_compare.compare(candidate, reexport)
        except ValueError as exc:  # unreadable or unbalanced re-export
            comparison = {"strict_passed": False, "error": type(exc).__name__}
        result["candidate_vs_reexport"] = comparison
        reexport_ok = bool(comparison["strict_passed"])
    # Two separate verdicts: what JDL received, and what was kept outside JDL.
    if not source_ok or reexport_ok is False:
        jdl = "FAIL"
    elif reexport_ok is None:
        jdl = "SOURCE_TO_CSV_PASS_REEXPORT_PENDING"
    else:
        jdl = "PASS"
    result["verdict_jdl_roundtrip"] = jdl
    result["verdict_information_outside_jdl"] = preservation["verdict"]
    result["verdict"] = (
        "PASS" if jdl == "PASS" and preservation["verdict"] in {"PASS", "NOT_NEEDED"}
        else "FAIL" if jdl == "FAIL" or preservation["verdict"] == "FAIL"
        else jdl
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--candidate", type=Path, required=True, help="formal JDL CSV generated by this app")
    parser.add_argument("--reexport", type=Path, help="JDL re-export of the same period from the test company")
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
    print(json.dumps(check(args.source, resolved.profile, resolved.context, args.candidate, args.reexport),
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

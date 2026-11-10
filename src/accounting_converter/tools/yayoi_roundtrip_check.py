"""Yayoi → JDL round-trip check: Yayoi source ↔ formal JDL CSV ↔ JDL re-export.

Prints counts and pass/fail only (no names, descriptions or amounts).

1. source ↔ candidate: journal and physical-row counts, every line as
   (date, side, JDL account code, JDL subaccount code, amount, tax amount),
   row descriptions, journal structure, debit/credit/tax totals.
2. candidate ↔ re-export (when given): the existing strict JDL comparator
   (only known JDL canonical normalizations allowed). Inside the scope of
   jdl_description_trailing_space, a 摘要 whose only change is an observed
   trailing-space removal is reported row by row as Evidence-backed
   information loss (never a silent pass).
3. information not written to JDL: the audit file (found by name, or by the
   candidate's SHA-256 when the CSV was renamed) must match the candidate and
   list exactly the journals the assessment reports.

Verdicts: PASS = nothing but canonical normalizations. PASS_WITH_ACCEPTED_NORMALIZATION =
additionally only Evidence-backed losses the user accepted (acceptance file). Such losses
without a valid acceptance: NORMALIZATION_ACCEPTANCE_PENDING (not a PASS). Anything
unexplained: FAIL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import jdl_description_trailing_space as trailing
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
    physical = []  # one item per JDL physical row, in output order (source provenance)
    for entry in entries:
        from accounting_converter.application.closing_entries import JDL_DATE_KEY

        day = entry.metadata.get(JDL_DATE_KEY) or entry.date.strftime("%Y%m%d")
        by_row: dict[int, list] = {}
        for line in entry.lines:
            by_row.setdefault(int(line.metadata[LINE_ROW_KEY]), []).append(line)
            mapping = profile.account_mappings.get(line.account)
            code = str(mapping.metadata.get("target_code", "?")) if mapping else "?"
            semantic = ev.target_tax_semantic(line, profile, context) if line.tax_info else JdlTaxSemantic.NO_TAX.value
            # The writer's own rule (blank = 0 in the comparison), so 軽減8% / 10%免80 keep the source tax.
            tax = ev.target_tax_amount(semantic, line, Decimal(line.amount)) or Decimal("0")
            lines[(day, line.side.value, code, _subaccount_code(profile, line.account, line.sub_account),
                   Decimal(line.amount), tax)] += 1
        rows += len(by_row)
        for row_number, row_lines in by_row.items():
            description = row_lines[0].metadata.get(LINE_ROW_DESCRIPTION_KEY) or entry.description or ""
            descriptions[(day, description)] += 1
            physical.append({"date": day, "source_row": row_number, "description": description,
                             "voucher": entry.metadata.get("yayoi_voucher_number"),
                             "journal_numbers": sorted({str(line.metadata.get("yayoi_journal_number") or "")
                                                        for line in row_lines} - {""})})
        debit = sum(1 for line in entry.lines if line.side.value == "DEBIT")
        structure[(day, debit, len(entry.lines) - debit, len(by_row))] += 1
    return entries, len(entries), rows, lines, descriptions, structure, physical


def _diff(expected: Counter, actual: Counter) -> dict[str, int]:
    return {"missing": sum((expected - actual).values()), "extra": sum((actual - expected).values())}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trailing_space_rows(candidate: Path, reexport: Path, loss_rows, physical,
                        usable: frozenset[str] = trailing.EVIDENCE.observed_suffixes) -> tuple[list[dict], bool]:
    """Row-level record of every Evidence-backed 摘要 loss, traced to the source row (customer data)."""
    c_rows, r_rows = mf_full_e2e_compare._rows(candidate), mf_full_e2e_compare._rows(reexport)
    records, aligned = [], len(physical) == len(c_rows)
    for index in loss_rows:
        before, after = c_rows[index - 1][23], r_rows[index - 1][23]
        suffix = trailing.removed_trailing_suffix(before, after, usable)
        entry = trailing.evidence_for_suffix(suffix) if suffix else None
        origin = physical[index - 1] if aligned else None
        if origin is None or origin["date"] != c_rows[index - 1][2] or origin["description"] != before:
            aligned = False
            origin = {}
        records.append({
            "row": index, "evidence_id": entry.evidence_id if entry else None,
            "date": c_rows[index - 1][2], "voucher": origin.get("voucher"),
            "journal_numbers": origin.get("journal_numbers"), "source_row": origin.get("source_row"),
            "removed": trailing.suffix_counts(suffix or ""),
            "candidate_description": before, "reexport_description": after,
        })
    return records, aligned


def check(source: Path, profile, context, candidate: Path, reexport: Path | None, *,
          company_setting_id: str | None = None, acceptance: Path | None = None) -> dict:
    entries, source_journals, source_rows, s_lines, s_desc, s_struct, physical = source_view(source, profile, context)
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
    scope = trailing.scope_problems(company_setting_id, context)   # every entry shares this scope
    suffixes = trailing.applicable_suffixes(company_setting_id, context)
    reexport_ok, loss = None, None
    if reexport is None:
        result["candidate_vs_reexport"] = "NOT_RUN (no re-export given)"
    else:
        try:
            comparison = mf_full_e2e_compare.compare(candidate, reexport, description_trailing_space_suffixes=suffixes)
        except ValueError as exc:  # unreadable or unbalanced re-export
            comparison = {"strict_passed": False, "error": type(exc).__name__}
        result["candidate_vs_reexport"] = comparison
        reexport_ok = bool(comparison["strict_passed"])
        if not reexport_ok and comparison.get("passed_with_evidenced_information_loss"):
            rows, aligned = trailing_space_rows(candidate, reexport, comparison["evidenced_information_loss_rows"],
                                                physical, suffixes)
            candidate_sha, reexport_sha = _sha256(candidate), _sha256(reexport)
            used = [item for item in trailing.EVIDENCES
                    if any(row["evidence_id"] == item.evidence_id for row in rows)]
            entries = [{
                "evidence_id": item.evidence_id, "technical_state": item.technical_state,
                "condition": item.condition, "rows": sum(r["evidence_id"] == item.evidence_id for r in rows),
                "evidence_files": {"candidate": item.candidate_sha256, "reexport": item.reexport_sha256},
                "this_round_is_the_evidence_round": (candidate_sha, reexport_sha)
                == (item.candidate_sha256, item.reexport_sha256),
            } for item in used]
            loss = {
                "evidence_ids": [entry["evidence_id"] for entry in entries],
                "evidence_entries": entries,
                "technical_state": trailing.EVIDENCE.technical_state,
                "this_round_is_the_evidence_round": any(e["this_round_is_the_evidence_round"] for e in entries),
                "files": {"candidate": {"name": candidate.name, "sha256": candidate_sha},
                          "reexport": {"name": reexport.name, "sha256": reexport_sha}},
                "rows_count": len(rows), "journals_count": len({(r["date"], r["voucher"]) for r in rows}),
                "removed_totals": {k: sum(r["removed"][k] for r in rows) for k in ("half_width_space",
                                                                                  "ideographic_space")},
                "source_alignment": "PASS" if aligned else "FAIL",
                "rows_sha256": trailing.rows_sha256(rows),
                "acceptance": trailing.check_acceptance(acceptance, candidate_sha256=candidate_sha,
                                                        reexport_sha256=reexport_sha, rows=rows),
                "rows": rows,
            }
    result["description_trailing_space_scope"] = "IN_SCOPE" if not scope else list(scope)
    # Two separate verdicts: what JDL received, and what was kept outside JDL.
    if not source_ok:
        jdl = "FAIL"
    elif reexport is None:
        jdl = "SOURCE_TO_CSV_PASS_REEXPORT_PENDING"
    elif reexport_ok:
        jdl = "PASS"
    elif loss is None or loss["source_alignment"] != "PASS":
        jdl = "FAIL"
    elif loss["acceptance"]["state"] == trailing.ACCEPTED:
        jdl = "PASS_WITH_ACCEPTED_NORMALIZATION"
    else:
        jdl = "NORMALIZATION_ACCEPTANCE_PENDING"
    if loss is not None:
        result["description_trailing_space_loss"] = loss
    result["verdict_jdl_roundtrip"] = jdl
    result["verdict_information_outside_jdl"] = preservation["verdict"]
    result["verdict"] = "FAIL" if preservation["verdict"] == "FAIL" else jdl
    return result


RECORD_SCHEMA = "jdl-description-trailing-space-record-v1"


def write_record(result: dict, path: Path) -> None:
    """The audit record of the Evidence-backed 摘要 losses (customer data: data/private only, never overwritten)."""
    if "data/private" not in path.resolve().as_posix():
        raise SystemExit("the record contains customer descriptions; write it under data/private only")
    loss = result["description_trailing_space_loss"]
    payload = {"schema": RECORD_SCHEMA, "verdict_jdl_roundtrip": result["verdict_jdl_roundtrip"],
               "source": result["source"], "candidate": result["candidate"], **loss}
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--candidate", type=Path, required=True, help="formal JDL CSV generated by this app")
    parser.add_argument("--reexport", type=Path, help="JDL re-export of the same period from the test company")
    parser.add_argument("--acceptance", type=Path,
                        help="the user's acceptance of the 摘要 trailing-space loss (jdl_description_trailing_space_acceptance)")
    parser.add_argument("--record-out", type=Path,
                        help="write the row-level 摘要 loss record here (data/private only; customer data)")
    args = parser.parse_args()
    profiles = ConversionProfileStore(args.company_store / "profiles")
    resolved = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id)
    result = check(args.source, resolved.profile, resolved.context, args.candidate, args.reexport,
                   company_setting_id=args.company_id, acceptance=args.acceptance)
    if args.record_out is not None and "description_trailing_space_loss" in result:
        write_record(result, args.record_out)
    loss = result.get("description_trailing_space_loss")
    if loss is not None:  # counts only on screen; the descriptions stay in the private record
        loss = {**loss, "rows": f"{len(loss['rows'])} rows (see --record-out)"}
        result = {**result, "description_trailing_space_loss": loss}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

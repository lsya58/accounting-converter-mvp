"""Yayoi 本決 (year-end closing) journals -> JDL 決算整理仕訳 with the month-13 date. Evidence-limited.

Real JDL Evidence (company A, JDL IBEX 出納帳 35.5, 2026-11-07, private `closing_probe_20261107`):
  1. Hand-entered self-export: JDL writes a 決算整理仕訳 with the date YYYY13DD (fiscal year end 2026-07-31 ->
     20261331); the other 29 columns equal those of the same ordinary journal. It is exported only with
     「決算整理を含む」.
  2. CSV Import of app-format journals dated 20261331 (B1 対象外, B1 非仕入 debit, B2, B1C1 — the probe case is
     named CI-B1C2-NO but has 2 rows), imported with
     「決算整理を含む」: re-exported unchanged (strict compare, known normalizations only) only with 決算整理を含む,
     absent without it; the ordinary control in both (`yayoi_closing_probe_check judge-import`:
     CLOSING_IMPORT_PRESERVED).

Applied only when ALL hold (anything else stays SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION):
  - Yayoi 決算 is 本決 (中決 = interim closing: no JDL representation observed);
  - the JDL setting is the exact scope of the Evidence (35.5・税抜・原則・一括比例・端数 売上切上げ/仕入四捨五入・16行);
  - the journal date is a fiscal year end of the observed month/day (07-31);
  - the journal's rows and JDL tax cells are one of the five imported closing shapes (B1 対象外, B1 非仕入 debit,
    B2, B1C1, B1C2).
The written date is never an ordinary date: a closing journal is never turned into an ordinary one. The original
date and 決算 value go to the audit file.
"""
from __future__ import annotations

from datetime import date

EVIDENCE_ID = "EVID-YAYOI-JDL-35-5-BUDDIES-CLOSING-MONTH13-IMPORT-001"
# 2026-11-07 follow-up (private `closing_probe_b1c2_20261107`, judge-import: CLOSING_IMPORT_PRESERVED): the 3-row
# B1C2 closing entry (journal 7531's shape) imported and re-exported unchanged only with 決算整理を含む.
B1C2_EVIDENCE_ID = "EVID-YAYOI-JDL-35-5-BUDDIES-CLOSING-MONTH13-IMPORT-B1C2-001"
SELF_EXPORT_EVIDENCE_ID = "EVID-YAYOI-JDL-35-5-BUDDIES-CLOSING-MONTH13-SELF-EXPORT-001"
FINAL = "本決"
INTERIM = "中決"
OBSERVED_YEAR_END = (7, 31)
JDL_DATE_KEY = "jdl_closing_period_date"      # entry metadata set only by mark_closing
EVIDENCE_KEY = "jdl_closing_evidence_id"
# Row signatures (debit cell, credit cell) that were imported as closing entries and re-exported unchanged.
SHAPE_EVIDENCE = {
    (("NO", "NO"),): EVIDENCE_ID,
    (("NP", "NO"),): EVIDENCE_ID,
    (("NO", "NO"), ("NO", "NO")): EVIDENCE_ID,
    (("NO", "NO"), ("-", "NO")): EVIDENCE_ID,
    (("NO", "NO"), ("-", "NO"), ("-", "NO")): B1C2_EVIDENCE_ID,
}
IMPORTED_SHAPES = frozenset(SHAPE_EVIDENCE)


def jdl_closing_date(day: date) -> str:
    """JDL's closing-period date: the fiscal year end with month 13 (2026-07-31 -> 20261331)."""
    return f"{day.year:04d}13{day.day:02d}"


def _scope_ok(context) -> bool:
    from accounting_converter.adapters.output.jdl import scoped_evidence
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev

    return bool(context is not None and ev.context_is_verified(context)
                and scoped_evidence.scope_state(context) is scoped_evidence.ScopeState.IN_SCOPE)


def _signature(entry, profile, context):
    from accounting_converter.adapters.output.jdl import scoped_evidence
    from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
    from accounting_converter.domain.journal_rows import journal_physical_rows

    rows = journal_physical_rows(entry)
    if rows is None:
        return None

    def cell(line):
        if line is None:
            return "-"
        if line.tax_info is None or not line.tax_info.category:
            return "NO"
        return scoped_evidence.SEMANTIC_CELL.get(ev.target_tax_semantic(line, profile, context))

    return tuple((cell(row.debit), cell(row.credit)) for row in rows)


def problems(entry, profile, context) -> tuple[str, ...]:
    """() when this closing journal may be written as a JDL 決算整理仕訳."""
    kind = entry.metadata.get("yayoi_closing")
    if not kind:
        return ("NOT_A_CLOSING_ENTRY",)
    if kind != FINAL:
        return ("INTERIM_CLOSING_UNVERIFIED" if kind == INTERIM else "CLOSING_KIND_UNKNOWN",)
    found = []
    if not _scope_ok(context):
        found.append("CONTEXT_OUT_OF_SCOPE")
    if (entry.date.month, entry.date.day) != OBSERVED_YEAR_END:
        found.append("YEAR_END_DAY_UNVERIFIED")
    if _signature(entry, profile, context) not in IMPORTED_SHAPES:
        found.append("CLOSING_SHAPE_UNVERIFIED")
    return tuple(found)


def mark_closing(entries, profile, context) -> list:
    """Entries with each supported 本決 journal carrying its JDL closing-period date (nothing else changes)."""
    from dataclasses import replace

    result = []
    for entry in entries:
        if entry.metadata.get("yayoi_closing") and not problems(entry, profile, context):
            entry = replace(entry, metadata={**entry.metadata, JDL_DATE_KEY: jdl_closing_date(entry.date),
                                             EVIDENCE_KEY: SHAPE_EVIDENCE[_signature(entry, profile, context)]})
        result.append(entry)
    return result


def is_marked(entry) -> bool:
    return (entry.metadata.get(EVIDENCE_KEY) in set(SHAPE_EVIDENCE.values())
            and entry.metadata.get(JDL_DATE_KEY) == jdl_closing_date(entry.date)
            and entry.metadata.get("yayoi_closing") == FINAL)


def output_date(entry, context) -> str | None:
    """The JDL date text the output stage may write for this entry (None = an ordinary date)."""
    if entry.metadata.get(JDL_DATE_KEY) is None:
        return None
    if not is_marked(entry) or not _scope_ok(context) or (entry.date.month, entry.date.day) != OBSERVED_YEAR_END:
        raise ValueError("closing-period date without a valid closing mark")
    return entry.metadata[JDL_DATE_KEY]


def audit_record(entry, profile, context) -> dict | None:
    if not entry.metadata.get("yayoi_closing") or problems(entry, profile, context):
        return None
    return {
        "yayoi_closing": entry.metadata["yayoi_closing"],
        "source_date": entry.date.isoformat(),
        "jdl_date": jdl_closing_date(entry.date),
        "jdl_representation": "決算整理仕訳（JDLの13月。決算整理を含むで取込・出力）",
        "evidence_id": SHAPE_EVIDENCE[_signature(entry, profile, context)],
    }

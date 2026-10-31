"""Formal JDL output per JDL fiscal year, from one MF CSV and a saved CompanySetting.

JDL data is kept per fiscal year, so a source that crosses the fiscal year end
is converted into one formal file per year. Whole journals are assigned by
date; no journal is split. Each file is produced by the normal
MoneyForwardConversionWorkflow (READY-only, atomic, no overwrite) and is then
checked: journal and row counts, debit = credit, CP932, no BOM, CRLF only,
30 columns, and strict re-parse. The saved CompanySetting is read, not changed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
from datetime import date
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MoneyForwardInputAdapter
from accounting_converter.application.moneyforward_conversion_workflow import MoneyForwardConversionWorkflow
from accounting_converter.application.moneyforward_roundtrip import MoneyForwardJdlRoundTripComparator
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools.mf_formal_readiness import _input_profile, _subset_csv


def fiscal_year_end(day: date, month: int, last_day: int) -> date:
    end = date(day.year, month, last_day)
    return end if day <= end else date(day.year + 1, month, last_day)


def generate(source: Path, store: Path, company_id: str, output_dir: Path, *, fy_end_month: int, fy_end_day: int) -> dict:
    profiles = ConversionProfileStore(store / "profiles")
    companies = CompanySettingStore(store / "companies", profiles)
    resolved = companies.resolve(company_id)
    if not resolved.available:
        raise ValueError("CompanySetting is not available")
    entries = tuple(MoneyForwardInputAdapter().read(source, _input_profile()))
    periods: dict[date, list] = {}
    for entry in entries:
        periods.setdefault(fiscal_year_end(entry.date, fy_end_month, fy_end_day), []).append(entry)
    results = []
    for end, period_entries in sorted(periods.items()):
        rows = {n for e in period_entries for n in e.metadata.get("physical_row_numbers", ())}
        output = output_dir / f"mf_formal_jdl_FY{end:%Y-%m}.csv"
        with tempfile.TemporaryDirectory() as directory:
            subset = Path(directory) / source.name
            subset.write_bytes(_subset_csv(source, rows))
            workflow = MoneyForwardConversionWorkflow()
            prepared = workflow.prepare(
                input_path=subset, output_path=output, profile=resolved.profile,
                context=resolved.context, company_setting_validated=resolved.available,
            )
            result = workflow.execute(prepared)
        item = {
            "fiscal_year_end": end.isoformat(),
            "period": [min(e.date for e in period_entries).isoformat(), max(e.date for e in period_entries).isoformat()],
            "source_journals": len(period_entries),
            "source_physical_rows": len(rows),
            "readiness": prepared.summary.readiness.value,
            "blocking_reasons": list(prepared.summary.blocking_reasons),
            "status": result.status.value if result else None,
        }
        if output.exists():
            item.update(_verify(output, len(period_entries)))
            item["output"] = str(output)
        results.append(item)
    return {"source_journals": len(entries), "periods": results}


def _verify(path: Path, expected_journals: int) -> dict:
    raw = path.read_bytes()
    text = raw.decode("cp932", errors="strict")
    rows = [row for row in csv.reader(io.StringIO(text, newline=""))]
    body = rows[1:]
    report = MoneyForwardJdlRoundTripComparator().compare(path, path)
    debit = sum(int(row[11] or 0) for row in body)
    credit = sum(int(row[21] or 0) for row in body)
    checks = {
        "journals": report.candidate_journal_count,
        "physical_rows": report.candidate_row_count,
        "journals_match_source": report.candidate_journal_count == expected_journals,
        "debit_total": debit,
        "credit_total": credit,
        "balanced": debit == credit,
        "cp932": True,
        "bom": raw.startswith(b"\xef\xbb\xbf"),
        "crlf_only": raw.count(b"\r\n") == raw.count(b"\n"),
        "all_30_columns": all(len(row) == 30 for row in rows),
        "strict_reparse": report.passed,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    checks["ok"] = bool(
        checks["journals_match_source"] and checks["balanced"] and not checks["bom"]
        and checks["crlf_only"] and checks["all_30_columns"] and checks["strict_reparse"]
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fiscal-year-end", default="05-31", help="MM-DD of the JDL company's fiscal year end")
    args = parser.parse_args()
    month, day = (int(part) for part in args.fiscal_year_end.split("-"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps(
        generate(args.source, args.company_store, args.company_id, args.output_dir, fy_end_month=month, fy_end_day=day),
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

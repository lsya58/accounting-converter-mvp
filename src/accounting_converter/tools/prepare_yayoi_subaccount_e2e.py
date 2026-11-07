"""E2E Probe for JDL subaccounts that READY journals use but no real JDL round trip covers yet.

For each (JDL parent, subaccount) given, the most frequent READY shape of the company's journals that write it on
the debit side and on the credit side is taken as a template (accounts, subaccounts, Yayoi tax identities, rows).
Only amounts, date, voucher numbers and descriptions are replaced by synthetic values, and the file is written as
a Yayoi 仕訳日記帳（汎用形式）. The app then converts it through the normal formal path (prepare / execute) with the
saved setting as is (a COPY of the store; no approval is added or changed). Output, expected cells and the
commands for the check after the real JDL Import / re-export are written next to it.

NOT_FOR_PRODUCTION: synthetic amounts and descriptions, but real account / subaccount names of the company, so
everything is written under data/private.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import (
    HEADER,
    YAYOI_INVOICE_CLASS_KEY,
    YAYOI_PURCHASE_CREDIT_KEY,
    YAYOI_TAX_CALCULATION_KEY,
)
from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal import Side
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools.generate_yayoi_split_probes import _cell

# Synthetic amount per tax cell: (amount, explicit tax) with no fraction for any rounding.
SYNTHETIC = {"S10": (Decimal(11000), Decimal(1000)), "P10": (Decimal(3300), Decimal(300)),
             "R8": (Decimal(1080), Decimal(80)), "NO": (Decimal(5000), None), "NP": (Decimal(4000), None),
             "NS": (Decimal(4000), None), "XS": (Decimal(7000), None)}


def _reiwa(day: str) -> str:
    return f"令和{int(day[:4]) - 2018:02d}年{day[4:6]}月{day[6:]}日"


def _code(profile, account):
    mapping = profile.account_mappings.get(account)
    return mapping.metadata.get("target_code") if mapping else None


def _sub_code(profile, account, sub):
    for key, value in profile.subaccount_context_mappings.items():
        if key.parent_account == account and key.source_value == sub:
            return value.metadata.get("target_code")
    return None


def templates(entries, assessment, profile, targets: set[tuple[str, str]]) -> list:
    """Per (target, side): the first journal of the most frequent READY shape that uses the target there."""
    shapes: dict[tuple, Counter] = {}
    first: dict[tuple, object] = {}
    for entry in entries:
        if assessment.journal_blockers.get(entry.id):
            continue
        debits = [l for l in entry.lines if l.side is Side.DEBIT]
        credits = [l for l in entry.lines if l.side is Side.CREDIT]
        if not (len(debits) == 1 or len(credits) == 1):
            continue  # synthetic amounts must balance by construction: one side has a single line
        rows = journal_physical_rows(entry)
        if rows is None or len(rows) > 4:
            continue
        for line in entry.lines:
            target = (_code(profile, line.account), _sub_code(profile, line.account, line.sub_account))
            if target not in targets:
                continue
            shape = (scoped.layout_of(rows), tuple(sorted(
                f"{l.side.value[0]}{_code(profile, l.account)}:{_cell(l)}" for l in entry.lines)))
            key = (target, line.side.value)
            shapes.setdefault(key, Counter())[shape] += 1
            first.setdefault((key, shape), entry)
    chosen = []
    for key in sorted(shapes):
        shape, count = shapes[key].most_common(1)[0]
        chosen.append((key, shape, count, first[(key, shape)]))
    return chosen


def synthetic_rows(entry, case_id: str, day: str, voucher: int) -> list[list[str]]:
    sides = {side: [l for l in entry.lines if l.side is side] for side in (Side.DEBIT, Side.CREDIT)}
    # The balancing line: the untaxed line of a side that has only one line.
    candidates = [side for side, lines in sides.items() if len(lines) == 1 and _cell(lines[0]) == "NO"]
    if not candidates:
        raise ValueError(f"{case_id}: no single untaxed line to balance the synthetic amounts")
    single = candidates[0]
    amounts = {}
    for line in entry.lines:
        if line.side is not single:
            amount, tax = SYNTHETIC[_cell(line)]
            amounts[id(line)] = (amount, tax if (line.tax_info and line.tax_info.tax_amount is not None) else None)
    anchor = next(l for l in entry.lines if l.side is single)
    cell = _cell(anchor)
    if cell not in {"NO"}:
        raise ValueError(f"{case_id}: the single line carries tax; not a supported template")
    amounts[id(anchor)] = (sum(a for a, _ in amounts.values()), None)
    out = []
    for number, row in enumerate(journal_physical_rows(entry), start=1):
        record = dict.fromkeys(HEADER, "")
        record.update({"[表題行]": "[明細行]", "日付": _reiwa(day), "伝票No.": str(voucher), "調整": "NO",
                       "タイプ": "[振伝]", "摘要": f"{case_id}-R{number}", "作業日付": _reiwa(day), "仕訳番号": ""})
        for prefix, line in (("借方", row.debit), ("貸方", row.credit)):
            if line is None:
                record[f"{prefix}税区分"] = "対象外"
                continue
            amount, tax = amounts[id(line)]
            info = line.tax_info
            meta = info.metadata if info else {}
            record.update({f"{prefix}勘定科目": line.account, f"{prefix}補助科目": line.sub_account or "",
                           f"{prefix}税区分": (info.category or "").split("｜")[0] if info else "対象外",
                           f"{prefix}税計算区分": meta.get(YAYOI_TAX_CALCULATION_KEY, "") if tax is not None else "",
                           f"{prefix}金額": str(amount), f"{prefix}税額": "" if tax is None else str(tax)})
            if meta.get(YAYOI_INVOICE_CLASS_KEY) or meta.get(YAYOI_PURCHASE_CREDIT_KEY):
                record["請求書区分"] = meta.get(YAYOI_INVOICE_CLASS_KEY, "")
                record["仕入税額控除"] = meta.get(YAYOI_PURCHASE_CREDIT_KEY, "")
        out.append([record[name] for name in HEADER])
    return out


def render(rows: list[list[str]], day: str) -> bytes:
    month_start, month_end = f"{day[:6]}01", f"{day[:6]}28"
    records = [["帳票名", "仕訳日記帳"], ["書式名", "汎用形式"], ["事業所名", "E2E合成"],
               ["処理日時", _reiwa(day), "09:00:00"], ["検索条件", ""],
               ["集計期間", _reiwa(month_start), _reiwa(month_end), "決算仕訳を含む"], ["当日仕訳", "NO"], list(HEADER)]
    records.extend(rows)
    totals = dict.fromkeys(HEADER, "")
    totals["[表題行]"] = "[日次合計行]"
    for name in ("借方金額", "借方税額", "貸方金額", "貸方税額"):
        totals[name] = str(sum(int(r[HEADER.index(name)] or 0) for r in rows))
    records.append([totals[name] for name in HEADER])
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(records)
    return buffer.getvalue().encode("cp932", errors="strict")


def prepare(source: Path, company_store: Path, company_id: str, targets: set[tuple[str, str]], day: str,
            output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise SystemExit("write under data/private only (real account and subaccount names)")
    if "AppData" in company_store.resolve().as_posix():
        raise SystemExit("give a COPY of the settings store, never the real AppData")
    entries = detect_format(source).diagnose(source).entries
    if any(entry.date.strftime("%Y%m%d") == day for entry in entries):
        raise SystemExit("the day has source journals; choose another")
    output_dir.mkdir(parents=True, exist_ok=True)
    store = output_dir / "store_copy"
    if store.exists():
        raise SystemExit(f"{store} exists; nothing is overwritten")
    shutil.copytree(company_store, store)  # the check later reads the same settings the CSV was made with
    profiles = ConversionProfileStore(store / "profiles")
    resolved = CompanySettingStore(store / "companies", profiles).resolve(company_id)
    workflow = YayoiJournalReportJdlWorkflow()
    assessment = workflow.assess(source, resolved.profile, resolved.context)
    chosen = templates(entries, assessment, resolved.profile, targets)
    rows, cases = [], []
    for number, (key, shape, count, entry) in enumerate(chosen, start=1):
        case_id = f"E2E-SUB{number}"
        part = synthetic_rows(entry, case_id, day, number)
        rows.extend(part)
        cases.append({"case": case_id, "jdl_target": "-".join(key[0]), "side": key[1], "layout": shape[0],
                      "cells": list(shape[1]), "ready_journals_with_this_shape": count, "physical_rows": len(part)})
    synthetic = output_dir / f"YAYOI_SUB_E2E_{day}_NOT_FOR_PRODUCTION_source.txt"
    synthetic.write_bytes(render(rows, day))
    # Not named NOT_FOR_PRODUCTION on purpose: the formal path then writes and verifies the audit file too
    # (parent-only subaccounts in the templates), exactly as for a real formal output.
    output = output_dir / f"YAYOI_SUB_E2E_{day}_synthetic_formal.csv"
    prepared = workflow.prepare(input_path=synthetic, output_path=output, profile=resolved.profile,
                                context=resolved.context, company_setting_validated=resolved.available)
    if prepared.summary.readiness is not FirstReleaseReadiness.READY:
        raise SystemExit(f"the app does not make the synthetic file READY: {prepared.summary.blocking_reasons}")
    result = workflow.execute(prepared)
    if result is None or result.status.value != "SUCCESS":
        raise SystemExit("conversion failed")
    data = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
    expected = [{"case": r[23].rsplit("-R", 1)[0], "flag": r[0], "date": r[2],
                 "debit": [r[3], r[6], r[7], r[8], r[9], r[10], r[11], r[12]],
                 "credit": [r[13], r[16], r[17], r[18], r[19], r[20], r[21], r[22]], "description": r[23]}
                for r in data]
    manifest = {
        "NOT_FOR_PRODUCTION": True, "purpose": "JDL subaccounts used by READY journals without a real round trip",
        "targets": sorted("-".join(t) for t in targets), "probe_date": day, "company_setting_id": company_id,
        "source_sha256": hashlib.sha256(synthetic.read_bytes()).hexdigest(),
        "jdl_csv_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "journals": len(cases), "rows": len(data), "cases": cases,
        "expected_jdl_rows": expected,
        "expected_after_reexport": ("同じ行数・同じ科目/補助コード・金額・税・摘要。既知の正規化（伝番の採番、税額・部門の空欄→0、"
                                    "科目・補助の名称をJDLマスターから付け直す）以外の差異はFAIL"),
        "check": (f"PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_roundtrip_check --source {synthetic} "
                  f"--company-store {store} --company-id {company_id} --candidate {output} "
                  f"--reexport {output_dir / f'JDL_再Export_{day}.csv'}"),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="the company's Yayoi file (templates only)")
    parser.add_argument("--company-store", type=Path, required=True, help="a COPY of the settings store")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--target", action="append", required=True, help="JDL parent-subaccount, e.g. 1551-0169")
    parser.add_argument("--probe-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    targets = {tuple(t.split("-", 1)) for t in args.target}
    manifest = prepare(args.source, args.company_store, args.company_id, targets, args.probe_date, args.output_dir)
    print(json.dumps({k: manifest[k] for k in ("journals", "rows", "cases", "jdl_csv_sha256", "check")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

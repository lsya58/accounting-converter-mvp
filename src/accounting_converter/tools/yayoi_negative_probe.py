"""Round 6b: the smallest JDL Probe for journal 4012 (negative debit lines in a >64-row journal). Fully synthetic.

Why: 4012 (借方72・貸方1, three 借方 lines with a negative amount and a negative 内税 tax) is blocked at 64 rows.
Two things have no JDL Evidence (verified by search of the registry, the preflight and every private JDL export):
  1. whether JDL's CSV Import accepts a NEGATIVE 借方 amount with a NEGATIVE explicit 消費税 and gives it back
     unchanged (no JDL export seen so far contains a negative amount; the output preflight refuses them);
  2. the 64-row voucher layout C1D36 (counterpart on row 1 + 36 debit rows) with the part's real tax-cell pattern.
This tool writes the Probe for exactly those, built from 4012's own two split parts (same layout, same tax-cell
sequence, same positions of the negative lines) with synthetic amounts (±1,485; tax ±135).

  generate  --source --company-store --company-id --probe-date --output-dir
  judge     --probe --reexport : strict column comparison (the shared checker cannot read negative amounts).

Nothing here registers Evidence, changes readiness, the split rule or any saved setting. A PASS would prove the JDL
representation only; 4012 stays blocked until the Evidence is registered by a reviewed code change AND the Human
records the (separate) tax-accountant approval for splitting a journal with negative lines.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.application import voucher_split
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import generate_yayoi_gap_probes as gap
from accounting_converter.tools import yayoi_row64_probe as row64
from accounting_converter.tools.generate_yayoi_split_probes import signature
from accounting_converter.tools.yayoi_probe_check import manifest_path_for

DEBIT_AMOUNT, DEBIT_TAX, CREDIT_AMOUNT, CREDIT_TAX = 11, 12, 21, 22
_ROW_SUFFIX = re.compile(r"-R(\d+)$")
NONE, NO = "-", "NO"
UNIT = 1485
TAX_UNIT = 135


def positive_copy(entry):
    """The journal with absolute amounts: only used to ask the split rule for the part boundaries."""
    return replace(entry, lines=[replace(line, amount=abs(line.amount)) for line in entry.lines])


def negative_debit_ordinals(part) -> tuple[int, ...]:
    """0-based positions of the negative lines among the part's debit lines (physical order)."""
    debits = [line for line in part.lines if line.side.value == "DEBIT"]
    return tuple(i for i, line in enumerate(debits) if line.amount < 0)


def negate_voucher(rows: list[list[str]], negative: tuple[int, ...], overrides: dict[int, int] | None = None) -> list[list[str]]:
    """Make the chosen debit lines negative (amount and explicit tax) and set the single credit to the signed sum.

    `rows` are the CSV rows of ONE voucher (one credit line). A debit with an empty tax keeps an empty tax.
    """
    overrides = overrides or {}
    rows = [list(r) for r in rows]
    debit_rows = [r for r in rows if r[DEBIT_AMOUNT] not in {"", "0"}]
    total = 0
    for ordinal, row in enumerate(debit_rows):
        amount = overrides.get(ordinal, int(row[DEBIT_AMOUNT]))
        if ordinal in negative:
            amount = -abs(amount)
        had_tax = row[DEBIT_TAX] != ""
        row[DEBIT_AMOUNT] = str(amount)
        if had_tax:
            row[DEBIT_TAX] = str(int(Decimal(amount) / 11))
        total += amount
    credit_rows = [r for r in rows if r[CREDIT_AMOUNT] not in {"", "0"}]
    if len(credit_rows) != 1:
        raise ValueError("a voucher with exactly one credit line is expected")
    credit_rows[0][CREDIT_AMOUNT] = str(total)
    if credit_rows[0][CREDIT_TAX] not in {"", "0"}:
        raise ValueError("the counterpart must carry no tax")
    return rows


def generate(source: Path, company_store: Path, company_id: str, probe_date: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise gen.CampaignError("probe files contain the company's JDL master names; write them under data/private only")
    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    entries, profile, context = row64.load(source, company_store, company_id)
    if any(entry.date == day for entry in entries):
        raise gen.CampaignError("the probe date has source journals; choose a day without any")
    if probe_date in row64.USED_PROBE_DAYS:
        raise gen.CampaignError("this day was used by an earlier probe; choose another")
    target = next(e for e in entries if e.id.endswith(":4012"))
    plan = voucher_split.plan_split(positive_copy(target), row64.TARGET_LIMIT)
    if plan is None:
        raise gen.CampaignError("4012 no longer fits the split rule when signs are ignored")
    parts = voucher_split.split_entry(target, plan)
    accounts, names = gen._accounts(context)
    synthetic = gap.synthetic_profile(context)
    cases, negatives = [gap.control_case("CTL-NEG", accounts)], {}
    mini = ((NONE, NO), ("P10", row64.NONE), ("P10", row64.NONE))
    cases.append(gap.structural_case("NEG-MIN", mini, accounts, "G-NEG", "C1D2: 借方に負の明細（金額・内税とも負）が往復するか", 1))
    negatives["NEG-MIN"] = ((1,), {0: 2 * UNIT})
    for number, part in enumerate(parts, start=1):
        rows = signature(part)
        if rows is None:
            raise gen.CampaignError(f"part {number}: tax cells unresolved")
        case = gap.structural_case(f"NEG-4012-P{number}", rows[0], accounts, "G-NEG",
                                   f"4012の分割{number}の配置（C1D36・税セル列・負の位置を再現）", 1)
        cases.append(case)
        negatives[case.case_id] = (negative_debit_ordinals(part), {})
    output_dir.mkdir(parents=True, exist_ok=True)
    common = row64._common(company_id, context, probe_date)
    common["round"] = "6b: negative debit lines (journal 4012)"
    common["registry_note"] = ("PASS proves the JDL representation of negative 借方 lines and the C1D36 layout only. "
                               "4012 stays blocked until reviewed registration AND a Human-recorded approval.")
    manifest = gap.write_file("NEG4012", "借方の負の明細と分割後の配置（4012）", cases, day, probe_date, names, synthetic,
                              context, company_id, output_dir, common, check_lengths=True, row_limit=row64.TARGET_LIMIT)
    path = output_dir / manifest["probe_file"]
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode("cp932"), newline="")))
    header, body = rows[0], rows[1:]
    out, cursor = [header], 0
    for case_manifest in manifest["cases"]:
        chunk = body[cursor: cursor + case_manifest["physical_rows"]]
        cursor += case_manifest["physical_rows"]
        if case_manifest["case"] in negatives:
            chunk = negate_voucher(chunk, *negatives[case_manifest["case"]])
        out.extend(chunk)
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(out)
    payload = buffer.getvalue().encode("cp932", errors="strict")
    path.write_bytes(payload)
    manifest["probe_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["negative_lines"] = {k: list(v[0]) for k, v in negatives.items()}
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def _case_rows(path: Path) -> dict[str, list[list[str]]]:
    """Data rows of a JDL CSV / Export grouped by the case tag in 摘要 (`CASE-Rn`). Comment lines are skipped."""
    grouped: dict[str, list[list[str]]] = {}
    for row in csv.reader(io.StringIO(path.read_bytes().decode("cp932"), newline="")):
        if not row or row[0].startswith("//") or len(row) < 24 or not row[23].startswith(("CTL-", "NEG-")):
            continue
        grouped.setdefault(_ROW_SUFFIX.sub("", row[23]), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: int(_ROW_SUFFIX.search(r[23]).group(1)) if _ROW_SUFFIX.search(r[23]) else 0)
    return grouped


def _norm(value: str) -> str:
    return "" if value in {"", "0"} else value


def judge(probe: Path, reexport: Path, manifest: dict) -> dict:
    """Strict column comparison (columns 日付..摘要; 伝番 and the flag column are JDL-assigned) of the re-export
    against the probe, case by case. Empty and 0 are equal (JDL writes 0 for an absent side). Signs are compared."""
    wanted, got = _case_rows(probe), _case_rows(reexport)
    cases, extra = {}, sorted(set(got) - set(wanted))
    for case in manifest["cases"]:
        name = case["case"]
        left, right = wanted[name], got.get(name)
        if right is None:
            cases[name] = {"verdict": "MISSING"}
            continue
        if len(left) != len(right):
            cases[name] = {"verdict": "FAIL", "why": f"rows {len(left)} != {len(right)}"}
            continue
        diffs = [(i + 1, column) for i, (a, b) in enumerate(zip(left, right))
                 for column in range(2, 24) if _norm(a[column]) != _norm(b[column])]
        cases[name] = {"verdict": "PASS" if not diffs else "FAIL", "differences": diffs[:20]}
    verdict = {k: v["verdict"] for k, v in cases.items()}
    negative_ok = verdict.get("NEG-MIN") == "PASS"
    return {
        "cases": cases, "extra_unexplained_cases": extra,
        "control_pass": verdict.get("CTL-NEG") == "PASS",
        "result": ("NEGATIVE_DEBIT_PRESERVED" if negative_ok and verdict.get("CTL-NEG") == "PASS" and not extra
                   else "NOT_PROVEN"),
        "layout_c1d36_parts_pass": all(verdict.get(f"NEG-4012-P{n}") == "PASS" for n in (1, 2)),
    }


def analyze_error_log(path: Path) -> dict:
    """Per case: how many rows carry which JDL message. In the JDL log a message follows the row it is about.

    Facts only: nothing is inferred about which message JDL would show first when several apply.
    """
    rows = path.read_bytes().decode("cp932").replace("\r", "").split("\n")
    per_row: list[tuple[str, list[str]]] = []
    for line in rows:
        if line.startswith("//  "):
            if per_row:
                per_row[-1][1].append(line[4:].strip())
        elif line and not line.startswith("//") and line.count(",") >= 23:
            per_row.append((line.split(",")[23], []))
    summary: dict[str, dict] = {}
    for tag, messages in per_row:
        case = _ROW_SUFFIX.sub("", tag)
        entry = summary.setdefault(case, {"rows": 0, "messages": {}})
        entry["rows"] += 1
        key = " / ".join(messages) or "(no message)"
        entry["messages"][key] = entry["messages"].get(key, 0) + 1
    return {"rows_in_log": len(per_row), "cases": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--source", type=Path, required=True)
    g.add_argument("--company-store", type=Path, required=True)
    g.add_argument("--company-id", required=True)
    g.add_argument("--probe-date", required=True)
    g.add_argument("--output-dir", type=Path, required=True)
    j = sub.add_parser("judge")
    j.add_argument("--probe", type=Path, required=True)
    j.add_argument("--reexport", type=Path, required=True)
    e = sub.add_parser("log", help="summarise a JDL import error log per case")
    e.add_argument("--error-log", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "log":
        print(json.dumps(analyze_error_log(args.error_log), ensure_ascii=False, indent=1))
        return 0
    if args.command == "judge":
        manifest = json.loads(manifest_path_for(args.probe).read_text(encoding="utf-8"))
        print(json.dumps(judge(args.probe, args.reexport, manifest), ensure_ascii=False, indent=1))
        return 0
    manifest = generate(args.source, args.company_store, args.company_id, args.probe_date, args.output_dir)
    print(json.dumps({"file": manifest["probe_file"], "sha256": manifest["probe_sha256"][:16],
                      "journals": manifest["expected_logical_journals"], "rows": manifest["expected_physical_rows"],
                      "negative_lines": manifest["negative_lines"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

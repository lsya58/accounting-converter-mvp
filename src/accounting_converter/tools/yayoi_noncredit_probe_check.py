"""Judge the 控除不可 Probes (`generate_yayoi_noncredit_probes`): CSV round trip AND JDL's tax summary.

A CSV round trip only shows that JDL kept the cells. Whether a writing means "taxable purchase with NO input tax
credit" (Yayoi 控除不可) is read from JDL's own tax summary, before and after each file is imported.

  sheet   write the readings template (data/private only): one row per step (before / after each file) and tax
          summary field, plus one sign-off row per candidate for the tax accountant.
  judge   --round-report (JSON of `yayoi_gap_probe_check check --out`) + the filled readings sheet ->
          one result per case:
            IMPORT_REJECTED                    not re-exported
            IMPORTED_REEXPORT_CHANGED          imported, a cell changed (raw differences listed)
            TAX_RECOMPUTED_BY_JDL              imported, but JDL replaced the written tax 0 with the computed tax
            CSV_PASS_MEANING_UNVERIFIED        round trip PASS, no usable tax summary reading
            TAX_SUMMARY_SHOWS_CREDIT           the amount entered 課税仕入 or produced tax: NOT 控除不可
            TAX_SUMMARY_CONSISTENT_PENDING_HUMAN  no 課税仕入 amount / tax / credit added; the accountant has not
                                               signed off that it is equivalent for the tax return
            EQUIVALENCE_CONFIRMED              the above AND the accountant's sign-off (CANDIDATE kind only)
            NOT_ADOPTED_COMPARISON             comparison / negative probe: never adopted, whatever it shows
            UNDETERMINED                       the control does not add up, or the step cannot be attributed
          --after-restore: a re-export of the probe day taken after restoring the backup must have 0 journals.
Nothing here registers Evidence or changes the converter; 控除不可 stays blocked until a reviewed change.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path

from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows
from accounting_converter.tools.yayoi_probe_check import manifest_path_for

HEADER = ("種類", "段階", "キー", "画面で探す欄", "表示（税込/税抜）", "【記入】値", "メモ")
BEFORE = "before"
AMOUNT_FIELDS = {"PUR10_AMOUNT": "PUR10_TAX", "PUR8_AMOUNT": "PUR8_TAX"}
RATE = {"PUR10_AMOUNT": 10, "PUR8_AMOUNT": 8}


def manifests(probe_dir: Path) -> list[dict]:
    found = []
    for path in sorted(probe_dir.glob("YAYOI_GAP_NONCREDIT_*_NOT_FOR_PRODUCTION.csv")):
        found.append(json.loads(manifest_path_for(path).read_text(encoding="utf-8")))
    order = {"NONCREDIT_A": 0, "NONCREDIT_B10": 1, "NONCREDIT_B8": 2, "NONCREDIT_C10": 3, "NONCREDIT_C8": 4}
    return sorted(found, key=lambda m: order.get(m["batch"], 99))


def _private(path: Path) -> None:
    if "data/private" not in path.resolve().as_posix():
        raise SystemExit("write it under data/private only")


COMBINED = "after_all"
# Read from the same report when present. 課税仕入税額等合計 is the base of every credit method, so it shows
# whether a candidate added creditable tax even when 課税売上割合 is 0% (then the 一括比例 credit is 0 whatever
# was imported and cannot discriminate). JDL's 消費税集計表（原則課税） has no 非課税仕入 field.
OPTIONAL_FIELDS = {"PUR_TAX_TOTAL": "課税仕入税額等合計（全額控除方式の控除対象仕入税額等と同じ値）"}
# Trial balance, reference only (税抜振替 may not have run, so 仮払消費税 can stay unchanged).
TRIAL_BALANCE_FIELDS = {
    "TB_8471": "合計残高試算表 8471 旅費交通費 の残高（参考）",
    "TB_KARIBARAI": "合計残高試算表 仮払消費税 の残高（参考。税抜振替を実行していなければ動かないことがある）",
}


def write_sheet(probe_dir: Path, output: Path, *, combined: bool = False) -> int:
    """combined: the files are already in JDL; read once now (after_all) and once after restoring (before)."""
    _private(output)
    found = manifests(probe_dir)
    fields = dict(found[0]["summary_fields"])
    fields.update(OPTIONAL_FIELDS)
    if combined:
        fields.update(TRIAL_BALANCE_FIELDS)
    steps = [BEFORE, COMBINED] if combined else [BEFORE] + [f"after_{m['batch']}" for m in found]
    buffer = io.StringIO()
    out = csv.writer(buffer, lineterminator="\r\n")
    out.writerow(HEADER)
    out.writerow(("RATIO", BEFORE, "TAXABLE_SALES_RATIO", "課税売上割合（取込前。Probeに売上は無いので変わらない）", "%", "", ""))
    for step in steps:
        for key, label in fields.items():
            shown = "税込" if key.endswith("_AMOUNT") else "残高" if key.startswith("TB_") else ""
            out.writerow(("READING", step, key, label, shown, "", ""))
    for manifest in found:
        for case in manifest["cases"]:
            if case["candidate_kind"] == "CANDIDATE":
                out.writerow(("SIGNOFF", manifest["batch"], case["case"],
                              "税理士: この書き方は弥生の控除不可と申告上同等か（済 / 空欄）", "", "", ""))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("﻿" + buffer.getvalue(), encoding="utf-8")
    print(json.dumps({"rows": buffer.getvalue().count("\r\n") - 1, "steps": steps}, ensure_ascii=False))
    return 0


def read_sheet(path: Path) -> tuple[dict, dict, Decimal | None, dict]:
    """(readings[step][key] = Decimal, shown[key] = 税込/税抜, ratio, signoff[case] = bool)."""
    text = path.read_bytes().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(rows[0]) != HEADER:
        raise SystemExit("the readings sheet header differs")
    readings: dict[str, dict[str, Decimal]] = {}
    shown: dict[str, str] = {}
    signoff: dict[str, bool] = {}
    ratio = None
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        kind, step, key, _label, display, value = row[:6]
        value = value.replace(",", "").strip()
        if kind == "SIGNOFF":
            signoff[key] = value == "済"
            continue
        if not value:
            continue
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise SystemExit(f"not a number: {step} {key}")
        if kind == "RATIO":
            ratio = number / 100
        elif kind == "READING":
            readings.setdefault(step, {})[key] = number
            if display:
                shown[key] = display
    return readings, shown, ratio, signoff


def _amount_shown(amount: int, rate: int, tax: int | None, display: str) -> set[Decimal]:
    """What an included line could add to an amount field: gross, or net of the tax JDL kept / recomputed."""
    if display != "税抜":
        return {Decimal(amount)}
    recomputed = Decimal(amount) * rate / (100 + rate)
    values = {Decimal(amount) - recomputed.quantize(Decimal(1))}
    if tax is not None:
        values.add(Decimal(amount) - tax)
    return values


def judge_step(manifest: dict, before: dict, after: dict, shown: dict, ratio: Decimal | None) -> dict:
    """Which candidates of one file entered 課税仕入 (amount or tax) or the credit. Returns per-case findings."""
    delta = {key: after[key] - before[key] for key in after if key in before}
    controls = [c for c in manifest["cases"] if c["candidate_kind"] == "CONTROL"]
    others = [c for c in manifest["cases"] if c["candidate_kind"] != "CONTROL"]
    expected_control = {}
    for case in controls:
        for key, value in case["summary_delta_if_noncredit"].items():
            if key.endswith("_AMOUNT") and shown.get(key) == "税抜":
                value -= case["summary_delta_if_noncredit"][AMOUNT_FIELDS[key]]
            expected_control[key] = expected_control.get(key, 0) + value
    result = {"delta": {k: str(v) for k, v in delta.items()}, "cases": {}}
    missing = [k for k in (*AMOUNT_FIELDS, *AMOUNT_FIELDS.values()) if k not in delta]
    if missing:
        result["undetermined"] = f"readings missing: {missing}"
        return result
    residual = {key: delta[key] - expected_control.get(key, 0) for key in (*AMOUNT_FIELDS, *AMOUNT_FIELDS.values())}
    included: set[str] = set()
    for amount_key, tax_key in AMOUNT_FIELDS.items():
        rate = RATE[amount_key]
        pool = [c for c in others if _rate_of(c) == rate]
        target = residual[amount_key]
        if target == 0:
            continue
        explained = None
        for size in range(1, len(pool) + 1):
            for subset in combinations(pool, size):
                options = [set()]
                for c in subset:
                    written_tax = c["written_debit_tax_columns"].get("消費税")
                    tax = int(written_tax) if written_tax not in ("", None) else None
                    options = [o | {v} for o in options for v in _amount_shown(c["amount"], rate, tax, shown.get(amount_key, "税込"))]
                if any(sum(o) == target for o in options):
                    explained = subset
                    break
            if explained:
                break
        if explained is None:
            result["undetermined"] = f"{amount_key}: change {target} not explained by the control and any candidate"
            return result
        included |= {c["case"] for c in explained}
    for tax_key in AMOUNT_FIELDS.values():
        if residual[tax_key] != 0:
            rate = 10 if tax_key == "PUR10_TAX" else 8
            pool = [c["case"] for c in others if _rate_of(c) == rate]
            if len(pool) == 1:
                included.add(pool[0])
            elif not (included & set(pool)):
                result["undetermined"] = f"{tax_key}: tax {residual[tax_key]} added but not attributable"
                return result
    credit_ok = None
    control_tax = sum(expected_control.get(k, 0) for k in AMOUNT_FIELDS.values())
    if "CREDITABLE_TAX" in delta:
        if ratio is not None:
            credit_ok = abs(delta["CREDITABLE_TAX"] - Decimal(control_tax) * ratio) <= 1
        else:
            credit_ok = delta["CREDITABLE_TAX"] <= control_tax
    # With a 0% ratio the 一括比例 credit is 0 for any import: consistent, but it proves nothing.
    result["credit_check_discriminating"] = bool(credit_ok is not None and ratio is not None and ratio != 0)
    tax_total_ok = None
    if "PUR_TAX_TOTAL" in delta:
        tax_total_ok = delta["PUR_TAX_TOTAL"] == control_tax
        result["tax_total_delta_expected_from_controls"] = str(control_tax)
        if not tax_total_ok and not included:
            result["undetermined"] = "課税仕入税額等合計 changed more than the controls explain"
            return result
    for case in others:
        entered = case["case"] in included
        result["cases"][case["case"]] = {
            "entered_taxable_purchase_or_tax": entered,
            "credit_consistent_with_control_only": credit_ok,
            "tax_total_consistent_with_control_only": tax_total_ok,
            "nontax_purchase_delta_of_step": str(delta.get("NONTAX_PURCHASE", "")),
        }
    if credit_ok is False and not included:
        result["undetermined"] = "控除対象仕入税額 changed more than the control explains"
    return result


def _rate_of(case: dict) -> int:
    expected = case.get("summary_delta_if_noncredit") or {}
    if any(key.startswith("PUR8") for key in expected):
        return 8
    if any(key.startswith("PUR10") for key in expected):
        return 10
    written = case["written_debit_tax_columns"]
    if isinstance(written, dict) and written.get("税区") == "軽減8%":
        return 8
    if isinstance(written, dict) and written.get("税区") == "10%":
        return 10
    return 8 if case["case"].endswith("-8") else 10


_NORMALIZED = {"貸方消費税", "借方部門コード", "貸方部門コード"}


def recomputed_tax(differences) -> tuple[str, str] | None:
    """(written, re-exported) when the only real change is a written debit tax of 0 that JDL replaced."""
    real = [d for d in differences
            if not (d["column"] in _NORMALIZED and d["expected"] in {"", "0"} and d["actual"] in {"", "0"})]
    if len(real) == 1 and real[0]["column"] == "借方消費税" and real[0]["expected"] == "0" and real[0]["actual"] not in {"", "0"}:
        return real[0]["expected"], real[0]["actual"]
    return None


def judge(probe_dir: Path, round_report: Path, readings_path: Path | None, after_restore: Path | None = None) -> dict:
    report = json.loads(round_report.read_text(encoding="utf-8"))
    readings, shown, ratio, signoff = read_sheet(readings_path) if readings_path else ({}, {}, None, {})
    found = manifests(probe_dir)
    verdicts, details, rejected_files = {}, {}, set(report.get("files_with_nothing_reexported", ()))
    for name, result in report["files"].items():
        verdicts.update(result["verdicts"])
        details.update(result.get("details") or {})
    out = {"round_valid": report.get("round_valid"), "steps": {}, "cases": {}}
    if COMBINED in readings:
        return _judge_combined(found, verdicts, details, rejected_files, readings, shown, ratio, signoff, out)
    previous = BEFORE
    for manifest in found:
        step = f"after_{manifest['batch']}"
        controls_pass = all(verdicts.get(c["case"]) == "PASS" for c in manifest["cases"] if c["candidate_kind"] == "CONTROL")
        finding = None
        if previous in readings and step in readings and controls_pass:
            finding = judge_step(manifest, readings[previous], readings[step], shown, ratio)
            out["steps"][step] = finding
        elif step in readings and not controls_pass:
            out["steps"][step] = {"undetermined": "the control of this file did not round-trip"}
        if step in readings:
            previous = step
        for case in manifest["cases"]:
            if case["candidate_kind"] == "CONTROL":
                continue
            verdict = verdicts.get(case["case"], "MISSING")
            recomputed = recomputed_tax(details.get(case["case"], {}).get("raw_differences", ()))
            if verdict == "MISSING":
                category = "IMPORT_REJECTED"
            elif verdict != "PASS" and recomputed is not None:
                category = "TAX_RECOMPUTED_BY_JDL"  # the 0 became the computed tax: an ordinary 課税仕入
            elif verdict != "PASS":
                category = "IMPORTED_REEXPORT_CHANGED"
            elif case["candidate_kind"] != "CANDIDATE" and finding is None:
                category = "NOT_ADOPTED_COMPARISON"
            elif finding is None:
                category = "CSV_PASS_MEANING_UNVERIFIED"
            elif "undetermined" in finding:
                category = "UNDETERMINED"
            elif finding["cases"][case["case"]]["entered_taxable_purchase_or_tax"]:
                category = "TAX_SUMMARY_SHOWS_CREDIT"
            elif case["candidate_kind"] != "CANDIDATE":
                category = "NOT_ADOPTED_COMPARISON"
            elif signoff.get(case["case"]):
                category = "EQUIVALENCE_CONFIRMED"
            else:
                category = "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN"
            out["cases"][case["case"]] = {"round_trip": verdict, "result": category,
                                          "written": case["written_debit_tax_columns"]}
            if recomputed is not None:
                out["cases"][case["case"]]["tax_written_then_reexported"] = recomputed
            if manifest.get("probe_file") in rejected_files:
                out["cases"][case["case"]]["whole_file_absent_including_control"] = True
    if after_restore is not None:
        probe_date = found[0]["probe_date"]
        rows = [r for r in _rows(after_restore) if len(r) > 2 and r[2] == probe_date]
        out["after_restore_journals_on_probe_day"] = len(_groups(rows)) if rows else 0
        out["after_restore_clean"] = not rows
    return out


def _judge_combined(found, verdicts, details, rejected_files, readings, shown, ratio, signoff, out) -> dict:
    """All imported files at once: before (after restoring the backup) vs now. A candidate whose tax JDL
    recomputed is an ordinary creditable 課税仕入 (re-export shows it), so it is counted like a control."""
    merged = {"cases": []}
    imported = [m for m in found if m.get("probe_file") not in rejected_files]
    expected_tb_8471 = expected_tb_tax = 0
    for manifest in imported:
        for case in manifest["cases"]:
            verdict = verdicts.get(case["case"], "MISSING")
            recomputed = recomputed_tax(details.get(case["case"], {}).get("raw_differences", ()))
            written = case["written_debit_tax_columns"]
            if case["candidate_kind"] == "CONTROL" or recomputed is not None:
                key = "PUR10" if _rate_of(case) == 10 else "PUR8"
                tax = int(recomputed[1]) if recomputed else case["summary_delta_if_noncredit"].get(f"{key}_TAX", 0)
                merged["cases"].append({**case, "candidate_kind": "CONTROL",
                                        "summary_delta_if_noncredit": {f"{key}_AMOUNT": case["amount"], f"{key}_TAX": tax}})
                expected_tb_tax += tax
                expected_tb_8471 += case["amount"] - tax
            elif verdict == "PASS":
                merged["cases"].append(case)
                expected_tb_8471 += case["amount"]
            else:
                out["undetermined"] = f"{case['case']}: {verdict} without an explanation; the combined reading cannot be attributed"
                return out
    finding = judge_step(merged, readings[BEFORE], readings[COMBINED], shown, ratio)
    out["steps"][COMBINED] = finding
    before, after = readings[BEFORE], readings[COMBINED]
    out["trial_balance_reference"] = {
        key: {"expected_change_if_noncredit": value, "observed_change": str(after[key] - before[key])}
        for key, value in (("TB_8471", expected_tb_8471), ("TB_KARIBARAI", expected_tb_tax))
        if key in after and key in before
    }
    for manifest in found:
        for case in manifest["cases"]:
            if case["candidate_kind"] == "CONTROL":
                continue
            verdict = verdicts.get(case["case"], "MISSING")
            recomputed = recomputed_tax(details.get(case["case"], {}).get("raw_differences", ()))
            if verdict == "MISSING":
                category = "IMPORT_REJECTED"
            elif recomputed is not None:
                category = "TAX_RECOMPUTED_BY_JDL"
            elif verdict != "PASS":
                category = "IMPORTED_REEXPORT_CHANGED"
            elif "undetermined" in finding:
                category = "UNDETERMINED"
            elif finding["cases"][case["case"]]["entered_taxable_purchase_or_tax"]:
                category = "TAX_SUMMARY_SHOWS_CREDIT"
            elif case["candidate_kind"] != "CANDIDATE":
                category = "NOT_ADOPTED_COMPARISON"
            elif signoff.get(case["case"]):
                category = "EQUIVALENCE_CONFIRMED"
            else:
                category = "TAX_SUMMARY_CONSISTENT_PENDING_HUMAN"
            out["cases"][case["case"]] = {"round_trip": verdict, "result": category, "written": case["written_debit_tax_columns"]}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--probe-dir", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--combined", action="store_true", help="files already imported: read now and after restoring")
    j = sub.add_parser("judge")
    j.add_argument("--probe-dir", type=Path, required=True)
    j.add_argument("--round-report", type=Path, required=True)
    j.add_argument("--readings", type=Path)
    j.add_argument("--after-restore", type=Path, help="re-export of the probe day after restoring the backup")
    args = parser.parse_args()
    if args.command == "sheet":
        return write_sheet(args.probe_dir, args.output, combined=args.combined)
    print(json.dumps(judge(args.probe_dir, args.round_report, args.readings, args.after_restore), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Can a JDL IBEX 出納帳 35.5 CSV carry a closing entry (決算整理仕訳)? Judge the hand-entered self-export probe.

The 30-column CSV has no 決算 column, but the JDL CSV input / output screens offer 「決算整理を含む / 含まない」. So the
only way to know whether, and how, the CSV distinguishes a closing entry is JDL's own export of two hand-entered
journals that differ ONLY in being a closing entry (same date, accounts, amount; 摘要 CL-NORMAL / CL-CLOSING):

  step1  --with  export with 決算整理を含む, --without  export with 決算整理を含まない (same date range)
         -> CL-CLOSING present with / absent without = JDL knows it; then every column of the two rows is compared
            (except 摘要 and 伝番). A differing column is the candidate CSV mark; identical rows = the CSV cannot
            carry it.
  step2  (only when step1 found a mark) the --with export is imported into the restored copy with 決算整理を含む,
         then exported again without closing entries: --after-reimport-without. CL-CLOSING absent there = the mark
         survives a CSV Import (a real representation); present = Import turned it into an ordinary journal.

2026-11-07 result of step1: CSV_MARK_FOUND_IMPORT_UNVERIFIED. JDL writes the closing entry with the date
YYYY13DD (month 13, e.g. 20261331) and nothing else differs.

  generate-import  app-format Probe of the company's closing-entry shapes (B1 対象外, B1 非仕入, B2, B1C2), dated
                   YYYY13DD, plus an ordinary control in its own file (a rejected closing file cannot hide it).
  judge-import     after importing both files: every closing case must re-export unchanged (strict compare,
                   known normalizations only) with 決算整理を含む and be absent without it; the control in both.
                   -> CLOSING_IMPORT_PRESERVED / CLOSING_IMPORT_REJECTED / CLOSING_IMPORTED_AS_ORDINARY / UNDETERMINED

Results: CSV_MARK_ROUNDTRIPS (column, values) / CSV_MARK_LOST_ON_IMPORT / CSV_CANNOT_CARRY_CLOSING /
JDL_DOES_NOT_SEPARATE (both exports identical) / UNDETERMINED (marker rows missing or duplicated).
Nothing here changes the converter: closing entries stay blocked until a verified representation is implemented.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows

NORMAL, CLOSING = "CL-NORMAL", "CL-CLOSING"
IGNORED = {1, 23}  # 伝番 (numbered by JDL), 摘要 (the marker itself)
COLUMNS = ("//識別フラグ", "伝番", "日付", "借方科目", "借方科目名称", "借方科目正式名称", "借方補助", "借方補助名称", "借方課区",
           "借方税区", "借方税入力方法", "借方金額", "借方消費税", "貸方科目", "貸方科目名称", "貸方科目正式名称", "貸方補助",
           "貸方補助名称", "貸方課区", "貸方税区", "貸方税入力方法", "貸方金額", "貸方消費税", "摘要", "借方取引科目",
           "貸方取引科目", "借方部門コード", "借方部門名称", "貸方部門コード", "貸方部門名称")


def marked(path: Path) -> dict[str, list[list[str]]]:
    found: dict[str, list[list[str]]] = {NORMAL: [], CLOSING: []}
    for group in _groups(_rows(path)):
        for marker in found:
            if any(len(row) > 23 and row[23].startswith(marker) for row in group):
                found[marker].append(group)
    return found


def judge(with_closing: Path, without_closing: Path, after_reimport_without: Path | None = None) -> dict:
    a, b = marked(with_closing), marked(without_closing)
    out: dict = {"with": {k: len(v) for k, v in a.items()}, "without": {k: len(v) for k, v in b.items()}}
    if len(a[NORMAL]) != 1 or len(a[CLOSING]) != 1 or len(b[NORMAL]) != 1:
        out["result"] = "UNDETERMINED"
        out["why"] = "each marker must appear exactly once with closing entries, and CL-NORMAL once without"
        return out
    if len(b[CLOSING]) == 1:
        out["result"] = "JDL_DOES_NOT_SEPARATE"
        out["why"] = "CL-CLOSING is exported even without 決算整理: it was not entered as a closing entry"
        return out
    normal, closing = a[NORMAL][0], a[CLOSING][0]
    if len(normal) != len(closing):
        out["result"] = "UNDETERMINED"
        out["why"] = "the two hand entries do not have the same number of rows"
        return out
    differences = [
        {"row": i + 1, "column": COLUMNS[c] if c < len(COLUMNS) else str(c), "normal": n[c], "closing": k[c]}
        for i, (n, k) in enumerate(zip(normal, closing)) for c in range(max(len(n), len(k)))
        if c not in IGNORED and (n[c] if c < len(n) else "") != (k[c] if c < len(k) else "")
    ]
    out["column_differences"] = differences
    if not differences:
        out["result"] = "CSV_CANNOT_CARRY_CLOSING"
        out["why"] = "JDL separates the closing entry, but its CSV row is identical to the ordinary one"
        return out
    if after_reimport_without is None:
        out["result"] = "CSV_MARK_FOUND_IMPORT_UNVERIFIED"
        return out
    c = marked(after_reimport_without)
    out["after_reimport_without"] = {k: len(v) for k, v in c.items()}
    if len(c[NORMAL]) != 1:
        out["result"] = "UNDETERMINED"
        out["why"] = "CL-NORMAL must be re-exported once after the re-import"
    elif not c[CLOSING]:
        out["result"] = "CSV_MARK_ROUNDTRIPS"
    else:
        out["result"] = "CSV_MARK_LOST_ON_IMPORT"
    return out


CLOSING_SHAPES = (
    # (case id, rows) with the company's closing-entry structures (no customer value): 7530/7534, 7529/7535, 3605/7527, 7531
    ("CI-B1-NO", (("NO", "NO"),)),
    ("CI-B1-NP", (("NP", "NO"),)),
    ("CI-B2-NO", (("NO", "NO"), ("NO", "NO"))),
    ("CI-B1C2-NO", (("NO", "NO"), ("-", "NO"))),  # NB: 2 rows = layout B1C1 (the ID is historical)
)
# 2026-11-07 follow-up: journal 7531 is 1D3C on 3 rows (layout B1C2), which the first import did not cover.
CLOSING_SHAPES_B1C2 = (
    ("CI-B1C2-3ROWS", (("NO", "NO"), ("-", "NO"), ("-", "NO"))),
)
SHAPE_SETS = {"initial": CLOSING_SHAPES, "b1c2": CLOSING_SHAPES_B1C2}


SENTINEL_DATE = "20000101"  # outside any export range: a match after the swap proves the date was month 13


def _month13_swapped(path: Path, closing: str, directory: Path) -> Path:
    """Copy of a JDL CSV where only the month-13 closing date is replaced by SENTINEL_DATE (the strict comparator
    parses dates and rejects month 13). Rows with any other date are untouched."""
    import csv as _csv
    import io

    text = path.read_bytes().decode("cp932")
    rows = list(_csv.reader(io.StringIO(text)))
    for row in rows:
        if len(row) > 2 and row[2] == closing:
            row[2] = SENTINEL_DATE
    buffer = io.StringIO(newline="")
    _csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    target = directory / path.name
    target.write_bytes(buffer.getvalue().encode("cp932"))
    return target


def closing_date(year_end_day: str) -> str:
    """JDL's closing-entry date as observed: the fiscal year-end day with month 13 (20260731 -> 20261331)."""
    return f"{year_end_day[:4]}13{year_end_day[6:]}"


def generate_import(source: Path, company_store: Path, company_id: str, year_end_day: str, output_dir: Path,
                    shapes=CLOSING_SHAPES) -> dict:
    import csv as _csv
    import hashlib
    import io
    from datetime import date

    from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
    from accounting_converter.tools import generate_yayoi_gap_probes as gap
    from accounting_converter.tools import yayoi_gap_probe_plan as gap_plan
    from accounting_converter.tools.yayoi_probe_check import check as probe_check, manifest_path_for

    if "data/private" not in output_dir.resolve().as_posix():
        raise SystemExit("write under data/private only")
    entries, context = gap_plan.load(source, company_store, company_id, gap.VOUCHER_LIMIT)
    day = date(int(year_end_day[:4]), int(year_end_day[4:6]), int(year_end_day[6:]))
    accounts, names = gen._accounts(context)
    synthetic = gap.synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {"NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
              "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "target": "JDL IBEX 出納帳 35.5",
              "company_setting_id": company_id, "probe_date": year_end_day, "voucher_row_limit": gap.VOUCHER_LIMIT,
              "scoped_registry_allowed": False,
              "registry_exclusion_reason": "決算仕訳の表現の確認。構造・税額の会社範囲registryには入れない"}
    control = gap.write_file("CLOSING_CTL", "通常仕訳の対照（決算整理ではない）", [gap.control_case("CI-CTL", accounts)],
                             day, year_end_day, names, synthetic, context, company_id, output_dir, common, check_lengths=True)
    cases = [gap.structural_case(case_id, rows, accounts, "CLOSING", f"決算整理仕訳 {case_id}（日付 {closing_date(year_end_day)}）", 0)
             for case_id, rows in shapes]
    manifest = gap.write_file("CLOSING_IMP", "決算整理仕訳（JDLの出力どおり13月の日付）", cases, day, year_end_day, names,
                              synthetic, context, company_id, output_dir, common, check_lengths=True)
    path = output_dir / manifest["probe_file"]
    rows = list(_csv.reader(io.StringIO(path.read_bytes().decode("cp932"))))
    for row in rows[1:]:
        row[2] = closing_date(year_end_day)
    buffer = io.StringIO(newline="")
    _csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    payload = buffer.getvalue().encode("cp932")
    path.write_bytes(payload)
    manifest.update(probe_sha256=hashlib.sha256(payload).hexdigest(), journal_date_written=closing_date(year_end_day))
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        swapped = _month13_swapped(path, closing_date(year_end_day), Path(directory))
        self_check = probe_check(swapped, swapped, manifest)
    if any(c["verdict"] != "PASS" for c in self_check["cases"].values()):
        raise SystemExit("the comparator cannot read the month-13 date; nothing to import")
    return {"control": control["probe_file"], "closing": manifest["probe_file"],
            "closing_cases": [c["case"] for c in manifest["cases"]], "closing_date": closing_date(year_end_day)}


def judge_import(probe_dir: Path, with_closing: Path, without_closing: Path) -> dict:
    from accounting_converter.tools.yayoi_probe_check import check as probe_check, manifest_path_for

    import tempfile

    out: dict = {"files": {}}
    verdicts = {}
    for path in sorted(probe_dir.glob("YAYOI_GAP_CLOSING_*_NOT_FOR_PRODUCTION.csv")):
        manifest = json.loads(manifest_path_for(path).read_text(encoding="utf-8"))
        closing = closing_date(manifest["probe_date"])
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "p").mkdir(), (work / "w").mkdir(), (work / "o").mkdir()
            probe = _month13_swapped(path, closing, work / "p")
            with_result = probe_check(probe, _month13_swapped(with_closing, closing, work / "w"), manifest)["cases"]
            without_result = probe_check(probe, _month13_swapped(without_closing, closing, work / "o"), manifest)["cases"]
        for case in manifest["cases"]:
            verdicts[case["case"]] = (with_result[case["case"]]["verdict"], without_result[case["case"]]["verdict"])
        out["files"][path.name] = {c: {"with": v[0], "without": v[1]} for c, v in verdicts.items()
                                   if c in {x["case"] for x in manifest["cases"]}}
    control = verdicts.get("CI-CTL")
    closing = {c: v for c, v in verdicts.items() if c != "CI-CTL"}

    def present(path: Path, case: str) -> bool:  # by the 摘要 case ID, whatever else JDL changed
        return any(len(row) > 23 and (row[23] == case or row[23].startswith(case + "-R")) for row in _rows(path))

    seen = {c: (present(with_closing, c), present(without_closing, c)) for c in closing}
    out["present_by_description"] = {c: {"with": w, "without": o} for c, (w, o) in seen.items()}
    if control != ("PASS", "PASS") or not closing:
        out["result"] = "UNDETERMINED"
        out["why"] = "the ordinary control must re-export in both exports"
    elif all(v == ("PASS", "FAIL") for v in closing.values()) and not any(o for _, o in seen.values()):
        out["result"] = "CLOSING_IMPORT_PRESERVED"
    elif not any(w or o for w, o in seen.values()):
        out["result"] = "CLOSING_IMPORT_REJECTED"
    elif any(o for _, o in seen.values()):
        out["result"] = "CLOSING_IMPORTED_AS_ORDINARY"
    else:
        out["result"] = "UNDETERMINED"
        out["why"] = "the closing cases differ from each other; see files"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    g = sub.add_parser("generate-import")
    g.add_argument("--source", type=Path, required=True)
    g.add_argument("--company-store", type=Path, required=True)
    g.add_argument("--company-id", required=True)
    g.add_argument("--year-end-day", required=True, help="YYYYMMDD of the fiscal year end (closing entries)")
    g.add_argument("--output-dir", type=Path, required=True)
    g.add_argument("--shapes", choices=tuple(SHAPE_SETS), default="initial")
    j = sub.add_parser("judge-import")
    j.add_argument("--probe-dir", type=Path, required=True)
    j.add_argument("--with", dest="with_closing", type=Path, required=True)
    j.add_argument("--without", dest="without_closing", type=Path, required=True)
    parser.add_argument("--with", dest="with_closing", type=Path)
    parser.add_argument("--without", dest="without_closing", type=Path)
    parser.add_argument("--after-reimport-without", type=Path)
    args = parser.parse_args()
    if args.command == "generate-import":
        result = generate_import(args.source, args.company_store, args.company_id, args.year_end_day, args.output_dir,
                                 SHAPE_SETS[args.shapes])
    elif args.command == "judge-import":
        result = judge_import(args.probe_dir, args.with_closing, args.without_closing)
    else:
        if args.with_closing is None or args.without_closing is None:
            parser.error("--with and --without are required")
        result = judge(args.with_closing, args.without_closing, args.after_reimport_without)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

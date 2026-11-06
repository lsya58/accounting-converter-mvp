"""Evidence campaign: arrange the generated probes for one JDL session and judge the session.

split-rows
    Keeps every generated case byte-for-byte, but moves cases longer than the
    company's 振替伝票 row limit (default 16) out of A1/A2 into their own file,
    and adds two minimal untaxed boundary cases (exactly LIMIT rows and LIMIT+1
    rows) in separate files. Whether the screen limit also applies to CSV
    Import is unverified; a rejection then cannot hide any other case.
    The original A1/A2 files are moved to a `superseded_*` folder (not deleted).

check
    One re-export of the session period against every probe file of the
    session plus the hand-entered examples (description marker prefix).
    Per case: PASS only when exactly one re-exported journal matches it under
    the existing strict comparator. Session: every re-exported journal must be
    explained (a probe case or a hand-entered example); a marker seen twice
    means a duplicate Import or entry. Prints case IDs, counts and JDL tax
    literals of the hand-entered examples only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools.generate_mf_final_evidence_batch import _temporary_pair
from accounting_converter.tools.mf_full_e2e_compare import FAILURES, _groups, _rows
from accounting_converter.tools.yayoi_probe_check import _comparator, manifest_path_for

DESCRIPTION = 23  # 摘要 column (0-based)


def _write_csv(path: Path, rows) -> bytes:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(
        (jdl_ibex_cashbook_official_journal_import_spec().column_names, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    if path.exists() or manifest_path_for(path).exists():
        raise gen.CampaignError(f"{path.name} already exists; nothing is overwritten")
    path.write_bytes(payload)
    return payload


def _subset(name: str, note: str, picked, base: dict, output_dir: Path, derived) -> dict:
    """picked: [(case dict, rows)] in Import order."""
    path = output_dir / name
    payload = _write_csv(path, [row for _case, rows in picked for row in rows])
    cases = [{**case, "journal_index": index} for index, (case, _rows) in enumerate(picked)]
    manifest = {**{k: v for k, v in base.items() if k not in {"cases", "production_guards_today"}},
                "batch": name.split("_")[3], "batch_note": note, "probe_file": name,
                "probe_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_logical_journals": len(cases), "expected_physical_rows": sum(len(r) for _c, r in picked),
                "derived_from": derived, "cases": cases}
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def split_rows(campaign_dir: Path, company_store: Path, company_id: str, limit: int = 16) -> dict:
    if "data/private" not in campaign_dir.resolve().as_posix():
        raise gen.CampaignError("work under data/private only")
    originals = sorted(campaign_dir.glob("YAYOI_EVIDENCE_CAMPAIGN_A[12]_*_NOT_FOR_PRODUCTION.csv"))
    if len(originals) != 2:
        raise gen.CampaignError("expected the generated A1 and A2 files")
    loaded = {}
    for path in originals:
        manifest = json.loads(manifest_path_for(path).read_text(encoding="utf-8"))
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["probe_sha256"]:
            raise gen.CampaignError(f"{path.name} does not match its manifest")
        groups = _groups(_rows(path))
        loaded[manifest["batch"]] = (path, manifest, [(case, groups[case["journal_index"]]) for case in manifest["cases"]])
    probe_date = loaded["A1"][1]["probe_date"]
    derived = {batch: {"file": path.name, "sha256": manifest["probe_sha256"]} for batch, (path, manifest, _) in loaded.items()}
    long_cases = [item for _b, (_p, _m, items) in sorted(loaded.items()) for item in items if len(item[1]) > limit]

    # Minimal row-count boundary: paired untaxed rows only, so the row count is the only new variable.
    profiles = ConversionProfileStore(company_store / "profiles")
    context = CompanySettingStore(company_store / "companies", profiles).resolve(company_id).context
    accounts, names = gen._accounts(context)
    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    synthetic = gen._synthetic_profile(context)
    boundary = {}
    for rows in (limit, limit + 1):
        case = gen.structural_case(f"ROWS-{rows}", f"振替伝票の行数上限の確認：対象外のみの{rows}行（1行ごとに借方・貸方）",
                                   [f"VOUCHER_ROW_LIMIT:{rows}"], (("NO", "NO"),) * rows, accounts)
        entry = gen._entry(case, 0, day, names, synthetic, context)
        boundary[rows] = ({"case": case.case_id, "physical_rows": rows,
                           "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-{company_id.upper()}-{case.case_id}-SYNTHETIC-ROUNDTRIP-001",
                           "group": "A-ROWLIMIT", "purpose": case.purpose,
                           "expected": (f"{rows}行は会社設定（{limit}行以内）の範囲内。取込・再Exportで一致すればPASS" if rows == limit else
                                        f"取込で拒否されれば『{limit}行を超える伝票はCSVでも取り込めない』（拒否メッセージを記録）。"
                                        "取り込めて一致すればPASS＝上限は画面入力だけ"),
                           "settles": case.settles, "shape": "%dD%dC/%drows" % case.shape},
                          list(gen.serialize([entry], context)))
    superseded = campaign_dir / f"superseded_{probe_date}_before_row_limit_split"
    staging = campaign_dir / f".staging_{probe_date}"
    superseded.mkdir(exist_ok=False)
    staging.mkdir(exist_ok=False)
    base = loaded["A1"][1]
    out = {}
    out["A1"] = _subset(f"YAYOI_EVIDENCE_CAMPAIGN_A1_{probe_date}_NOT_FOR_PRODUCTION.csv",
                        f"既知の書き方・{limit}行以内だけ",
                        [item for item in loaded["A1"][2] if len(item[1]) <= limit], base, staging, derived)
    out["A2"] = _subset(f"YAYOI_EVIDENCE_CAMPAIGN_A2_{probe_date}_NOT_FOR_PRODUCTION.csv",
                        f"税の付く側が通常と逆・{limit}行以内だけ（取込拒否の可能性あり）",
                        [item for item in loaded["A2"][2] if len(item[1]) <= limit], base, staging, derived)
    # The originals are kept (moved aside, not deleted); the new files take the plain names.
    for path in originals:
        shutil.move(str(path), superseded / path.name)
        shutil.move(str(manifest_path_for(path)), superseded / manifest_path_for(path).name)
    for item in sorted(staging.iterdir()):
        shutil.move(str(item), campaign_dir / item.name)
    staging.rmdir()
    out["A3"] = _subset(f"YAYOI_EVIDENCE_CAMPAIGN_A3_{probe_date}_ROWS{limit}_NOT_FOR_PRODUCTION.csv",
                        f"行数上限の確認：ちょうど{limit}行", [boundary[limit]], base, campaign_dir, derived)
    out["A4"] = _subset(f"YAYOI_EVIDENCE_CAMPAIGN_A4_{probe_date}_OVER{limit}_NOT_FOR_PRODUCTION.csv",
                        f"{limit}行を超える伝票（{limit + 1}行の境界と、既存の長い境界ケース）。拒否される可能性あり。最後に取り込む",
                        [boundary[limit + 1], *long_cases], base, campaign_dir, derived)
    return {batch: {"file": m["probe_file"], "cases": len(m["cases"]), "rows": m["expected_physical_rows"],
                    "max_rows": max(c["physical_rows"] for c in m["cases"])} for batch, m in out.items()}


def _marker(group) -> str:
    return re.sub(r"-R\d+$", "", group[0][DESCRIPTION])


def check_session(reexport: Path, probes: list[Path], manual_prefix: str, expected_manual: list[str]) -> dict:
    reexport_groups = _groups(_rows(reexport))
    matched: dict[int, list[str]] = {}
    batches = {}
    for probe in probes:
        manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
        candidate_rows = _rows(probe)
        groups = _groups(candidate_rows)
        comparator = _comparator(candidate_rows)
        verdicts = {}
        for case in manifest["cases"]:
            group = groups[case["journal_index"]]
            hits = []
            for index, other in enumerate(reexport_groups):
                if len(other) != len(group):
                    continue
                with _temporary_pair(group, other) as (left, right):
                    report = comparator.compare(left, right)
                if report.passed and not any(d.classification in FAILURES for d in report.differences):
                    hits.append(index)
            for index in hits:
                matched.setdefault(index, []).append(case["case"])
            verdicts[case["case"]] = ("PASS" if len(hits) == 1 and len(group) == case["physical_rows"]
                                      else "FAIL" if not hits else "DUPLICATE")
        batches[manifest["batch"]] = {"pass": sum(v == "PASS" for v in verdicts.values()),
                                      "cases": len(verdicts), "verdicts": verdicts}
    markers = Counter(_marker(group) for group in reexport_groups)
    manual = {index: _marker(group) for index, group in enumerate(reexport_groups)
              if _marker(group).startswith(manual_prefix)}
    literals = {
        _marker(group): [{"flag": row[0], "debit": row[8:11], "debit_tax_amount": bool(row[12]),
                          "credit": row[18:21], "credit_tax_amount": bool(row[22])} for row in group]
        for index, group in enumerate(reexport_groups) if index in manual
    }
    unexplained = [index for index in range(len(reexport_groups)) if index not in matched and index not in manual]
    return {
        "reexport_journals": len(reexport_groups),
        "reexport_rows": sum(len(group) for group in reexport_groups),
        "batches": batches,
        "manual_examples_found": sorted(manual.values()),
        "manual_examples_missing": sorted(set(expected_manual) - set(manual.values())),
        "manual_examples_tax_literals": literals,
        "duplicate_markers": sorted(marker for marker, count in markers.items() if count > 1),
        "journals_matched_by_two_cases": sorted(index for index, cases in matched.items() if len(cases) > 1),
        "unexplained_reexport_journals": len(unexplained),
        "session_clean": not unexplained and all(count == 1 for count in markers.values()),
    }


# ---------------------------------------------------------------- group B
# Only representations seen in the real JDL self-export are used. Examples the
# Human could not enter with the intended setting stay out (never guessed).
GROUP_B_EXAMPLES = {
    # marker: (side carrying the tax, debit account, credit account, amount)
    "BM-EXPORT": ("CREDIT", "1111", "6121", "11000"),
    "BM-RED8": ("DEBIT", "8471", "1111", "1080"),
    "BM-TRANS80": ("DEBIT", "8471", "1111", "1100"),
}
GROUP_B_PENDING = {
    "BM-NODED10": "控除不可の指定方法が画面で確認できず、通常の10%仕入として入力された（控除不可の表現は未確認）",
    "BM-NODED8": "控除不可の指定方法が画面で確認できず、通常の軽減8%仕入として入力された（控除不可の表現は未確認）",
    "BM-CLOSING": "決算区分の入力方法が確認できず、通常の仕訳として入力された（決算仕訳の表現は未確認）",
}


def observed_group_b(reexport: Path, probe_date: str) -> dict:
    """Literals of the hand-entered examples, from the session's re-export only."""
    groups = _groups(_rows(reexport))
    found = {}
    for marker, (side, debit, credit, amount) in GROUP_B_EXAMPLES.items():
        exact = [g for g in groups if _marker(g) == marker]
        how = "marker"
        if not exact:
            # Entered without its marker: accept only one unambiguous journal with the instructed content.
            exact = [g for g in groups if len(g) == 1 and not g[0][DESCRIPTION] and g[0][2] == probe_date
                     and g[0][3] == debit and g[0][13] == credit and g[0][11] == amount and g[0][21] == amount]
            how = "content_without_marker"
        if len(exact) != 1:
            found[marker] = {"status": "MISSING" if not exact else "AMBIGUOUS"}
            continue
        row = exact[0][0]
        columns = (8, 9, 10, 12) if side == "DEBIT" else (18, 19, 20, 22)
        scope, category, method, tax = (row[i] for i in columns)
        if row[3] != debit or row[13] != credit or row[11] != amount:
            found[marker] = {"status": "CONTENT_DIFFERS"}
            continue
        found[marker] = {"status": "OBSERVED", "identified_by": how, "side": side,
                         "jdl_tax_scope": scope, "jdl_tax_category": category, "jdl_tax_input_method": method,
                         "observed_tax_amount": tax, "amount": amount}
    for marker, reason in GROUP_B_PENDING.items():
        found[marker] = {"status": "PENDING_NOT_ENTERED_AS_INTENDED", "reason": reason,
                         "present_in_reexport": any(_marker(g) == marker for g in groups)}
    return found


def _line(side, code, amount, names, row, marker, literal=None, tax=None):
    from decimal import Decimal

    from accounting_converter.domain.journal import JournalLine, Side, SourceReference, TaxInfo
    from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, LINE_ROW_KEY

    info = None
    if literal is not None:
        info = TaxInfo(category=literal["jdl_tax_category"],
                       tax_amount=None if tax is None else Decimal(tax),
                       metadata={"jdl_tax_scope": literal["jdl_tax_scope"],
                                 "jdl_tax_input_method": literal["jdl_tax_input_method"]})
    return JournalLine(Side[side], names[code], Decimal(amount), SourceReference("synthetic-group-b", row),
                       tax_info=info, metadata={LINE_ROW_KEY: row, LINE_ROW_DESCRIPTION_KEY: marker})


def group_b(campaign_dir: Path, reexport: Path, company_store: Path, company_id: str, probe_date: str,
            session1_date: str = "20260628") -> dict:
    """Synthetic group B Import file built only from observed literals (no customer values)."""
    from datetime import date as _date

    from accounting_converter.application.yayoi_sources import detect_format  # noqa: F401  (source check below)
    from accounting_converter.domain.journal import JournalEntry, SourceReference
    from accounting_converter.domain.journal_rows import ROW_ORDER_KEY

    if "data/private" not in campaign_dir.resolve().as_posix():
        raise gen.CampaignError("work under data/private only")
    observed = observed_group_b(reexport, session1_date)
    lit = {m: v for m, v in observed.items() if v["status"] == "OBSERVED"}
    profiles = ConversionProfileStore(company_store / "profiles")
    context = CompanySettingStore(company_store / "companies", profiles).resolve(company_id).context
    _accounts, names = gen._accounts(context)
    day = _date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    p10 = {"jdl_tax_scope": "仕　入", "jdl_tax_category": "10%", "jdl_tax_input_method": "内税"}
    plans = []  # (case_id, purpose, settles, [(row, side, code, amount, literal, tax)])
    if "BM-EXPORT" in lit:
        e = lit["BM-EXPORT"]
        plans += [
            ("BI-EXPORT", "輸出売上（課区『輸出売』）の取込往復。1行", ["TAX_UNAVAILABLE:EXPORT_EXEMPT:CREDIT"],
             [(1, "DEBIT", "1111", "11000", None, None), (1, "CREDIT", "6121", "11000", e, None)]),
            ("BI-EXPORT-2D2C", "輸出売上を含む会社Aの構造（1行目 貸方 輸出売、2行目 対象外同士。35仕訳）",
             ["TAX_UNAVAILABLE:EXPORT_EXEMPT:CREDIT", "TAXED_2D2C_LAYOUT:C:EXPORT"],
             [(1, "DEBIT", "1111", "1100", None, None), (1, "CREDIT", "6121", "1100", e, None),
              (2, "DEBIT", "1111", "1100", None, None), (2, "CREDIT", "3181", "1100", None, None)]),
        ]
    if "BM-RED8" in lit:
        r = lit["BM-RED8"]
        plans += [
            ("BI-RED8", "軽減8%仕入（仕　入／軽減8%／内税）の取込往復。1行・明示税額80", ["TAX_UNAVAILABLE:REDUCED_8:DEBIT"],
             [(1, "DEBIT", "8471", "1080", r, "80"), (1, "CREDIT", "1111", "1080", None, None)]),
            ("BI-RED8-2D1C", "軽減8%を含む構造（1行目 課税仕入10%と対象外、2行目 軽減8%）",
             ["TAX_UNAVAILABLE:REDUCED_8:DEBIT"],
             [(1, "DEBIT", "8471", "1100", p10, "100"), (1, "CREDIT", "1111", "2180", None, None),
              (2, "DEBIT", "8471", "1080", r, "80")]),
        ]
    if "BM-TRANS80" in lit:
        t = lit["BM-TRANS80"]
        plans += [
            ("BI-TRANS80", "80%経過措置（仕　入／10%免80／内税）の取込往復。1行・明示税額80", ["TAX_UNAVAILABLE:TRANSITIONAL_80:DEBIT"],
             [(1, "DEBIT", "8471", "1100", t, "80"), (1, "CREDIT", "1111", "1100", None, None)]),
            ("BI-TRANS80-1D2C", "80%経過措置を含む会社Aの構造（1行目 借方10%免80と対象外、2行目 対象外。14仕訳）",
             ["TAX_UNAVAILABLE:TRANSITIONAL_80:DEBIT"],
             [(1, "DEBIT", "8471", "2200", t, "160"), (1, "CREDIT", "1111", "1100", None, None),
              (2, "CREDIT", "3181", "1100", None, None)]),
        ]
    entries, cases = [], []
    for index, (case_id, purpose, settles, lines) in enumerate(plans):
        rows = sorted({row for row, *_ in lines})
        markers = {row: case_id if len(rows) == 1 else f"{case_id}-R{row}" for row in rows}
        built = [_line(side, code, amount, names, row, markers[row], literal, tax)
                 for row, side, code, amount, literal, tax in lines]
        entry = JournalEntry(f"probe:{case_id}", SourceReference("synthetic-group-b", index), day, built,
                             description=case_id if len(rows) == 1 else None,
                             metadata={ROW_ORDER_KEY: tuple(rows)})
        if entry.debit_total() != entry.credit_total():
            raise gen.CampaignError(f"{case_id} does not balance")
        entries.append(entry)
        debit = sum(1 for line in built if line.side.value == "DEBIT")
        cases.append({"case": case_id, "journal_index": index, "physical_rows": len(rows),
                      "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-{company_id.upper()}-{case_id}-SYNTHETIC-ROUNDTRIP-001",
                      "group": "B", "purpose": purpose, "settles": settles,
                      "expected": "再Exportで全列が一致（既知の正規化のみ）。税区分・明示税額が変わらない",
                      "shape": f"{debit}D{len(built) - debit}C/{len(rows)}rows"})
    rows = gen.serialize(entries, context)
    gen.JDLOutputAdapter._validate_field_lengths(rows)
    path = campaign_dir / f"YAYOI_EVIDENCE_CAMPAIGN_B_{probe_date}_NOT_FOR_PRODUCTION.csv"
    payload = _write_csv(path, rows)
    manifest = {"NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
                "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "batch": "B", "probe_date": probe_date,
                "company_setting_id": company_id, "probe_file": path.name,
                "probe_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_logical_journals": len(cases), "expected_physical_rows": len(rows),
                "literals_from_session1_self_export": observed,
                "not_generated": {m: v["reason"] for m, v in observed.items() if v["status"].startswith("PENDING")},
                "cases": cases}
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    result = check_session(path, [path], "BM-", [])
    if result["unexplained_reexport_journals"] or any(
            v != "PASS" for b in result["batches"].values() for v in b["verdicts"].values()):
        raise gen.CampaignError("group B self-comparison failed")
    return {"file": path.name, "journals": len(cases), "rows": len(rows), "cases": [c["case"] for c in cases],
            "observed": {m: v["status"] for m, v in observed.items()}}


# ---------------------------------------------------------------- reassess
CATEGORY_ORDER = (
    "ROW_LIMIT_16",                 # longer than the company's voucher limit: cannot be one JDL voucher
    "UNRESOLVED_REPRESENTATION",    # 控除不可 / 決算: JDL representation still unknown
    "NO_EVIDENCE",                  # other conditions with no real JDL Evidence (rare shapes etc.)
    "EVIDENCE_READY_NEEDS_IMPLEMENTATION",  # every condition has real Evidence; code/registry not yet changed
    "NO_TECHNICAL_CONDITION",       # existing production Evidence already covers it
)


def passed_settles(sessions: list[tuple[Path, list[Path]]]) -> tuple[set[str], dict]:
    """Keys settled by cases that PASSed in the real re-exports (recomputed, not read from notes)."""
    settled, summary = set(), {}
    for reexport, probes in sessions:
        result = check_session(reexport, probes, "BM", [])
        for probe in probes:
            manifest = json.loads(manifest_path_for(probe).read_text(encoding="utf-8"))
            verdicts = result["batches"][manifest["batch"]]["verdicts"]
            summary[manifest["batch"]] = f"{sum(v == 'PASS' for v in verdicts.values())}/{len(verdicts)}"
            for case in manifest["cases"]:
                if verdicts[case["case"]] == "PASS":
                    settled.update(case["settles"])
    return settled, summary


def reassess(source: Path, company_store: Path, company_id: str, sessions, row_limit: int = 16) -> dict:
    from accounting_converter.application.yayoi_sources import detect_format
    from accounting_converter.domain.journal_rows import journal_physical_rows
    from accounting_converter.tools import yayoi_evidence_campaign as campaign

    settled, batches = passed_settles(sessions)
    settled |= set(gen.EXISTING_SYNTHETIC_EVIDENCE)
    # Observed literal now has a real round trip (group B); the 2D2C export layout is its own case.
    settled |= {"TAXED_2D2C_LAYOUT:C:EXPORT"}
    # 非課税売上 on 9111 is existing real Evidence (the company's exact candidate is 9111);
    # it holds only if the Human maps to 9111, so it is reported as conditional below.
    settled |= {"NONSALE_TARGET_ACCOUNT"}
    profiles = ConversionProfileStore(company_store / "profiles")
    context = CompanySettingStore(company_store / "companies", profiles).resolve(company_id).context
    entries = detect_format(source).diagnose(source).entries
    categories, open_keys, conditional = Counter(), Counter(), Counter()
    implementation_keys = Counter()
    for entry in entries:
        keys, _profile = campaign.journal_keys(entry, context)
        rows = journal_physical_rows(entry)
        unresolved = {k for k in keys if k.startswith(("TAX_UNAVAILABLE:NON_DEDUCTIBLE", "CLOSING_ENTRY"))}
        # 対象外 on a purchase account: JDL representation already known (blank tax); candidate only.
        known = {k for k in keys if "OUT_OF_SCOPE_KNOWN_REPRESENTATION" in k}
        missing = keys - settled - unresolved - known
        if rows is not None and len(rows) > row_limit:
            category = "ROW_LIMIT_16"
        elif unresolved:
            category = "UNRESOLVED_REPRESENTATION"
        elif missing:
            category = "NO_EVIDENCE"
            open_keys.update(campaign.family(k) for k in missing)
        elif keys:
            category = "EVIDENCE_READY_NEEDS_IMPLEMENTATION"
            implementation_keys.update(campaign.family(k) for k in keys)
        else:
            category = "NO_TECHNICAL_CONDITION"
        categories[category] += 1
        if category in {"EVIDENCE_READY_NEEDS_IMPLEMENTATION", "NO_TECHNICAL_CONDITION"}:
            # Account-specific Evidence (課税売上10%: 6121/6131/6181/9251, 非課税売上: 9111). 非課税仕入
            # is verified on four accounts after the campaign, so it is no longer account-specific.
            for key in keys & {"SALES10_TARGET_ACCOUNT", "NONSALE_TARGET_ACCOUNT"}:
                conditional[key] += 1
    return {
        "journals": len(entries),
        "case_results": batches,
        "categories": {name: categories.get(name, 0) for name in CATEGORY_ORDER},
        "no_evidence_by_family": dict(open_keys.most_common()),
        "implementation_needed_by_family": dict(implementation_keys.most_common()),
        "valid_only_if_human_maps_to_verified_accounts": dict(conditional),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    split = sub.add_parser("split-rows")
    split.add_argument("--campaign-dir", type=Path, required=True)
    split.add_argument("--company-store", type=Path, required=True)
    split.add_argument("--company-id", required=True)
    split.add_argument("--limit", type=int, default=16)
    session = sub.add_parser("check")
    session.add_argument("--reexport", type=Path, required=True)
    session.add_argument("--probe", type=Path, action="append", required=True)
    session.add_argument("--manual-prefix", default="BM-")
    session.add_argument("--expected-manual", action="append", default=[])
    groupb = sub.add_parser("group-b")
    groupb.add_argument("--campaign-dir", type=Path, required=True)
    groupb.add_argument("--reexport", type=Path, required=True)
    groupb.add_argument("--company-store", type=Path, required=True)
    groupb.add_argument("--company-id", required=True)
    groupb.add_argument("--date", required=True)
    re_ = sub.add_parser("reassess")
    re_.add_argument("--source", type=Path, required=True)
    re_.add_argument("--company-store", type=Path, required=True)
    re_.add_argument("--company-id", required=True)
    re_.add_argument("--session", nargs="+", action="append", required=True,
                     help="REEXPORT PROBE [PROBE ...] (one per JDL session)")
    args = parser.parse_args()
    if args.command == "reassess":
        sessions = [(Path(items[0]), [Path(p) for p in items[1:]]) for items in args.session]
        print(json.dumps(reassess(args.source, args.company_store, args.company_id, sessions),
                         ensure_ascii=False, indent=1))
        return 0
    if args.command == "group-b":
        print(json.dumps(group_b(args.campaign_dir, args.reexport, args.company_store, args.company_id, args.date),
                         ensure_ascii=False, indent=1))
        return 0
    if args.command == "split-rows":
        result = split_rows(args.campaign_dir, args.company_store, args.company_id, args.limit)
    else:
        result = check_session(args.reexport, args.probe, args.manual_prefix, args.expected_manual)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

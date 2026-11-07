"""Synthetic JDL Probes for what the remaining over-limit / 控除不可 journals still need (round 4).

NOT_FOR_PRODUCTION, fully synthetic (no customer amount, description or date). Only the account-free conditions
that the registered scoped Evidence does not prove yet are probed:

  SPLIT  the JDL voucher layouts and tax cells of the parts that the Human-approvable voucher split
         (application/voucher_split, rule SINGLE_COUNTERPART_BALANCED_V1) would write for the company's over-limit
         journals, where the registry has no round trip yet (e.g. C1D14 with 軽減8%).
  NP     the 非仕入 debit cell in the layouts of the 控除不可 journals (e.g. B1D4 of journal 565). This proves the
         JDL structure only; 控除不可 stays blocked until the tax accountant's sign-off is recorded.

Conditions already proven are never probed again. Files are written by the round-3 writer
(generate_yayoi_gap_probes.write_file), so `yayoi_gap_probe_check check` and `build_scoped_evidence_registry
--gap-dir` read them unchanged. Nothing here registers Evidence, changes readiness or touches saved settings.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.adapters.output.jdl.scoped_evidence import SCOPE_ID
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application import noncredit_approval
from accounting_converter.application import voucher_split
from accounting_converter.application.yayoi_review import candidate_semantic
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import generate_yayoi_gap_probes as gap
from accounting_converter.tools import yayoi_gap_probe_plan as gap_plan

NO, NONE = "NO", "-"
# Earlier probe days on the company's JDL test copy (never reused).
USED_PROBE_DAYS = frozenset({"20260331", "20260529", "20260615", "20260616", "20260621", "20260627", "20260628",
                             "20260705", "20260719", "20260726"})


def _cell(line) -> str | None:
    category = line.tax_info.category if line.tax_info and line.tax_info.category else None
    if category is None:
        return NO
    if noncredit_approval.is_target_identity(category):
        return "NP"  # the writing the signed approval would use (structure only)
    semantic = candidate_semantic(category)
    return scoped.SEMANTIC_CELL.get(semantic.value) if semantic else None


def signature(entry) -> tuple[tuple[tuple[str, str], ...], str] | None:
    rows = journal_physical_rows(entry)
    if rows is None or entry.metadata.get("yayoi_closing"):
        return None
    cells = []
    for row in rows:
        pair = []
        for line in (row.debit, row.credit):
            cell = NONE if line is None else _cell(line)
            if cell is None:
                return None
            pair.append(cell)
        cells.append(tuple(pair))
    return tuple(cells), scoped.layout_of(rows)


def needed(entries, row_limit: int) -> dict:
    """layout -> {"cells": {(side, cell)}, "journals": {source journal ids}, "layout_missing": bool}."""
    found: dict = defaultdict(lambda: {"cells": set(), "journals": set(), "layout_missing": False})
    for entry in entries:
        plan = voucher_split.plan_split(entry, row_limit)
        noncredit = any(noncredit_approval.is_target_identity(l.tax_info.category if l.tax_info else None)
                        for l in entry.lines)
        if plan is not None:
            parts = voucher_split.split_entry(entry, plan)
        elif noncredit and len(journal_physical_rows(entry) or ()) <= row_limit:
            parts = (entry,)
        else:
            continue
        for part in parts:
            record = signature(part)
            if record is None:
                continue
            cells, layout = record
            for condition in gap_plan.conditions(cells, layout, ()):
                kind = condition[0]
                if kind == "LAYOUT":
                    found[layout]["layout_missing"] = True
                elif kind == "CELL":
                    found[layout]["cells"].add((condition[2], condition[3]))
                elif kind == "PAIR":
                    raise gen.CampaignError(f"{entry.id}: a row with tax on both sides; not a split part")
                else:
                    continue
                found[layout]["journals"].add(entry.id)
    return found


def probe_signature(layout: str, cells: set[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """Rows of the layout (B1Dn / C1Dn only) carrying every needed debit cell once; other debits 課税仕入10%."""
    kind, count = layout[:2], int(layout[3:])
    if kind not in {"B1", "C1"} or layout[2] != "D":
        raise gen.CampaignError(f"unexpected layout {layout}")
    if any(side != "DEBIT" for side, _ in cells):
        raise gen.CampaignError(f"{layout}: only debit cells are expected for split parts")
    wanted = sorted({cell for _, cell in cells})
    debit_rows = count + (1 if kind == "B1" else 0)
    fill = [*wanted] + ["P10"] * (debit_rows - len(wanted))
    if len(wanted) > debit_rows:
        raise gen.CampaignError(f"{layout}: more cells than rows")
    rows = [(fill[0], NO)] if kind == "B1" else [(NONE, NO)]
    rows += [(cell, NONE) for cell in (fill[1:] if kind == "B1" else fill)]
    return tuple(rows)


def generate(source: Path, company_store: Path, company_id: str, probe_date: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise gen.CampaignError("probe files contain the company's JDL master names; write them under data/private only")
    if probe_date in USED_PROBE_DAYS:
        raise gen.CampaignError("this day was used by an earlier probe; choose another")
    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    entries, context = gap_plan.load(source, company_store, company_id, gap.VOUCHER_LIMIT)
    if not ev.context_is_verified(context) or scoped.scope_state(context) is not scoped.ScopeState.IN_SCOPE:
        raise gen.CampaignError("the company is not in the verified scope (税抜・原則・一括比例・端数・16行)")
    if any(entry.date == day for entry in entries):
        raise gen.CampaignError("the probe date has source journals; choose a day without any")
    found = needed(entries, gap.VOUCHER_LIMIT)
    accounts, names = gen._accounts(context)
    files: dict[str, list] = {"SPLIT": [], "NP": []}
    for layout in sorted(found, key=lambda l: (l[:2], int(l[3:]))):
        info = found[layout]
        if not info["layout_missing"] and not info["cells"]:
            continue
        rows = probe_signature(layout, info["cells"])
        has_np = any(cell == "NP" for row in rows for cell in row)
        case_id = f"{'NP' if has_np else 'SP'}-{layout}"
        case = gap.structural_case(case_id, rows, accounts, "G-NP" if has_np else "G-SPLIT",
                                   f"{layout} の配置 {''.join(f'[{d}|{c}]' for d, c in rows)}"
                                   + ("（控除不可の非仕入：構造だけ。控除不可の変換は税理士確認まで止める）" if has_np else
                                      "（Human承認された伝票分割で出る形）"),
                                   len(info["journals"]))
        case.proves = gap.conditions_of(rows, layout)
        files["NP" if has_np else "SPLIT"].append((case, sorted(info["journals"])))
    synthetic = gap.synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "source_kind": "fully_synthetic_JDL_target_probe_with_company_structure",
        "round": "4: voucher split parts and 非仕入 placement",
        "target": "JDL IBEX 出納帳 35.5", "company_setting_id": company_id, "scope_id": SCOPE_ID,
        "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value, "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "voucher_row_limit": gap.VOUCHER_LIMIT, "probe_date": probe_date,
        "registry_note": "PASS proves the JDL layout / cell only. The split itself still needs the Human's recorded approval; "
                         "the NP cases never make 控除不可 convert without the tax accountant's sign-off.",
        "must_verify_before_import": [
            "company_data_restored_from_the_existing_backup_and_a_fresh_backup_taken_first",
            "probe_date_inside_the_fiscal_period_with_no_existing_journal",
            "tax_settings: 税抜・原則課税・一括比例配分, 端数 売上=切上げ / 仕入=四捨五入, 振替伝票入力行数=16",
        ],
    }
    manifests, journals = {}, {}
    for name, items in files.items():
        if not items:
            continue
        cases = [gap.control_case(f"CTL-{name}", accounts), *(case for case, _ in items)]
        manifest = gap.write_file(name, {"SPLIT": "伝票分割の各伝票の配置（16行以内）", "NP": "非仕入（借方）の配置"}[name],
                                  cases, day, probe_date, names, synthetic, context, company_id, output_dir, common,
                                  check_lengths=True)
        manifests[name] = manifest
        journals[name] = {case.case_id: ids for case, ids in items}
    return {"files": manifests, "journals_needing_each_case": journals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--probe-date", required=True, help="YYYYMMDD: a day with no journals in the JDL company")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.source, args.company_store, args.company_id, args.probe_date, args.output_dir)
    print(json.dumps({
        "files": {n: {"file": m["probe_file"], "sha256": m["probe_sha256"][:16], "journals": m["expected_logical_journals"],
                      "rows": m["expected_physical_rows"], "cases": [c["case"] for c in m["cases"]]}
                  for n, m in result["files"].items()},
        "journals_needing_each_case": {n: {k: len(v) for k, v in d.items()} for n, d in result["journals_needing_each_case"].items()},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

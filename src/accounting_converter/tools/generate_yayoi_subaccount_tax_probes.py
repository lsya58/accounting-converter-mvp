"""NOT_FOR_PRODUCTION JDL Probes for one Yayoi company: subaccount omission on parents that HAVE JDL
subaccounts, and the account-level tax Evidence still missing. Fully synthetic amounts and descriptions.

Files (one probe day, one re-export; every file starts with a known-good control):
  TAX15         15 one-row cases: 軽減8% / 80%経過措置 / 課税仕入10% / 課税売上10% on the exact
                (account, relation) pairs that block journals today. Known JDL literals only.
  SUB_KEEP      the parent WITH its existing JDL subaccount (code + name from the master), one per
                parent that has subaccounts. Expected to round-trip (the normal "keep" path).
  SUB_BLANK     blank subaccount code AND name on a parent with subaccounts not covered by the
                existing rejection Evidence (1551 / 1311 were rejected on 2026-05-15/16 in another
                company: not repeated). Expected: Import rejected.
  SUB_0000      subaccount code "0000" with a blank name. No Evidence anywhere: outcome unknown.
  SUB_NAMEONLY  blank code with the name of an existing subaccount. No Evidence: outcome unknown.
Risky files are separate so a whole-file rejection never hides another case; import them last.
A PASS of SUB_0000 / SUB_NAMEONLY would mean JDL keeps exactly that row; any change (another
subaccount assigned, amount moved) shows as CHANGED with the raw cells. Nothing here registers
Evidence, changes a setting, or makes anything READY.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl.scoped_evidence import SCOPE_ID
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import generate_yayoi_gap_probes as gp
from accounting_converter.tools.yayoi_probe_check import check, manifest_path_for

D = Decimal
# Columns of the 30-column JDL import (0-based): subaccount code / name per side.
SUB_COLUMNS = {"DEBIT": (6, 7), "CREDIT": (16, 17)}

# (case, side carrying the cell, account, cell, amount, written tax, relation) - the exact pairs that
# block journals in the company's data (see yayoi_master_update_impact); amounts give that relation.
TAX_CASES = (
    ("TX-R8-8491-EXACT", "8491", "R8", "1080", "80", "EXACT"),
    ("TX-R8-8491-HALFHIGH", "8491", "R8", "1200", "89", "HALF_HIGH"),
    ("TX-R8-8491-HALFLOW", "8491", "R8", "1000", "74", "HALF_LOW"),
    ("TX-R8-8451-HALFLOW", "8451", "R8", "1000", "74", "HALF_LOW"),
    ("TX-T80-7121-EXACT", "7121", "T80", "1100", "80", "EXACT"),
    ("TX-T80-7121-HALFHIGH", "7121", "T80", "1000", "73", "HALF_HIGH"),
    ("TX-T80-8451-EXACT", "8451", "T80", "1100", "80", "EXACT"),
    ("TX-T80-8621-FLOORHIGH", "8621", "T80", "1000", "72", "FLOOR_HIGH"),
    ("TX-T80-8641-HALFLOW", "8641", "T80", "1050", "76", "HALF_LOW"),
    ("TX-T80-8751-EXACT", "8751", "T80", "1100", "80", "EXACT"),
    ("TX-T80-8751-FLOORHIGH", "8751", "T80", "1000", "72", "FLOOR_HIGH"),
    ("TX-T80-8751-HALFHIGH", "8751", "T80", "1000", "73", "HALF_HIGH"),
    ("TX-T80-8751-HALFLOW", "8751", "T80", "1050", "76", "HALF_LOW"),
    ("TX-P10-7141-COMPANY", "7141", "P10", "1106", "101", "COMPANY"),
)
SALES_FLOOR_9251 = ("TX-S10-9251-FLOOR", "9251", "S10", "1105", "100", "FLOOR")
# Layouts / tax placements that block journals once the subaccounts are decided (the existing MF path then
# fails on the account and the company-scoped Evidence decides). Structure only; from the impact analysis.
STRUCTURE_SIGNATURES = (
    ("ST-B1C1B1-S10", (("NO", "S10"), ("-", "NO"), ("NO", "NO")), 10),
    ("ST-B1D1-S10P10", (("NO", "S10"), ("P10", "-")), 6),
    ("ST-B1D1-NPP10", (("NP", "NO"), ("P10", "-")), 1),
    ("ST-B1D1-P10NP", (("P10", "NO"), ("NP", "-")), 1),
    ("ST-B5D1B4-S10P10", (("NO", "S10"),) * 5 + (("P10", "-"),) + (("NO", "S10"),) * 4, 1),
    ("ST-B1C1B1-P10", (("NO", "NO"), ("-", "P10"), ("P10", "NO")), 1),
)
# Parents not covered by the existing blank-subaccount rejection Evidence (1551 / 1311, other company).
BLANK_EVIDENCE_EXISTS = {"1551": "EVID-JDL-35-5-BLANK-SUB-REJECT-1551-001", "1311": "EVID-JDL-35-5-BLANK-SUB-REJECT-1311-001"}


@dataclass
class SubCase:
    case: gp.Case
    overrides: dict[str, tuple[str, str]] = field(default_factory=dict)  # side -> (code, name) written raw


def tax_cases(accounts) -> list[SubCase]:
    cases = []
    for case_id, code, cell, amount, tax, relation in TAX_CASES:
        cases.append(SubCase(gp.one_row(
            case_id, "TAX", f"借方 {code} の{cell}・明示税額の関係 {relation}（その科目で未確認）",
            gp.KEEP, gp.Line(cell, code, D(amount), D(tax)), gp.Line("NO", accounts["cash"], D(amount)),
            proves=[f"ACCOUNT:DEBIT:{code}:{cell}:{relation}"])))
    case_id, code, cell, amount, tax, relation = SALES_FLOOR_9251
    cases.append(SubCase(gp.one_row(
        case_id, "TAX", f"貸方 {code} の課税売上10%・切捨ての明示税額（その科目で未確認）",
        gp.KEEP, gp.Line("NO", accounts["cash"], D(amount)), gp.Line(cell, code, D(amount), D(tax)),
        proves=[f"ACCOUNT:CREDIT:{code}:{cell}:{relation}"])))
    return cases


def _parent_side(code: str) -> str:
    return "CREDIT" if code in {"1551"} else "DEBIT"  # 売掛金 collected; 買掛金 / 預金 debited


def _sub_case(case_id: str, parent: str, accounts, purpose: str, expected: str, override, proves) -> SubCase:
    side = _parent_side(parent)
    amount = D("1100")
    parent_line, cash_line = gp.Line("NO", parent, amount), gp.Line("NO", accounts["cash"], amount)
    debit, credit = (parent_line, cash_line) if side == "DEBIT" else (cash_line, parent_line)
    return SubCase(gp.one_row(case_id, "SUBACCOUNT", purpose, expected, debit, credit, proves=proves),
                   {side: override})


def subaccount_files(context, accounts) -> dict[str, tuple[str, list[SubCase]]]:
    subs: dict[str, list] = {}
    for item in context.subaccounts:
        subs.setdefault(item.parent_account_code, []).append(item)
    parents = sorted(subs)
    first = {p: sorted(subs[p], key=lambda s: s.output_code)[0] for p in parents}
    keep = [_sub_case(f"SK-{p}", p, accounts, f"{p} を既存の補助 {first[p].output_code} 付きで出力（通常の補助保持）",
                      "再Exportで補助コード・名称が一致（数値補助の先頭0の正規化のみ）", (first[p].output_code, first[p].output_name),
                      [f"SUBACCOUNT:{p}:KEEP"]) for p in parents]
    blank = [_sub_case(f"SB-{p}", p, accounts, f"{p}（補助あり）に補助コード・名称とも空欄",
                       "取込拒否の見込み（1551・1311は他社で拒否済み）。取り込まれた場合は再Exportで補助が付くかを確認", ("", ""),
                       [f"SUBACCOUNT:{p}:BLANK"]) for p in parents if p not in BLANK_EVIDENCE_EXISTS]
    zero = [_sub_case(f"SZ-{p}", p, accounts, f"{p}（補助あり）に補助コード0000・名称空欄",
                      "結果は未知。取込拒否／0000のまま保持／別の補助に変わる、のいずれかを観測する", ("0000", ""),
                      [f"SUBACCOUNT:{p}:CODE0000"]) for p in parents if p != "1311"]
    name_only = [_sub_case(f"SN-{p}", p, accounts, f"{p}（補助あり）に補助コード空欄・既存補助の名称のみ",
                           "結果は未知。取込拒否／名称から補助コードが補われる、のいずれかを観測する", ("", first[p].output_name),
                           [f"SUBACCOUNT:{p}:NAME_ONLY"]) for p in parents if p != "1311"]
    structure = [SubCase(gp.structural_case(case_id, signature, accounts, "STRUCTURE",
                                            f"{signature} の配置（{journals}仕訳）", journals))
                 for case_id, signature, journals in STRUCTURE_SIGNATURES]
    return {
        "SUBTAX_TAX15": ("科目別の税額Evidence（既知の書き方のみ）", tax_cases(accounts)),
        "SUBTAX_STRUCT6": ("補助確定後に表に出るレイアウト・税の配置（既知の書き方のみ）", structure),
        "SUBTAX_SUB_KEEP": ("補助のある親科目を既存補助付きで出力（通常の保持）", keep),
        "SUBTAX_SUB_BLANK": ("補助のある親科目に空欄補助（拒否見込み）", blank),
        "SUBTAX_SUB_0000": ("補助コード0000（未知）", zero),
        "SUBTAX_SUB_NAMEONLY": ("補助名称のみ（未知）", name_only),
    }


def write_file(name: str, note: str, cases: list[SubCase], day: date, probe_date: str, names, profile, context,
               company_id: str, output_dir: Path, common: dict) -> dict:
    entries = [gp.build_entry(c.case, i, day, names, profile, context) for i, c in enumerate(cases)]
    for entry in entries:
        if entry.debit_total() != entry.credit_total():
            raise gen.CampaignError(f"{entry.id} does not balance")
    chunks = gp.serialize_case_rows(entries, context, [c.case for c in cases])
    rows = []
    for sub_case, chunk in zip(cases, chunks, strict=True):
        for row in chunk:
            row = list(row)
            for side, (code, name_value) in sub_case.overrides.items():
                code_column, name_column = SUB_COLUMNS[side]
                row[code_column], row[name_column] = code, name_value
            rows.append(tuple(row))
    gen.JDLOutputAdapter._validate_field_lengths(tuple(rows))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((jdl_ibex_cashbook_official_journal_import_spec().column_names, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    path = output_dir / f"YAYOI_GAP_{name}_{probe_date}_NOT_FOR_PRODUCTION.csv"
    if path.exists() or manifest_path_for(path).exists():
        raise gen.CampaignError(f"{path.name} already exists; nothing is overwritten")
    path.write_bytes(payload)
    manifest = {
        **common, "batch": name, "batch_note": note, "probe_file": path.name,
        "probe_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_logical_journals": len(cases), "expected_physical_rows": len(rows),
        "cases": [{"case": c.case.case_id, "journal_index": i, "physical_rows": len(c.case.rows),
                   "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-BUDDIES-GAP-{c.case.case_id}-SYNTHETIC-ROUNDTRIP-001",
                   "group": c.case.group, "purpose": c.case.purpose, "expected": c.case.expected, "proves": c.case.proves,
                   "shape": "%dD%dC/%drows" % c.case.shape, "description_under_test": False,
                   "subaccount_written": {side: {"code": code, "name_present": bool(nm)} for side, (code, nm) in c.overrides.items()}}
                  for i, c in enumerate(cases)],
    }
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Rows with an incomplete subaccount identity (code only / name only) cannot be read by the strict
    # comparator; the round check judges them by raw cells. Self-check only the complete files.
    if all(code and nm or not code and not nm for c in cases for code, nm in c.overrides.values()):
        result = check(path, path, manifest)
        if any(r["verdict"] != "PASS" for r in result["cases"].values()):
            raise gen.CampaignError(f"{name}: self-comparison failed")
    return manifest


def generate(company_store: Path, company_id: str, source: Path, probe_date: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise gen.CampaignError("probe files contain the company's master names; write them under data/private only")
    from accounting_converter.application.yayoi_sources import detect_format

    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    if any(entry.date == day for entry in detect_format(source).diagnose(source).entries):
        raise gen.CampaignError("the probe date has source journals; choose a day without any")
    profiles = ConversionProfileStore(company_store / "profiles")
    context = CompanySettingStore(company_store / "companies", profiles).resolve(company_id).context
    if context is None or not ev.context_is_verified(context):
        raise gen.CampaignError("the company has no confirmed Tax Context")
    accounts, names = gen._accounts(context)
    synthetic = gp.synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "target": "JDL IBEX 出納帳 35.5", "company_setting_id": company_id,
        "scope_id": SCOPE_ID, "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value, "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "voucher_row_limit": 16, "probe_date": probe_date,
        "existing_blank_subaccount_evidence_not_repeated": BLANK_EVIDENCE_EXISTS,
    }
    out = {}
    for name, (note, cases) in subaccount_files(context, accounts).items():
        if not cases:
            continue
        control = SubCase(gp.control_case(f"CTL-{name.split('_', 1)[1]}", accounts))
        out[name] = write_file(name, note, [control, *cases], day, probe_date, names, synthetic, context,
                               company_id, output_dir, common)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--probe-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.company_store, args.company_id, args.source, args.probe_date, args.output_dir)
    print(json.dumps({n: {"file": m["probe_file"], "journals": m["expected_logical_journals"], "rows": m["expected_physical_rows"],
                          "cases": [c["case"] for c in m["cases"]]} for n, m in result.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

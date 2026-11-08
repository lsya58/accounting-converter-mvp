"""JDL 振替伝票入力行数「64行以内」: analysis, minimal real-JDL Probe, check and forecast (round 5).

JDL IBEX 出納帳 35.5 offers 16 or 64 rows per 振替伝票 (会社情報). The JDL product page says the voucher takes
「最大で借方64行・貸方64行」 (screen entry; https://www.jdlibex.net/pkg/ab/input.html, no version given). What a CSV
Import counts is NOT known: CSV physical rows (one row may carry a debit and a credit) or lines per side. Every scoped
Evidence so far ran with 16 (`EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-16-001`). Nothing here assumes 64 behaves
the same: a company set to 64 stays blocked (VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED) until a valid real round is
registered in `scoped_evidence_registry.ROW_LIMIT_SCOPES`.

  analyze   per journal over 16 physical rows: debit lines, credit lines, physical rows (never mixed up), whether 64
            fits by physical rows and by lines per side, split eligibility, blockers now / under 64 today (unverified)
            / under 64 if every planned case passed, for both counting rules (forecast, never READY).
  generate  the Probe files (fully synthetic, structure only; NOT_FOR_PRODUCTION) under data/private, one boundary
            or risk per file so that one rejected file never hides another (a JDL CSV Import is all-or-nothing):
              R64A      control, B64 (64 rows, 64 lines each side), INV (every registered tax cell and row pair: carries
                        the 16-row layouts), REL (every registered explicit-tax rounding relation: carries them)
              R64SUB    control, JDL subaccount code + name on 1551 / 3141 (carries subaccounts)
              R64L1..   control and up to five 17..64-row layouts each, for the company's journals / 64-row split parts
              R64SIDED  control, 65 rows with 64 debit lines and 1 credit line (journal 7265 itself)
              R64SIDEC  control, 65 rows with 1 debit line and 64 credit lines
              R64OVERD  control, 65 debit lines (66 rows): must be rejected
              R64OVERC  control, 65 credit lines (65 rows): must be rejected
              fallback/ one file per case of R64A / R64SUB / R64L*: imported only when its group file was rejected,
                        so every case is still judged in the same session
              closing/  決算整理仕訳 (month 13) control + the five imported closing shapes (carries closing entries)
            Conditions already proven under 16 are not probed as such; the controls above re-observe each category.
  check     judge the re-exports plus the Human's import-screen results; prints the gate and, only if 64 is verified,
            the registry block to add (a reviewed code change).
  forecast  DRY RUN: READY under 64 with the round's actual result. Never READY.

Counting rule registered after the round: PHYSICAL_ROWS unless both SIDE files round-tripped (then LINES_PER_SIDE).
Counting physical rows is safe whenever B64 round-trips: a voucher of at most 64 physical rows has at most 64 lines
per side. 控除不可 is never carried over (its tax-summary Evidence is setting specific).
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.adapters.output.jdl.scoped_evidence_registry import RowLimitScopeEvidence, ScopedCase
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application import scoped_evidence_composition as composition
from accounting_converter.application import voucher_split
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal import Side
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import generate_yayoi_gap_probes as gap
from accounting_converter.tools import generate_yayoi_split_probes as split_probes
from accounting_converter.tools import generate_yayoi_subaccount_tax_probes as subtax
from accounting_converter.tools import yayoi_closing_probe_check as closing
from accounting_converter.tools.mf_full_e2e_compare import _groups, _rows
from accounting_converter.tools.yayoi_probe_check import manifest_path_for

FROM_LIMIT = scoped.SCOPE_VOUCHER_ROW_LIMIT
TARGET_LIMIT = 64
NO, NONE = "NO", "-"
D = Decimal
USED_PROBE_DAYS = split_probes.USED_PROBE_DAYS | {"20260711", "20260718", "20260731"}
YEAR_END_DAY = "20260731"
LIMIT_EVIDENCE_ID = f"EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-{TARGET_LIMIT}-001"
CARRY_EVIDENCE_ID = {c: f"EVID-YAYOI-JDL-35-5-BUDDIES-VOUCHER-ROW-LIMIT-{TARGET_LIMIT}-CARRY-{c}-001"
                     for c in ("LAYOUT", "TAX_RELATION", "SUBACCOUNT", "CLOSING")}
CASE_ROWS = f"L64-ROWS{TARGET_LIMIT}"
CASE_INV, CASE_REL = "L64-INV", "L64-REL"
CASE_SIDE_D, CASE_SIDE_C = "L64-SIDE-D", "L64-SIDE-C"
CASE_OVER_D, CASE_OVER_C = "L64-OVER-D", "L64-OVER-C"
SIDE_JOURNAL = "7265"  # the company's journal with exactly 64 debit lines on 65 rows
LAYOUT_FILE_SIZE = 5
REJECTION_HINT = "伝票内の仕訳数が多すぎます"
FALLBACK_DIR, CLOSING_DIR = "fallback", "closing"
GROUP_FILES = ("R64A", "R64SUB")  # + R64L1.. (computed)
BOUNDARY_FILES = ("R64SIDED", "R64SIDEC", "R64OVERD", "R64OVERC")
# Explicit-tax rounding relations registered under 16 (side, cell, account, amount, written, relation): each on an
# account where it round-tripped, so REL re-observes every relation type the 16-row Evidence authorizes.
REL_LINES = (
    ("CREDIT", "S10", "6121", "1000", "91", "COMPANY"),
    ("CREDIT", "S10", "6121", "1000", "90", "FLOOR"),
    ("DEBIT", "P10", "8471", "1000", "91", "COMPANY"),
    ("DEBIT", "S10", "6131", "1000", "90", "FLOOR"),
    ("DEBIT", "R8", "8471", "1000", "74", "HALF_LOW"),
    ("DEBIT", "R8", "8471", "1200", "89", "HALF_HIGH"),
    ("DEBIT", "T80", "8471", "1050", "76", "HALF_LOW"),
    ("DEBIT", "T80", "8471", "1000", "73", "HALF_HIGH"),
    ("DEBIT", "T80", "8471", "1000", "72", "FLOOR_HIGH"),
)
SUB_TARGETS = (("1551", "0169"), ("3141", "0137"), ("1551", None), ("3141", None))  # None = the lowest code


# ---------------------------------------------------------------- loading
def load(source: Path, company_store: Path, company_id: str):
    resolved = CompanySettingStore(company_store / "companies", ConversionProfileStore(company_store / "profiles")).resolve(company_id)
    if resolved.context is None:
        raise gen.CampaignError("the company's JDL setting is not confirmed")
    return detect_format(source).diagnose(source).entries, resolved.profile, resolved.context


def same_settings_as_verified_scope(context) -> bool:
    """Every scope condition except the row limit matches (the setting the round would run with)."""
    return scoped.scope_state(replace(context, voucher_row_limit=FROM_LIMIT)) is scoped.ScopeState.IN_SCOPE


def side_counts(entry) -> tuple[int, int, int]:
    """(debit lines, credit lines, CSV physical rows)."""
    rows = journal_physical_rows(entry) or ()
    return (sum(1 for l in entry.lines if l.side is Side.DEBIT), sum(1 for l in entry.lines if l.side is Side.CREDIT),
            len(rows))


# ---------------------------------------------------------------- what the journals need
def parts_under(entry, limit: int):
    """The vouchers this journal would be written as under `limit` counted by physical rows (approvable split only)."""
    rows = journal_physical_rows(entry)
    if rows is None:
        return ()
    if len(rows) <= limit:
        return (entry,)
    plan = voucher_split.plan_split(entry, limit)
    return voucher_split.split_entry(entry, plan) if plan is not None else ()


def needed_layouts(entries, limit: int = TARGET_LIMIT) -> tuple[dict, dict]:
    """layout -> {"cells", "journals"} for vouchers no 16-row Evidence covers (physical-row counting); skipped ids."""
    by_layout: dict[str, dict] = {}
    kinds: dict[str, set] = defaultdict(set)
    skipped: dict[str, str] = {}
    for entry in entries:
        rows = journal_physical_rows(entry)
        if rows is None or len(rows) <= FROM_LIMIT:
            continue
        parts = parts_under(entry, limit)
        if not parts:
            skipped[entry.id] = voucher_split.ineligible_reason(entry, limit) or "NO_PARTS"
            continue
        for part in parts:
            record = split_probes.signature(part)
            if record is None:
                skipped[entry.id] = "CLOSING_OR_UNKNOWN_TAX_CELL"
                continue
            cells, layout = record
            if not scoped.placement_gaps(layout, cells, FROM_LIMIT):
                continue  # a part of up to 16 rows the registered Evidence already covers (carry-over)
            mine = {(side, cell) for row in cells for side, cell in (("DEBIT", row[0]), ("CREDIT", row[1]))
                    if cell not in {NO, NONE}}
            kinds[layout] |= mine
            item = by_layout.setdefault(layout, {"cells": cells, "kinds": mine, "journals": set()})
            if mine > item["kinds"]:
                item["cells"], item["kinds"] = cells, mine
            item["journals"].add(entry.id)
    for layout, item in by_layout.items():
        if item["kinds"] != kinds[layout]:
            raise gen.CampaignError(f"{layout}: no single journal carries every tax cell the layout needs")
    return by_layout, skipped


def inv_signature() -> tuple[tuple[str, str], ...]:
    """Every registered row pair once (so every registered (side, cell) too), in a stable order: >16 rows."""
    pairs = sorted(scoped.views(FROM_LIMIT)[2])
    if len(pairs) <= FROM_LIMIT:
        raise gen.CampaignError("the carry-over case must be longer than 16 rows")
    return tuple(pairs)


def signature_layout(signature) -> str:
    """The B/D/C run layout of a (debit cell, credit cell) signature ("-" = no line)."""
    runs: list[list] = []
    for debit, credit in signature:
        kind = "B" if debit != NONE and credit != NONE else "D" if debit != NONE else "C"
        if runs and runs[-1][0] == kind:
            runs[-1][1] += 1
        else:
            runs.append([kind, 1])
    return "".join(f"{kind}{count}" for kind, count in runs)


def _case(case_id, signature, accounts, group, purpose, journals, expected=None):
    case = gap.structural_case(case_id, signature, accounts, group, purpose, journals)
    case.proves = gap.conditions_of(signature, signature_layout(signature))
    if expected:
        case.expected = expected
    return case


def rel_case(accounts) -> gap.Case:
    """Every explicit-tax rounding relation, one per row with a 税なし counterpart, padded to 17 rows."""
    rows = []
    for side, cell, account, amount, tax, _relation in REL_LINES:
        taxed = gap.Line(cell, account, D(amount), D(tax))
        other = gap.Line(NO, accounts["cash"] if side == "CREDIT" else accounts["no_tax_credit"], D(amount))
        rows.append((other, taxed) if side == "CREDIT" else (taxed, other))
    while len(rows) <= FROM_LIMIT:
        rows.append((gap.Line(NO, accounts["cash"], gap.UNIT), gap.Line(NO, accounts["no_tax_credit"], gap.UNIT)))
    for (side, cell, account, amount, tax, relation), row in zip(REL_LINES, rows):
        line = row[1] if side == "CREDIT" else row[0]
        if scoped.relation_of(cell, line.amount, line.explicit_tax) != relation:
            raise gen.CampaignError(f"REL: {cell} {amount}/{tax} is not {relation}")
    case = gap.Case(CASE_REL, "L64-CARRY", "64行設定でも、明示税額（会社の端数・切捨て・8%・80%の端数）が書いたとおり保持されるか"
                    "（16行Evidenceの税額の関係を引き継ぐ条件）", gap.KEEP, tuple(rows))
    case.proves = [f"CARRY:TAX_RELATION:{s}:{c}:{r}" for s, c, _a, _m, _t, r in REL_LINES]
    return case


def sub_cases(context, accounts, prefix: str = "L64") -> list:
    """One-row cases with a JDL subaccount code + name (the subaccounts the company's journals use)."""
    subs = defaultdict(dict)
    for item in context.subaccounts:
        subs[item.parent_account_code][item.output_code] = item.output_name
    cases = []
    for parent, code in SUB_TARGETS:
        codes = subs.get(parent) or {}
        code = code if code in codes else (min(codes) if code is None and codes else None)
        if code is None:
            raise gen.CampaignError(f"subaccount for {parent} not in the JDL master")
        case = subtax._sub_case(f"{prefix}-SUB-{parent}-{code}", parent, accounts,
                                f"64行設定で {parent} の補助 {code}（コード・名称）が保持されるか（補助の引き継ぎ条件）",
                                "再Exportで補助コード・名称が一致（数値補助の先頭0の正規化のみ）", (code, codes[code]),
                                [f"CARRY:SUBACCOUNT:{parent}"])
        cases.append(case)
    return cases


def plan_files(entries, context, accounts) -> list[dict]:
    """Ordered import files: {"name", "note", "cases": [(Case, journal ids)], "over": ids, "fallback": bool}."""
    layouts, _skipped = needed_layouts(entries)
    side_entry = next((e for e in entries if e.id.rsplit(":", 1)[-1] == SIDE_JOURNAL), None)
    side_signature = split_probes.signature(side_entry)[0] if side_entry is not None else None
    if side_signature is None or side_counts(side_entry)[:2] != (TARGET_LIMIT, 1):
        side_signature = ((NONE, NO),) + ((NO, NONE),) * TARGET_LIMIT
    files = [{
        "name": "R64A", "note": "64行設定：64行ちょうど・レイアウトと税セルの引き継ぎ（INV）・明示税額の引き継ぎ（REL）",
        "fallback": True, "over": frozenset(), "cases": [
            (gap.control_case("CTL-R64A", accounts), []),
            (_case(CASE_ROWS, ((NO, NO),) * TARGET_LIMIT, accounts, "L64-LIMIT",
                   f"上限ちょうど：物理{TARGET_LIMIT}行・借方{TARGET_LIMIT}明細・貸方{TARGET_LIMIT}明細（税なし）", 0), []),
            (_case(CASE_INV, inv_signature(), accounts, "L64-CARRY",
                   "64行設定でも、登録済みの全税セル・全行ペアが同じように往復するか（レイアウトの引き継ぎ条件）", 0), []),
            (rel_case(accounts), []),
        ]}, {
        "name": "R64SUB", "note": "64行設定：補助科目（コード・名称）の引き継ぎ", "fallback": True, "over": frozenset(),
        "cases": [(gap.control_case("CTL-R64SUB", accounts), []), *((c, []) for c in sub_cases(context, accounts))],
    }]
    ordered = sorted(layouts, key=lambda l: (len(layouts[l]["cells"]), l))
    for index in range(0, len(ordered), LAYOUT_FILE_SIZE):
        name = f"R64L{index // LAYOUT_FILE_SIZE + 1}"
        chunk = []
        for layout in ordered[index:index + LAYOUT_FILE_SIZE]:
            item = layouts[layout]
            has_np = any(cell == "NP" for row in item["cells"] for cell in row)
            purpose = (f"{layout}（物理{len(item['cells'])}行）の配置。64行設定で1伝票として取り込めるか"
                       + ("（非仕入を含む。控除不可の変換は税理士確認まで止める）" if has_np else ""))
            chunk.append((_case(f"L64-{layout}", item["cells"], accounts, "L64-LAYOUT", purpose, len(item["journals"])),
                          sorted(item["journals"])))
        files.append({"name": name, "note": f"64行設定：17〜64行の形（{len(chunk)}種類）", "fallback": True,
                      "over": frozenset(), "cases": [(gap.control_case(f"CTL-{name}", accounts), []), *chunk]})
    boundary = (
        ("R64SIDED", CASE_SIDE_D, side_signature, "L64-COUNT",
         f"物理{TARGET_LIMIT + 1}行・借方{TARGET_LIMIT}明細・貸方1明細（仕訳{SIDE_JOURNAL}の形）。JDLが片側の明細数を数えるなら取込",
         "取り込めて一致＝片側64明細まで可（物理行は数えない）／拒否＝物理行を数える。どちらも結果として記録",
         [f"yayoi-report:source.txt:{SIDE_JOURNAL}"]),
        ("R64SIDEC", CASE_SIDE_C, ((NO, NONE),) + ((NONE, NO),) * TARGET_LIMIT, "L64-COUNT",
         f"物理{TARGET_LIMIT + 1}行・借方1明細・貸方{TARGET_LIMIT}明細（税なし）。貸方側の同じ境界",
         "取り込めて一致＝片側64明細まで可／拒否＝物理行を数える", []),
        ("R64OVERD", CASE_OVER_D, ((NONE, NO),) + ((NO, NONE),) * (TARGET_LIMIT + 1), "L64-LIMIT",
         f"借方{TARGET_LIMIT + 1}明細・貸方1明細（物理{TARGET_LIMIT + 2}行、税なし）。借方の上限超過",
         f"取込で拒否される（{REJECTION_HINT}）。取り込めたら64行設定になっていないか上限が違う", []),
        ("R64OVERC", CASE_OVER_C, ((NO, NO),) + ((NONE, NO),) * TARGET_LIMIT, "L64-LIMIT",
         f"借方1明細・貸方{TARGET_LIMIT + 1}明細（物理{TARGET_LIMIT + 1}行、税なし）。貸方の上限超過",
         f"取込で拒否される（{REJECTION_HINT}）。取り込めたら64行設定になっていないか上限が違う", []),
    )
    for name, case_id, signature, group, purpose, expected, journals in boundary:
        files.append({"name": name, "note": purpose, "fallback": False, "over": frozenset({case_id}), "cases": [
            (gap.control_case(f"CTL-{name}", accounts), []),
            (_case(case_id, signature, accounts, group, purpose, len(journals), expected), journals)]})
    return files


def single_id(case_id: str) -> str:
    return "L64S-" + case_id.split("-", 1)[1]


def original_id(case_id: str) -> str:
    return "L64-" + case_id.split("-", 1)[1] if case_id.startswith("L64S-") else case_id


# ---------------------------------------------------------------- generate
def _common(company_id, context, probe_date):
    return {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "source_kind": "fully_synthetic_JDL_target_probe_with_company_structure",
        "round": "5: 振替伝票入力行数 64", "target": "JDL IBEX 出納帳 35.5", "company_setting_id": company_id,
        "scope_id": scoped.scope_id_for(TARGET_LIMIT),
        "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value, "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "voucher_row_limit": TARGET_LIMIT, "probe_date": probe_date,
        "registry_note": ("Registered only through `yayoi_row64_probe check` and a reviewed code change. PASS never "
                          "releases 控除不可 or a voucher split without the recorded approvals."),
        "must_verify_before_import": [
            "company_data_restored_from_the_existing_backup_and_a_fresh_backup_taken_first",
            "JDL 会社情報 振替伝票入力行数 = 64行以内 in the TEST COPY only (never the production company)",
            "probe_date_inside_the_fiscal_period_with_no_existing_journal",
            "tax_settings: 税抜・原則課税・一括比例配分, 端数 売上=切上げ / 仕入=四捨五入",
            "one file at a time in the documented order; a fallback file only if its group file was rejected",
        ],
    }


def _write(directory: Path, name: str, note: str, cases, day, probe_date, names, synthetic, writer_context, company_id,
           common, over=frozenset()):
    sub = [c for c in cases if isinstance(c, subtax.SubCase)]
    if sub:
        plain = [c if isinstance(c, subtax.SubCase) else subtax.SubCase(c) for c in cases]
        return subtax.write_file(name, note, plain, day, probe_date, names, synthetic, writer_context, company_id,
                                 directory, common)
    return gap.write_file(name, note, list(cases), day, probe_date, names, synthetic, writer_context, company_id,
                          directory, common, check_lengths=True, row_limit=TARGET_LIMIT, expected_over_limit=over)


def _as_single(case):
    if isinstance(case, subtax.SubCase):
        return subtax.SubCase(_as_single(case.case), case.overrides)
    return replace(case, case_id=single_id(case.case_id), proves=list(case.proves))


def generate(source: Path, company_store: Path, company_id: str, probe_date: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise gen.CampaignError("probe files contain the company's JDL master names; write them under data/private only")
    if probe_date in USED_PROBE_DAYS:
        raise gen.CampaignError("this day was used by an earlier probe; choose another")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise gen.CampaignError(f"{output_dir} is not empty; nothing is overwritten")
    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    entries, _profile, context = load(source, company_store, company_id)
    if not ev.context_is_verified(context) or not same_settings_as_verified_scope(context):
        raise gen.CampaignError("the company is not in the verified scope (税抜・原則・一括比例・端数) apart from the row limit")
    if any(entry.date == day for entry in entries):
        raise gen.CampaignError("the probe date has source journals; choose a day without any")
    accounts, names = gen._accounts(context)
    writer_context = replace(context, voucher_row_limit=None)  # rows only; no acceptance guard (that is what is probed)
    synthetic = gap.synthetic_profile(writer_context)
    common = _common(company_id, context, probe_date)
    files = plan_files(entries, context, accounts)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / FALLBACK_DIR).mkdir()
    manifests, fallbacks, journals = {}, {}, {}
    for spec in files:
        cases = [case for case, _ in spec["cases"]]
        manifests[spec["name"]] = _write(output_dir, spec["name"], spec["note"], cases, day, probe_date, names, synthetic,
                                         writer_context, company_id, common, spec["over"])
        journals.update({(c.case.case_id if isinstance(c, subtax.SubCase) else c.case_id): ids
                         for c, ids in spec["cases"] if ids})
        if spec["fallback"]:
            for case in cases[1:]:
                single = _as_single(case)
                case_id = single.case.case_id if isinstance(single, subtax.SubCase) else single.case_id
                name = f"F{case_id[5:]}"[:40]
                fallbacks[name] = {"for_file": spec["name"], **_write(
                    output_dir / FALLBACK_DIR, name, f"{spec['name']} が拒否された場合だけ取り込む（{case_id}）", [single],
                    day, probe_date, names, synthetic, writer_context, company_id, {**common, "fallback_for": spec["name"]})}
    closing_result = closing.generate_import(
        source, company_store, company_id, YEAR_END_DAY, output_dir / CLOSING_DIR,
        shapes=closing.CLOSING_SHAPES + closing.CLOSING_SHAPES_B1C2, row_limit=TARGET_LIMIT,
        label="64行設定の決算整理仕訳")
    template = {name: {"accepted_journals": None, "rejected": None, "message": ""} for name in manifests}
    template.update({name: {"accepted_journals": None, "rejected": None, "message": "", "fallback_for": m["for_file"]}
                     for name, m in fallbacks.items()})
    for name in ("CLOSING_CTL", "CLOSING_IMP"):
        template[name] = {"accepted_journals": None, "rejected": None, "message": "", "folder": CLOSING_DIR}
    (output_dir / f"import_results_{probe_date}.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    procedure = output_dir / f"JDL操作手順_第5回_64行_{probe_date}.md"
    procedure.write_text(procedure_text(probe_date, manifests, fallbacks, closing_result), encoding="utf-8")
    return {"files": manifests, "fallbacks": fallbacks, "closing": closing_result, "journals_needing_each_case": journals,
            "procedure": procedure.name}


def procedure_text(probe_date: str, manifests: dict, fallbacks: dict, closing_result: dict) -> str:
    day = f"{probe_date[:4]}-{probe_date[4:6]}-{probe_date[6:]}"
    year_end = f"{YEAR_END_DAY[:4]}-{YEAR_END_DAY[4:6]}-{YEAR_END_DAY[6:]}"
    lines = [
        f"# JDL操作手順 第5回：振替伝票入力行数 64行（Probe日 {day}）", "",
        "目的: 64行設定でCSV取込できる行数・形を確かめる。**本番のJDL会社・アプリの本番設定は変更しない。**", "",
        "## 準備", "",
        "1. 本番会社のバックアップを取る。バックアップから検証用の複製会社を作る。",
        "2. 複製会社の 会社情報 → 振替伝票入力行数 を **64行以内** にして保存する（複製だけ）。",
        "3. 税設定が 税抜・原則課税・一括比例配分、端数 売上=切上げ／仕入=四捨五入 のままか確認する。",
        f"4. {day} に仕訳が無いことを確認する。", "",
        f"## 取込（CSV入力・決算整理を含まない。この順に1ファイルずつ。結果は `import_results_{probe_date}.json` に記入）", "",
    ]
    for index, (name, manifest) in enumerate(manifests.items(), start=1):
        lines.append(f"{index}. `{manifest['probe_file']}`（{manifest['expected_logical_journals']}仕訳・"
                     f"{manifest['expected_physical_rows']}行）: {manifest['batch_note']}")
    lines += [
        "", "- 取り込めた仕訳数と、エラー表示の文言（例: 「伝票内の仕訳数が多すぎます」）をそのまま記入する。"
        "R64OVERD・R64OVERC は拒否が期待どおり。R64SIDED・R64SIDEC はどちらの結果でもよい（結果そのものが確認事項）。",
        "- **R64A・R64SUB・R64L1〜 のどれかが拒否されたら**、そのファイルの代わりに `fallback/` の対応ファイル"
        "（ファイル名の F の後ろがケース名）を1つずつ取り込む。拒否されなかったファイルの fallback は取り込まない。", "",
        "fallback の対応:", "",
    ]
    by_group = defaultdict(list)
    for name, manifest in fallbacks.items():
        by_group[manifest["for_file"]].append(manifest["probe_file"])
    for group, names_ in by_group.items():
        lines.append(f"- {group}: " + "、".join(f"`{n}`" for n in names_))
    lines += [
        "", f"## 決算整理（CSV入力で「決算整理を含む」を選ぶ）", "",
        f"{len(manifests) + 1}. `closing/{closing_result['control']}`（通常仕訳の対照）",
        f"{len(manifests) + 2}. `closing/{closing_result['closing']}`（決算整理仕訳 {len(closing_result['closing_cases'])}件、日付 {closing_result['closing_date']}）", "",
        "## 再Export（3回）", "",
        f"- {day} の1日（決算整理を含まない）→ `JDL_再Export_{probe_date}.csv`",
        f"- {year_end}（決算整理を含む）→ `closing/JDL_取込後_決算あり_{YEAR_END_DAY}.csv`",
        f"- {year_end}（決算整理を含まない）→ `closing/JDL_取込後_決算なし_{YEAR_END_DAY}.csv`",
        "- 複製会社は確認後に削除してよい（本番には何も取り込まない）。", "",
        "## 判定（開発側）", "",
        "```", "PYTHONPATH=src python3 -m accounting_converter.tools.yayoi_row64_probe check \\",
        f"  --probe-dir <このフォルダ> --reexport <このフォルダ>/JDL_再Export_{probe_date}.csv \\",
        f"  --import-results <このフォルダ>/import_results_{probe_date}.json \\",
        f"  --closing-with <このフォルダ>/closing/JDL_取込後_決算あり_{YEAR_END_DAY}.csv \\",
        f"  --closing-without <このフォルダ>/closing/JDL_取込後_決算なし_{YEAR_END_DAY}.csv", "```", "",
        "64行が有効になる条件: 取り込んだファイルの対照がすべてPASS・L64-ROWS64 PASS・L64-OVER-D と L64-OVER-C がどちらも拒否"
        "（文言を記録）・重複0・説明できない仕訳0。数え方は L64-SIDE-D と L64-SIDE-C がどちらも取り込めて一致したときだけ"
        "「片側の明細数」、それ以外は「物理行」（安全側）。", "",
        "16行Evidenceの引き継ぎ: レイアウト・税セル＝INV、明示税額＝REL、補助＝R64SUB（4件すべて）、決算整理＝closing の判定が"
        "PASSしたものだけ。控除不可は引き継がない（64行では止めたまま）。", "",
        "合格しても、本番会社を64行にするか・アプリの振替伝票入力行数を64にするかは事務所の判断です。"
        "アプリの行数を変えると、記録済みの伝票分割の承認と控除不可の承認は無効になり、記録し直しが必要です。", "",
        "同じ複製で、中間決算（仕訳3605）の画面調査（`../interim_closing_probe_20261108/JDL操作手順_中間決算_20260131.md`）も"
        "行えます。64行の確認とは独立です。", "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- check
def _rejected(results: dict, name: str) -> bool:
    item = results.get(name) or {}
    return bool((item.get("message") or "").strip()) or item.get("rejected") is True


def check(probe_dir: Path, reexport: Path, import_results: dict,
          closing_with: Path | None = None, closing_without: Path | None = None) -> dict:
    from accounting_converter.tools.build_scoped_evidence_registry import case_record, gap_evidence_id
    from accounting_converter.tools.yayoi_gap_probe_check import check_round

    with tempfile.TemporaryDirectory() as directory:
        merged = Path(directory)
        for folder in (probe_dir, probe_dir / FALLBACK_DIR):
            for path in folder.glob("YAYOI_GAP_*_NOT_FOR_PRODUCTION.csv*"):
                shutil.copy2(path, merged / path.name)
        report = check_round(merged, reexport, import_counts=import_results)
        groups_by_file = {name: _groups(_rows(merged / name)) for name in report["files"]}
        manifests = {name: json.loads(manifest_path_for(merged / name).read_text(encoding="utf-8")) for name in report["files"]}
    raw = {case: verdict for f in report["files"].values() for case, verdict in f["verdicts"].items()}
    batches = {f["batch"]: name for name, f in report["files"].items()}
    missing = [n for n in (*GROUP_FILES, *BOUNDARY_FILES) if n not in batches]
    if missing:
        raise SystemExit(f"Probe files of this round not found in the directory: {missing}")
    verdicts: dict[str, str] = {}
    for case, verdict in raw.items():  # a case passes in its group file or in its fallback file
        key = original_id(case)
        if verdicts.get(key) != "PASS" and (verdict == "PASS" or verdicts.get(key, "MISSING") == "MISSING"):
            verdicts[key] = verdict
    passed = lambda case: verdicts.get(case) == "PASS"  # noqa: E731
    over_rejected = {c: verdicts.get(c) == "MISSING" and _rejected(import_results, f) for c, f in
                     ((CASE_OVER_D, "R64OVERD"), (CASE_OVER_C, "R64OVERC"))}
    controls = {c: v for c, v in raw.items() if c.startswith("CTL-")}
    gate = {
        "round_valid": report["round_valid"],
        "a_control_passed": any(v == "PASS" for v in controls.values()),
        f"{CASE_ROWS}_pass": passed(CASE_ROWS),
        f"{CASE_OVER_D}_rejected_with_message": over_rejected[CASE_OVER_D],
        f"{CASE_OVER_C}_rejected_with_message": over_rejected[CASE_OVER_C],
    }
    verified = all(gate.values())
    side = (verdicts.get(CASE_SIDE_D), verdicts.get(CASE_SIDE_C))
    counts = "LINES_PER_SIDE" if side == ("PASS", "PASS") else "PHYSICAL_ROWS"
    closing_judged = (closing.judge_import(probe_dir / CLOSING_DIR, closing_with, closing_without)
                      if closing_with and closing_without else None)
    sub_ids = [c for c in verdicts if c.startswith("L64-SUB-")]
    carried = {
        "LAYOUT": passed(CASE_INV),
        "TAX_RELATION": passed(CASE_REL),
        "SUBACCOUNT": bool(sub_ids) and all(passed(c) for c in sub_ids),
        "CLOSING": bool(closing_judged) and closing_judged.get("result") == "CLOSING_IMPORT_PRESERVED",
    }
    result = {
        "gate": gate, "row_limit_64_verified": verified, "counts": counts,
        "side_cases": {CASE_SIDE_D: side[0], CASE_SIDE_C: side[1]},
        "carried": carried, "closing": closing_judged, "verdicts": verdicts,
        "round": {k: report[k] for k in (
            "reexport_journals", "reexport_rows", "expected_journals", "expected_rows", "verdict_totals",
            "duplicate_identifiers", "extra_unexplained_reexport_journals", "files_with_nothing_reexported",
            "controls_pass_in_imported_files")},
        "not_judged": sorted(c for c, v in verdicts.items() if v == "MISSING" and c not in {CASE_OVER_D, CASE_OVER_C}
                             and not c.startswith("CTL-")
                             and not (counts == "PHYSICAL_ROWS" and c in {CASE_SIDE_D, CASE_SIDE_C})),
        "failed": {c: v for c, v in verdicts.items() if v not in {"PASS", "MISSING"}},
    }
    if not verified:
        result["registry"] = None
        result["note"] = "64行は未確認のまま。registryへ何も追加しない（会社を64にしてもBLOCK）"
        return result
    registrable = {CASE_ROWS, CASE_INV, CASE_REL}
    if counts == "LINES_PER_SIDE":
        registrable |= {CASE_SIDE_D, CASE_SIDE_C}
    records, seen = [], set()
    for name, manifest in manifests.items():
        for case in manifest["cases"]:
            key = original_id(case["case"])
            if key in seen or raw.get(case["case"]) != "PASS":
                continue
            if not (key in registrable or case["group"] == "L64-LAYOUT"):
                continue
            record = case_record(key, gap_evidence_id(key), groups_by_file[name][case["journal_index"]])
            records.append(record)
            seen.add(key)
    result["registry_records"] = records
    result["registry"] = render_registry_block(records, report, counts, carried)
    return result


def render_registry_block(records: list[dict], report: dict, counts: str = "PHYSICAL_ROWS",
                          carried: dict | None = None) -> str:
    carried_items = tuple((c, CARRY_EVIDENCE_ID[c]) for c, ok in (carried or {}).items() if ok)
    lines = [
        f"# Round 5 (振替伝票入力行数 {TARGET_LIMIT}): gate PASS ({CASE_ROWS} PASS; {CASE_OVER_D} / {CASE_OVER_C} rejected),",
        f"# counts {counts}, carried {[c for c, _ in carried_items]}. Re-export journals {report['reexport_journals']} "
        f"/ rows {report['reexport_rows']}.",
        "SCOPED_CASES += (",
    ]
    for record in records:
        lines.append(
            f"    ScopedCase({record['case_id']!r}, {record['evidence_id']!r}, {record['layout']!r},\n"
            f"        {record['rows']!r},\n"
            f"        {record['taxed']!r}, row_limit_scope={TARGET_LIMIT}),")
    lines += [")", f"ROW_LIMIT_SCOPES[{TARGET_LIMIT}] = RowLimitScopeEvidence(\n"
                   f"    {TARGET_LIMIT}, {LIMIT_EVIDENCE_ID!r}, counts={counts!r},\n    carried={carried_items!r})"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- forecast / analyze
ALL_CARRIED = ("LAYOUT", "TAX_RELATION", "SUBACCOUNT", "CLOSING")


@contextmanager
def assumed_round(records: list[dict], limit: int = TARGET_LIMIT, counts: str = "PHYSICAL_ROWS",
                  carried=ALL_CARRIED):
    """DRY RUN ONLY: behave as if these cases and the row-limit scope were registered; restored on exit."""
    old_cases, old_scopes = scoped.SCOPED_CASES, scoped.ROW_LIMIT_SCOPES
    scoped.SCOPED_CASES = old_cases + tuple(
        ScopedCase(r["case_id"], "FORECAST:" + r["evidence_id"], r["layout"], tuple(r["rows"]), tuple(r["taxed"]),
                   row_limit_scope=limit) for r in records)
    scoped.ROW_LIMIT_SCOPES = {**old_scopes, limit: RowLimitScopeEvidence(
        limit, "FORECAST:LIMIT", counts=counts, carried=tuple((c, f"FORECAST:CARRY-{c}") for c in carried))}
    scoped.reset_views()
    composition.reset_capabilities()
    try:
        yield
    finally:
        scoped.SCOPED_CASES, scoped.ROW_LIMIT_SCOPES = old_cases, old_scopes
        scoped.reset_views()
        composition.reset_capabilities()


def planned_records(entries, context, include_side: bool = False) -> list[dict]:
    """The registry records the planned cases would give if every one of them round-tripped unchanged."""
    from accounting_converter.tools.build_scoped_evidence_registry import case_record, gap_evidence_id

    accounts, names = gen._accounts(context)
    writer_context = replace(context, voucher_row_limit=None)
    synthetic = gap.synthetic_profile(writer_context)
    wanted = {CASE_ROWS, CASE_INV, CASE_REL} | ({CASE_SIDE_D, CASE_SIDE_C} if include_side else set())
    cases = [case for spec in plan_files(entries, context, accounts) for case, _ in spec["cases"]
             if not isinstance(case, subtax.SubCase) and (case.case_id in wanted or case.group == "L64-LAYOUT")]
    day = date(2000, 1, 1)
    built = [gap.build_entry(case, i, day, names, synthetic, writer_context) for i, case in enumerate(cases)]
    per_case = gap.serialize_case_rows(built, writer_context, cases)
    return [case_record(case.case_id, gap_evidence_id(case.case_id), [list(r) for r in rows])
            for case, rows in zip(cases, per_case, strict=True)]


def _short(journal_id: str) -> str:
    return journal_id.rsplit(":", 1)[-1]


def _outcome(found) -> str:
    found = sorted(found)
    return "READY" if not found else "SPLIT_APPROVAL_ONLY" if found == [voucher_split.APPROVAL_BLOCKER] else "BLOCKED"


def analyze(source: Path, company_store: Path, company_id: str, actual: dict | None = None) -> dict:
    """actual: a `check` result; None = assume every planned case passes (both counting rules are shown)."""
    entries, profile, context = load(source, company_store, company_id)
    workflow = YayoiJournalReportJdlWorkflow()

    def blockers(ctx):
        return workflow.assess(source, profile, ctx).journal_blockers

    now = blockers(context)
    ctx64 = replace(context, voucher_row_limit=TARGET_LIMIT)
    today64 = blockers(ctx64)
    scenarios = {}
    if actual is None:
        for counts in ("PHYSICAL_ROWS", "LINES_PER_SIDE"):
            with assumed_round(planned_records(entries, context, counts == "LINES_PER_SIDE"), counts=counts):
                scenarios[counts] = blockers(ctx64)
    else:
        carried = tuple(c for c, ok in actual["carried"].items() if ok)
        with assumed_round(actual["registry_records"], counts=actual["counts"], carried=carried):
            scenarios[actual["counts"]] = blockers(ctx64)
    journals = []
    for entry in entries:
        rows = journal_physical_rows(entry)
        if rows is None or len(rows) <= FROM_LIMIT:
            continue
        debit, credit, physical = side_counts(entry)
        journals.append({
            "journal": _short(entry.id), "debit_lines": debit, "credit_lines": credit, "physical_rows": physical,
            "layout": scoped.layout_of(rows),
            "fits_64_physical_rows": physical <= TARGET_LIMIT,
            "fits_64_lines_each_side": debit <= TARGET_LIMIT and credit <= TARGET_LIMIT,
            "split_rule_16": voucher_split.ineligible_reason(entry, FROM_LIMIT) or "ELIGIBLE",
            "split_rule_64_physical": voucher_split.ineligible_reason(entry, TARGET_LIMIT) or "ELIGIBLE",
            "blockers_now_16": sorted(now[entry.id]),
            "blockers_64_today_unverified": sorted(today64[entry.id]),
            **{f"blockers_64_{c}": sorted(found[entry.id]) for c, found in scenarios.items()},
            **{f"outcome_64_{c}": _outcome(found[entry.id]) for c, found in scenarios.items()},
        })
    ready = lambda found: sum(1 for b in found.values() if not b)  # noqa: E731
    return {
        "journals_total": len(entries), "journals_over_16_rows": len(journals),
        "ready_now_16": ready(now), "ready_64_today_unverified": ready(today64),
        **{f"ready_64_{c}": ready(found) for c, found in scenarios.items()},
        **{f"outcome_64_{c}": dict(Counter(j[f"outcome_64_{c}"] for j in journals)) for c in scenarios},
        "forecast_note": "DRY RUN: READY under 64 only after the real round and the registry change; not READY now",
        "journals": journals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("analyze", "generate", "forecast"):
        p = sub.add_parser(name)
        p.add_argument("--source", type=Path, required=True)
        p.add_argument("--company-store", type=Path, required=True)
        p.add_argument("--company-id", required=True)
        if name == "generate":
            p.add_argument("--probe-date", required=True, help="YYYYMMDD: a day with no journals in the JDL company")
            p.add_argument("--output-dir", type=Path, required=True)
        if name == "forecast":
            p.add_argument("--check-result", type=Path, required=True, help="JSON written by `check --out`")
        if name in {"analyze", "forecast"}:
            p.add_argument("--table", action="store_true", help="one line per journal instead of JSON")
    c = sub.add_parser("check")
    c.add_argument("--probe-dir", type=Path, required=True)
    c.add_argument("--reexport", type=Path, required=True)
    c.add_argument("--import-results", type=Path, required=True)
    c.add_argument("--closing-with", type=Path)
    c.add_argument("--closing-without", type=Path)
    c.add_argument("--out", type=Path, help="write the full result (data/private only)")
    args = parser.parse_args()
    if args.command == "generate":
        result = generate(args.source, args.company_store, args.company_id, args.probe_date, args.output_dir)
        print(json.dumps({
            "files": {n: {"file": m["probe_file"], "journals": m["expected_logical_journals"],
                          "rows": m["expected_physical_rows"], "cases": [c["case"] for c in m["cases"]]}
                      for n, m in result["files"].items()},
            "fallback_files": len(result["fallbacks"]), "closing": result["closing"],
            "procedure": result["procedure"],
        }, ensure_ascii=False, indent=1))
        return 0
    if args.command == "check":
        result = check(args.probe_dir, args.reexport, json.loads(args.import_results.read_text(encoding="utf-8")),
                       args.closing_with, args.closing_without)
        if args.out:
            if "data/private" not in args.out.resolve().as_posix():
                raise SystemExit("--out must be under data/private")
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k not in {"registry", "registry_records"}}, ensure_ascii=False, indent=1))
        if result.get("registry"):
            print(result["registry"])
        return 0
    actual = None
    if args.command == "forecast":
        actual = json.loads(args.check_result.read_text(encoding="utf-8"))
        if not actual.get("row_limit_64_verified"):
            raise SystemExit("the round did not verify 64 rows; nothing to forecast")
    result = analyze(args.source, args.company_store, args.company_id, actual)
    if args.table:
        print({k: v for k, v in result.items() if k != "journals"})
        strip = lambda found: ",".join(b.split(":", 1)[1] for b in found) or "-"  # noqa: E731
        keys = [k for k in result["journals"][0] if k.startswith("blockers_64_") and k != "blockers_64_today_unverified"]
        for j in result["journals"]:
            print(f"{j['journal']:>5} D{j['debit_lines']:>3} C{j['credit_lines']:>2} rows{j['physical_rows']:>3} "
                  f"phys64:{'Y' if j['fits_64_physical_rows'] else 'N'} side64:{'Y' if j['fits_64_lines_each_side'] else 'N'}"
                  f" | now {strip(j['blockers_now_16'])} | " + " | ".join(f"{k[12:]} {strip(j[k])}" for k in keys))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

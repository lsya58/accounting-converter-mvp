"""NOT_FOR_PRODUCTION JDL Probes for Yayoi「課対仕入10%｜区分記載｜控除不可」「課対仕入8%（軽）｜区分記載｜控除不可」.

Company A (Buddies): 課税・税抜・原則課税・一括比例配分. In Yayoi these lines are 内税 with tax 0: a taxable purchase
from a supplier without a qualified invoice, outside the 80% transitional measure, so no input tax credit at all.

What the JDL 課区・税区一覧表 (2023改正版, sha256 daf34063…) states, and what it does NOT:
  - p.2 (原則課税・一括比例配分): 課区 31 仕入 = 課税仕入, 34 非仕入 = 非課税仕入, 0 = 対象外 (blank in CSV).
    No 課区 or 税区 named 控除不可. No note about non-qualified suppliers on this page.
  - p.6 (簡易課税 only): 34 非仕入 "税抜経理処理方式の場合は「免税事業者等からの課税仕入れに係る経過措置」の
    適用を受けない免税事業者等からの課税仕入も含みます". This is a candidate for 原則課税, NOT a fact for it.
  - p.7: 税区 CSV literals 10% / 軽減8% / 10%免80 / 軽減8%免80 / (免70); no 0% and no 控除不可 税区.

Every candidate is one synthetic 1-row journal (debit 8471 / credit 現金 1111) written raw in the four tax columns.
Controls go through the production row builder with writings that already round-tripped (課税仕入10% / 軽減8%).
No sales line anywhere: a sales line would move 課税売上割合 and blur the 控除対象仕入税額 comparison.

Files (import in this order, one at a time, read the tax summary after each; a rejected file never hides another):
  NONCREDIT_A    known writings only (expected to import): controls 10% / 軽減8%, 非仕入 (as 10% and 8% amounts),
                 対象外 (comparison only; 控除不可 is NOT 対象外)
  NONCREDIT_B10  非仕入 + 税区10% + 内税 + 税額0       (unknown: rejected / kept / rate dropped / tax recomputed)
  NONCREDIT_B8   非仕入 + 税区軽減8% + 内税 + 税額0    (same question for 8%)
  NONCREDIT_C10  仕入 + 税区10% + 内税 + 税額0         (negative comparison: stays a creditable 課税仕入?)
  NONCREDIT_C8   仕入 + 税区軽減8% + 内税 + 税額0      (same for 8%)
Each file starts with its own control (課税仕入10%, 11,000 / 1,000). Amounts differ per case so the tax summary
deltas can be attributed. Nothing here registers Evidence, changes a setting or makes anything READY.
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
OFFICIAL_PDF_SHA256 = "daf3406379935f5731667cafc8973f77793df52500fb10551254108f3f96c082"
EXPENSE = "8471"  # the expense account every purchase writing below already round-tripped on (P10 / R8 / T80)
# Debit tax columns of the 30-column import (0-based): 課区, 税区, 税入力方法, 消費税.
DEBIT_TAX_COLUMNS = (8, 9, 10, 12)
SHIIRE, HISHIIRE = "仕　入", "非仕入"

# Tax summary fields the Human reads in JDL before / after each file (see the procedure). Keys are stable;
# the label is what to look for on the screen. Amount fields are read as 税込 unless the sheet says 税抜.
SUMMARY_FIELDS = {
    "PUR10_AMOUNT": "課税仕入 10%（仕入れの対価の額）",
    "PUR10_TAX": "課税仕入 10% の消費税額",
    "PUR8_AMOUNT": "課税仕入 軽減8%（仕入れの対価の額）",
    "PUR8_TAX": "課税仕入 軽減8% の消費税額",
    "NONTAX_PURCHASE": "非課税仕入の金額（課区34）",
    "CREDITABLE_TAX": "控除対象仕入税額（一括比例配分方式の計算後）",
}


@dataclass
class NoncreditCase:
    case: gp.Case
    written: tuple[str, str, str, str] | None  # raw debit (課区, 税区, 入力, 消費税); None = production writing
    candidate: str  # CONTROL / CANDIDATE / COMPARISON / NEGATIVE
    hypothesis: str
    negation: str
    # Expected change of each summary field IF the writing means "taxable purchase, no credit at all" (Yayoi 控除不可),
    # and IF it means "an ordinary creditable taxable purchase". Controls have one expectation.
    if_noncredit: dict[str, int] = field(default_factory=dict)
    if_creditable: dict[str, int] = field(default_factory=dict)


def _line(cell: str, amount: int, tax: int | None = None) -> gp.Line:
    return gp.Line(cell, EXPENSE, D(amount), None if tax is None else D(tax))


def _control(case_id: str, accounts) -> NoncreditCase:
    amount, tax = 11000, 1000
    case = gp.one_row(case_id, "CONTROL", "既知の正常ケース（課税仕入10%・内税、8471、11,000円・税1,000円）。"
                      "失敗または消費税集計の増分が違う場合はテスト環境の異常としてその回を無効にする",
                      gp.KEEP, _line("P10", amount, tax), gp.Line("NO", accounts["cash"], D(amount)))
    effect = {"PUR10_AMOUNT": amount, "PUR10_TAX": tax}
    return NoncreditCase(case, None, "CONTROL", "既知の課税仕入10%", "取込拒否・差異・集計増分の不一致はテスト環境の異常",
                         effect, effect)


def _candidate(case_id, purpose, expected, amount, written, candidate, hypothesis, negation, rate, accounts):
    case = gp.one_row(case_id, candidate, purpose, expected, _line("NO", amount),
                      gp.Line("NO", accounts["cash"], D(amount)))
    net_tax = amount * rate // (100 + rate)
    key = "PUR10" if rate == 10 else "PUR8"
    nontax = amount if written[0] == HISHIIRE else 0
    return NoncreditCase(
        case, written, candidate, hypothesis, negation,
        if_noncredit={"NONTAX_PURCHASE": nontax},
        if_creditable={f"{key}_AMOUNT": amount, f"{key}_TAX": net_tax if written[3] != "0" else 0},
    )


def files(accounts) -> dict[str, tuple[str, list[NoncreditCase]]]:
    a = [
        _control("NC-A-CTL-P10", accounts),
        NoncreditCase(
            gp.one_row("NC-A-CTL-R8", "CONTROL", "既知の正常ケース（課税仕入 軽減8%・内税、8471、10,800円・税800円）",
                       gp.KEEP, _line("R8", 10800, 800), gp.Line("NO", accounts["cash"], D(10800))),
            None, "CONTROL", "既知の課税仕入 軽減8%", "取込拒否・差異・集計増分の不一致はテスト環境の異常",
            {"PUR8_AMOUNT": 10800, "PUR8_TAX": 800}, {"PUR8_AMOUNT": 10800, "PUR8_TAX": 800}),
        _candidate("NC-A-NP-10", "控除不可10%の候補: 課区「非仕入」（税区・入力・税額は空欄。実機往復済みの書き方）。"
                   "PDF p.6（簡易課税）の注記を原則課税にも当てはめる候補", gp.KEEP, 22000,
                   (HISHIIRE, "", "", ""), "CANDIDATE",
                   "課税仕入から除かれ、仕入税額控除0（弥生の控除不可と申告上同じ）",
                   "課税仕入（10%・8%）の金額または税額が増える／控除対象仕入税額が増える", 10, accounts),
        _candidate("NC-A-NP-8", "控除不可 軽減8%の候補: 課区「非仕入」（税率は書けない）", gp.KEEP, 21600,
                   (HISHIIRE, "", "", ""), "CANDIDATE",
                   "同上（ただし10%と軽減8%の区別はJDLに残らない）",
                   "課税仕入の金額または税額が増える", 8, accounts),
        _candidate("NC-A-OOS-10", "比較用: 課区空欄（対象外）。控除不可を対象外と同一視しないための比較", gp.KEEP, 33000,
                   ("", "", "", ""), "COMPARISON",
                   "消費税計算と無関係（PDF p.2）。控除0にはなるが、課税仕入である事実は残らない",
                   "控除不可の表現として採用しない（集計結果に関係なく）", 10, accounts),
    ]
    b10 = [_control("NC-B10-CTL-P10", accounts), _candidate(
        "NC-B10-NP-R10", "控除不可10%の候補: 課区「非仕入」＋税区10%＋内税＋税額0（JDLが税区を保持するか）",
        "結果は未知。取込拒否／税区が空欄に戻る／税額が再計算される／書いたまま残る、のいずれかを観測", 44000,
        (HISHIIRE, "10%", "内税", "0"), "CANDIDATE",
        "非仕入のまま税率10%の記録が残り、控除0",
        "税額が0以外に再計算される／課税仕入に集計される", 10, accounts)]
    b8 = [_control("NC-B8-CTL-P10", accounts), _candidate(
        "NC-B8-NP-R8", "控除不可 軽減8%の候補: 課区「非仕入」＋税区軽減8%＋内税＋税額0",
        "結果は未知（B10と同じ観測）", 43200,
        (HISHIIRE, "軽減8%", "内税", "0"), "CANDIDATE",
        "非仕入のまま税率軽減8%の記録が残り、控除0",
        "税額が0以外に再計算される／課税仕入に集計される", 8, accounts)]
    c10 = [_control("NC-C10-CTL-P10", accounts), _candidate(
        "NC-C10-P10-T0", "否定・比較用: 課区「仕入」＋税区10%＋内税＋税額0（税額0なら控除されないか）",
        "結果は未知。税額0が保持されても、課税仕入に集計されるなら控除不可の表現にはしない", 55000,
        (SHIIRE, "10%", "内税", "0"), "NEGATIVE",
        "課税仕入の対価に含まれる（積上げなら税額0、割戻しなら控除が発生）",
        "課税仕入の金額が増える場合は控除不可の表現として採用しない", 10, accounts)]
    c8 = [_control("NC-C8-CTL-P10", accounts), _candidate(
        "NC-C8-R8-T0", "否定・比較用: 課区「仕入」＋税区軽減8%＋内税＋税額0",
        "結果は未知（C10と同じ観測）", 54000,
        (SHIIRE, "軽減8%", "内税", "0"), "NEGATIVE",
        "課税仕入の対価に含まれる",
        "課税仕入の金額が増える場合は控除不可の表現として採用しない", 8, accounts)]
    return {
        "NONCREDIT_A": ("既知の書き方だけ（取込成功の見込み）。非仕入・対象外の比較", a),
        "NONCREDIT_B10": ("非仕入＋税区10%（取込可否が未知のため単独）", b10),
        "NONCREDIT_B8": ("非仕入＋税区軽減8%（取込可否が未知のため単独）", b8),
        "NONCREDIT_C10": ("仕入＋税区10%＋税額0（否定・比較用、単独）", c10),
        "NONCREDIT_C8": ("仕入＋税区軽減8%＋税額0（否定・比較用、単独）", c8),
    }


def override_tax_columns(row: tuple[str, ...], written: tuple[str, str, str, str]) -> tuple[str, ...]:
    """Write the candidate's raw debit 課区 / 税区 / 税入力方法 / 消費税 into one serialized row."""
    values = list(row)
    for column, value in zip(DEBIT_TAX_COLUMNS, written, strict=True):
        values[column] = value
    return tuple(values)


def case_manifest(c: NoncreditCase, index: int) -> dict:
    return {
        "case": c.case.case_id, "journal_index": index, "physical_rows": 1,
        "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-BUDDIES-GAP-{c.case.case_id}-SYNTHETIC-ROUNDTRIP-001",
        "group": c.case.group, "candidate_kind": c.candidate, "purpose": c.case.purpose, "expected": c.case.expected,
        "proves": [], "shape": "1D1C/1rows", "description_under_test": False,
        "debit_account": EXPENSE, "amount": int(c.case.rows[0][0].amount),
        "written_debit_tax_columns": (
            dict(zip(("課区", "税区", "税入力方法", "消費税"), c.written)) if c.written else "PRODUCTION_WRITING"),
        "hypothesis": c.hypothesis, "negation": c.negation,
        "summary_delta_if_noncredit": c.if_noncredit, "summary_delta_if_creditable": c.if_creditable,
    }


def write_file(name, note, cases: list[NoncreditCase], day, probe_date, names, profile, context, output_dir, common):
    ids = [c.case.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise gen.CampaignError("duplicate case ids")
    entries = [gp.build_entry(c.case, i, day, names, profile, context) for i, c in enumerate(cases)]
    for entry in entries:
        if entry.debit_total() != entry.credit_total():
            raise gen.CampaignError(f"{entry.id} does not balance")
    chunks = gp.serialize_case_rows(entries, context, [c.case for c in cases])
    rows = []
    for case, chunk in zip(cases, chunks, strict=True):
        if len(chunk) != 1:
            raise gen.CampaignError(f"{case.case.case_id}: expected one physical row")
        rows.append(override_tax_columns(chunk[0], case.written) if case.written else chunk[0])
    gen.JDLOutputAdapter._validate_field_lengths(tuple(rows))
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((jdl_ibex_cashbook_official_journal_import_spec().column_names, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise gen.CampaignError("BOM is not allowed")
    path = output_dir / f"YAYOI_GAP_{name}_{probe_date}_NOT_FOR_PRODUCTION.csv"
    if path.exists() or manifest_path_for(path).exists():
        raise gen.CampaignError(f"{path.name} already exists; nothing is overwritten")
    path.write_bytes(payload)
    manifest = {
        **common, "batch": name, "batch_note": note, "probe_file": path.name,
        "probe_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_logical_journals": len(cases), "expected_physical_rows": len(rows),
        "cases": [case_manifest(c, i) for i, c in enumerate(cases)],
    }
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    result = check(path, path, manifest)  # the file must read back as itself under the strict comparator
    if any(r["verdict"] != "PASS" for r in result["cases"].values()):
        raise gen.CampaignError(f"{name}: self-comparison failed; manifest does not match the probe")
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
    if EXPENSE not in names:
        raise gen.CampaignError(f"{EXPENSE} is not in the company's JDL master")
    synthetic = gp.synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "target": "JDL IBEX 出納帳 35.5", "company_setting_id": company_id,
        "scope_id": SCOPE_ID, "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value, "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "voucher_row_limit": 16, "probe_date": probe_date, "official_pdf_sha256": OFFICIAL_PDF_SHA256,
        "source_tax_identities": ["課対仕入10%｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜控除不可"],
        "summary_fields": SUMMARY_FIELDS,
        "scoped_registry_allowed": False,
        "registry_exclusion_reason": ("控除不可Probe: CSV往復ではJDLの消費税計算上の意味が分からない。消費税集計と税理士の確認の後、"
                                      "別の設計（税区分の対応表）として扱う。構造・税額の会社範囲registryには入れない"),
        "equivalence_rule": ("CSV往復のPASSだけでは控除不可の再現とみなさない。消費税集計で課税仕入（金額・税額）と"
                             "控除対象仕入税額が増えないこと、かつ税理士が申告上同等と確認した候補だけを採用候補にする"),
    }
    return {name: write_file(name, note, cases, day, probe_date, names, synthetic, context, output_dir, common)
            for name, (note, cases) in files(accounts).items()}


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

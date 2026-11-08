"""Synthetic JDL Probe files for the Evidence still missing for one Yayoi company (round 3).

NOT_FOR_PRODUCTION. Fully synthetic: no customer amount, description or date.
Only the *structure* (physical rows and the JDL tax cell on each side) of the
journals that still lack Evidence is reused, taken from `yayoi_gap_probe_plan`,
which settles exactly the production gap set (it never re-probes what the
registered Evidence already proves).

Files (all Import into the same JDL test company, one re-export of the probe day):
  G1a/G1b/G1c  layouts and tax placements using tax cells already round-tripped (by row count)
  G2           layouts that carry a not-yet-placed 輸出売 / 軽減8% / 10%免80 cell
  G3           explicit tax with a fraction on 軽減8% / 10%免80 (the 80% deduction mismatch)
  G4           摘要 boundaries expected to be accepted (half-width, mixed, CP932 bytes)
  G5           摘要 boundaries expected to be rejected (last: a rejection must not hide others)

Every file also holds one known-good control. Every case has its own ID in the
摘要 (rows: ID-Rn), its own purpose, expected result and the conditions it proves.
Nothing here registers Evidence, changes readiness, or touches saved settings.
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
from types import SimpleNamespace

from accounting_converter.adapters.output.jdl import JDL_OUTPUT_METADATA_KEY, JdlEvidenceProfile
from accounting_converter.adapters.output.jdl.scoped_evidence import SCOPE_ID
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import LINE_ROW_DESCRIPTION_KEY, LINE_ROW_KEY, ROW_ORDER_KEY
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_yayoi_evidence_campaign as gen
from accounting_converter.tools import yayoi_gap_probe_plan as gap_plan
from accounting_converter.tools.yayoi_probe_check import check, manifest_path_for

# 1485 = 27 x 11 x 5: 10%, 8/108 and the 80% of 10% are all whole yen.
UNIT = Decimal("1485")
LITERALS = {
    **gen.LITERALS,
    "XS": ("", "輸出売"),
    "R8": ("軽減8%", "仕　入"),
    "T80": ("10%免80", "仕　入"),
}
VOUCHER_LIMIT = 16


@dataclass(frozen=True)
class Line:
    tax: str
    account: str
    amount: Decimal
    explicit_tax: Decimal | None = None


@dataclass
class Case:
    case_id: str
    group: str
    purpose: str
    expected: str
    rows: tuple[tuple[Line | None, Line | None], ...]
    proves: list[str] = field(default_factory=list)
    journals_settled: int = 0
    description_override: str | None = None  # 摘要 under test (single-row cases only)

    @property
    def shape(self) -> tuple[int, int, int]:
        return (sum(d is not None for d, _ in self.rows), sum(c is not None for _, c in self.rows), len(self.rows))


KEEP = "再Exportで全列が一致（既知の正規化のみ）。税区分・税額・摘要が変化しない"


def explicit_tax(cell: str, amount: Decimal) -> Decimal | None:
    if cell in {"S10", "P10"}:
        return amount / 11
    if cell == "R8":
        return amount * 8 / 108
    if cell == "T80":
        return amount * 10 / 110 * Decimal("0.8")
    return None


def account_for(cell: str, side: str, accounts) -> str:
    table = {
        ("XS", "CREDIT"): "6121",  # only 6121 round-tripped as 輸出売
        ("R8", "DEBIT"): "8471", ("T80", "DEBIT"): "8471",  # only 8471 round-tripped
    }
    if (cell, side) in table:
        return table[(cell, side)]
    if cell == "XS" or cell in {"R8", "T80"}:
        raise gen.CampaignError(f"no verified account for {cell} on {side}")
    return gen._account_for(cell, side, accounts)


def structural_case(case_id: str, signature, accounts, group: str, purpose: str, journals: int) -> Case:
    debit_lines = sum(d != "-" for d, _ in signature)
    credit_lines = sum(c != "-" for _, c in signature)

    def spec(cell, side, amount):
        if cell == "-":
            return None
        return Line(cell, account_for(cell, side, accounts), amount, explicit_tax(cell, amount))

    # Equal 1,485 per line; the shorter side's last line takes the difference (a multiple of 1,485).
    extra_side = "CREDIT" if credit_lines < debit_lines else "DEBIT"
    extra = UNIT * abs(debit_lines - credit_lines)
    last = max(i for i, row in enumerate(signature) if row[0 if extra_side == "DEBIT" else 1] != "-") if extra else -1
    rows = []
    for index, (debit, credit) in enumerate(signature):
        rows.append((
            spec(debit, "DEBIT", UNIT + (extra if extra_side == "DEBIT" and index == last else 0)),
            spec(credit, "CREDIT", UNIT + (extra if extra_side == "CREDIT" and index == last else 0)),
        ))
    case = Case(case_id, group, purpose, KEEP, tuple(rows))
    case.journals_settled = journals
    return case


def one_row(case_id, group, purpose, expected, debit: Line, credit: Line, **kw) -> Case:
    return Case(case_id, group, purpose, expected, ((debit, credit),), **kw)


def control_case(case_id: str, accounts) -> Case:
    """Known-good (EXP-S-CEIL-style simple sales journal, 6121): a failure here means the test copy is not clean."""
    amount = UNIT
    return one_row(case_id, "CONTROL", "既知の正常ケース（課税売上10% 貸方6121、端数なし）。失敗ならテスト環境の異常",
                   KEEP, Line("NO", accounts["cash"], amount), Line("S10", "6121", amount, amount / 11))


def fraction_cases(accounts) -> list[Case]:
    """Fractional 80% deduction / reduced 8% tax: the written tax relates to the exact value in 3 distinct ways."""
    cases = []
    spec = (
        # (id, cell, amount, written tax, relation description)
        ("FR-R8-LOW", "R8", Decimal("1000"), Decimal("74"), "exact 74.07 → written 74 (fraction < .5: floor = half-up)"),
        ("FR-R8-HIGH-HALF", "R8", Decimal("1200"), Decimal("89"), "exact 88.89 → written 89 (fraction ≥ .5: half-up/ceil)"),
        ("FR-T80-LOW", "T80", Decimal("1050"), Decimal("76"), "exact 76.36 → written 76 (fraction < .5: floor = half-up)"),
        ("FR-T80-HIGH-HALF", "T80", Decimal("1000"), Decimal("73"), "exact 72.73 → written 73 (fraction ≥ .5: half-up/ceil)"),
        ("FR-T80-HIGH-FLOOR", "T80", Decimal("1000"), Decimal("72"), "exact 72.73 → written 72 (fraction ≥ .5 but floor ≠ half-up)"),
    )
    for case_id, cell, amount, written, note in spec:
        cases.append(one_row(
            case_id, "G3-FRACTION",
            f"{cell} の明示税額が小数を含む場合：{note}。JDLが明示税額を保持するか、再計算するかを判定",
            "税額がそのまま保持→PASS。別の値に変わる→FAIL（その税額表現は出せない）",
            Line(cell, "8471", amount, written), Line("NO", accounts["cash"], amount),
            proves=[f"EXPLICIT:DEBIT:{cell}:FRACTION:{note.split(' (')[0]}"]))
    return cases


# Description boundary probes. The text is synthetic ASCII / half-width katakana / full-width kana.
def description_cases(accounts) -> tuple[list[Case], list[Case]]:
    fw = "あ"  # 2 bytes in CP932
    kata = "ｱ"  # half-width katakana: 1 byte in CP932
    accept, reject = [], []

    def make(case_id, text, purpose, expected, bucket, amount):
        text_bytes = len(text.encode("cp932"))
        case = one_row(case_id, bucket[0], f"{purpose}（{len(text)}文字・CP932 {text_bytes}バイト）", expected,
                       Line("NO", accounts["cash"], Decimal(amount)), Line("NO", accounts["no_tax_credit"], Decimal(amount)),
                       proves=[f"DESCRIPTION:{len(text)}chars:{text_bytes}bytes"], description_override=text)
        bucket[1].append(case)

    ok = ("G4-DESC", accept)
    ng = ("G5-DESC", reject)
    expected_ok = "摘要がそのまま保持される→その長さ・文字種はCSV Importで受け付けられる。切り詰め・拒否→FAIL（制限は公式仕様と異なる）"
    expected_ng = "拒否または切り詰め→上限の位置が確定。そのまま保持→制限は想定より緩い（それでも本体は緩和しない）"
    # 摘要 begins with the case ID so the re-exported journal can be identified even when JDL changes it.
    # Full-width cases carry a full-width 7-character tag so the text is entirely full-width.
    make("DS-FW32", "ＤＳ－ＦＷ３２" + fw * 25, "全角32文字＝64バイト（公式仕様の上限ちょうど）", expected_ok, ok, 20001)
    make("DS-HW33", "DS-HW33" + "A" * 26, "半角英数33文字（32文字超・64バイト以内）", expected_ok, ok, 20002)
    make("DS-HW48", "DS-HW48" + "A" * 41, "半角英数48文字", expected_ok, ok, 20003)
    make("DS-HW64", "DS-HW64" + "A" * 57, "半角英数64文字（半角上限ちょうど）", expected_ok, ok, 20004)
    make("DS-KANA40", "DS-KN40" + kata * 33, "半角カナ40文字（CP932で1バイト/文字）", expected_ok, ok, 20005)
    make("DS-MIX64", "DS-MX64" + fw * 22 + "B" * 13, "全角22＋半角20＝64バイト（混在・上限ちょうど）", expected_ok, ok, 20006)
    # Characters that occur in the company's long descriptions: half-width space and symbols (CSV comma included).
    symbols = " -./@()#$,&*_+':"
    make("DS-SYM64", ("DS-SY64" + symbols * 4)[:64], "半角スペース・記号を含む半角64文字", expected_ok, ok, 20010)
    make("DS-MIXSYM", ("DS-MS64 " + fw * 10 + kata * 10 + " 12-34/56 (7).8@" + "C" * 30)[:52],
         "全角＋半角カナ＋半角数字・記号・スペースの混在（64バイト以内）", expected_ok, ok, 20011)
    make("DS-HW65", "DS-HW65" + "A" * 58, "半角英数65文字（64バイト超）", expected_ng, ng, 20007)
    make("DS-FW33", "ＤＳ－ＦＷ３３" + fw * 26, "全角33文字＝66バイト（64バイト超）", expected_ng, ng, 20008)
    make("DS-MIX65", "DS-MX65" + fw * 22 + "B" * 14, "全角22＋半角21＝65バイト（混在・64バイト超）", expected_ng, ng, 20009)
    return accept, reject


# ---------------------------------------------------------------- build
def synthetic_profile(context):
    digest = ev.tax_context_identity_sha256(context)
    return SimpleNamespace(tax_mappings={
        f"PROBE:{code}": MappingValue(f"PROBE:{code}", target, MappingStatus.USER_CONFIRMED,
                                      metadata={"jdl_tax_scope": scope, "jdl_tax_context_identity_sha256": digest})
        for code, (target, scope) in LITERALS.items()
    })


def build_entry(case: Case, index: int, day: date, names, profile, context) -> JournalEntry:
    reference = SourceReference("synthetic-gap-probe", index)
    source_lines, mapped_lines = [], []
    for row_number, row in enumerate(case.rows, start=1):
        marker = f"{case.case_id}-R{row_number}" if len(case.rows) > 1 else case.case_id
        for side, spec in ((Side.DEBIT, row[0]), (Side.CREDIT, row[1])):
            if spec is None:
                continue
            meta = {LINE_ROW_KEY: row_number, LINE_ROW_DESCRIPTION_KEY: marker}
            source_lines.append(JournalLine(side, f"SRC-{spec.account}", spec.amount, reference,
                                            tax_info=TaxInfo(category=f"PROBE:{spec.tax}", tax_amount=spec.explicit_tax),
                                            metadata=meta))
            mapped_lines.append(JournalLine(side, names[spec.account], spec.amount, reference, metadata=dict(meta)))
    source = JournalEntry(f"probe:{case.case_id}", reference, day, source_lines)
    mapped = JournalEntry(f"probe:{case.case_id}", reference, day, mapped_lines)
    literal = ev.apply_tax_literals(source, mapped, f"PENDING:{case.case_id}", profile=profile, context=context)
    markers = tuple({"row_number": n, "value": f"{case.case_id}-R{n}" if len(case.rows) > 1 else case.case_id}
                    for n in range(1, len(case.rows) + 1))
    return JournalEntry(
        literal.id, reference, day, literal.lines,
        description=case.case_id if len(case.rows) == 1 else None,
        metadata={JDL_OUTPUT_METADATA_KEY: JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL.value,
                  "moneyforward_descriptions": markers, ROW_ORDER_KEY: tuple(range(1, len(case.rows) + 1))},
    )


def serialize_case_rows(entries, context, cases):
    rows = list(gen.serialize(entries, context))
    # Apply the description under test after the production row builder (the length guard is what is being probed).
    cursor = 0
    result = []
    for case in cases:
        count = len(case.rows)
        chunk = rows[cursor: cursor + count]
        cursor += count
        if case.description_override is not None:
            chunk = [tuple(case.description_override if i == 23 else value for i, value in enumerate(r)) for r in chunk]
        result.append(chunk)
    return result


def write_file(name: str, note: str, cases: list[Case], day: date, probe_date: str, names, profile, context, company_id,
               output_dir: Path, common: dict, check_lengths: bool, row_limit: int = VOUCHER_LIMIT,
               expected_over_limit: frozenset[str] = frozenset()) -> dict:
    """Write one Probe file. A case longer than `row_limit` is refused unless it is named in
    `expected_over_limit` (a boundary case that exists to be rejected by JDL, in a file of its own)."""
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise gen.CampaignError("duplicate case ids")
    over = [c.case_id for c in cases if len(c.rows) > row_limit and c.case_id not in expected_over_limit]
    if over:
        raise gen.CampaignError(f"cases exceed the voucher row limit {row_limit}: {over}")
    entries = [build_entry(case, i, day, names, profile, context) for i, case in enumerate(cases)]
    for entry in entries:
        if entry.debit_total() != entry.credit_total():
            raise gen.CampaignError(f"{entry.id} does not balance")
    per_case = serialize_case_rows(entries, context, cases)
    rows = tuple(row for chunk in per_case for row in chunk)
    if check_lengths:
        gen.JDLOutputAdapter._validate_field_lengths(rows)
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    path = output_dir / f"YAYOI_GAP_{name}_{probe_date}_NOT_FOR_PRODUCTION.csv"
    if path.exists() or manifest_path_for(path).exists():
        raise gen.CampaignError(f"{path.name} already exists; nothing is overwritten")
    path.write_bytes(payload)
    manifest = {
        **common, "batch": name, "batch_note": note, "probe_file": path.name,
        "probe_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_logical_journals": len(cases), "expected_physical_rows": len(rows),
        "cases": [
            {"case": c.case_id, "journal_index": i, "physical_rows": len(c.rows),
             "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-{company_id.upper()}-GAP-{c.case_id}-SYNTHETIC-ROUNDTRIP-001",
             "group": c.group, "purpose": c.purpose, "expected": c.expected, "proves": c.proves,
             "journals_settled_if_pass": c.journals_settled, "shape": "%dD%dC/%drows" % c.shape,
             "description_under_test": c.description_override is not None}
            for i, c in enumerate(cases)
        ],
    }
    manifest_path_for(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not any(c.description_override for c in cases):
        result = check(path, path, manifest)
        if any(r["verdict"] != "PASS" for r in result["cases"].values()):
            raise gen.CampaignError(f"{name}: self-comparison failed; manifest does not match the probe")
    return manifest


def conditions_of(signature, layout) -> list[str]:
    return sorted("/".join(map(str, c)) for c in gap_plan.provided(signature, layout))


def generate(source: Path, company_store: Path, company_id: str, probe_date: str, output_dir: Path) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise gen.CampaignError("probe files contain the company's JDL master names; write them under data/private only")
    day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    entries, context = gap_plan.load(source, company_store, company_id, VOUCHER_LIMIT)
    if not ev.context_is_verified(context):
        raise gen.CampaignError("the company has no confirmed Tax Context in the verified 税抜・原則・一括比例 Context")
    if any(entry.date == day for entry in entries):
        raise gen.CampaignError("the probe date has source journals; choose a day without any")
    plan = gap_plan.plan(entries, context, VOUCHER_LIMIT)
    accounts, names = gen._accounts(context)
    signatures = plan["_signatures"]
    counts = {tuple(map(tuple, s["rows"])): s["journals_settled"] for s in plan["minimal_probe_signatures"]}
    new_cells = {"XS", "R8", "T80"}
    structural: list[Case] = []
    for number, signature in enumerate(signatures, start=1):
        layout = gap_plan.scoped.layout_of(_Rows(signature))
        has_new = any(cell in new_cells for row in signature for cell in row)
        group = "G2-NEWCELL" if has_new else "G1"
        case = structural_case(f"GP{number:03d}", signature, accounts, group,
                               f"{layout} の配置 {''.join(f'[{d}|{c}]' for d, c in signature)}", counts.get(signature, 0))
        case.proves = conditions_of(signature, layout)
        structural.append(case)
    g1 = [c for c in structural if c.group == "G1"]
    g2 = [c for c in structural if c.group == "G2-NEWCELL"]
    sized = lambda lo, hi: [c for c in g1 if lo <= len(c.rows) <= hi]  # noqa: E731
    files = [
        ("G1a", "既知の税区分だけの配置（1〜4行）", sized(1, 4)),
        ("G1b", "既知の税区分だけの配置（5〜8行）", sized(5, 8)),
        ("G1c", "既知の税区分だけの配置（9〜16行）", sized(9, VOUCHER_LIMIT)),
        ("G2", "輸出売・軽減8%・10%免80を含む配置", g2),
        ("G3", "軽減8%・10%免80の小数を含む明示税額", fraction_cases(accounts)),
    ]
    accept, reject = description_cases(accounts)
    files += [("G4", "摘要の長さ・文字種：受け付けられる見込みの境界", accept),
              ("G5", "摘要の長さ・文字種：拒否される見込みの境界（最後に取り込む）", reject)]
    synthetic = synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False, "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT", "source_kind": "fully_synthetic_JDL_target_probe_with_company_structure",
        "target": "JDL IBEX 出納帳 35.5", "company_setting_id": company_id, "scope_id": SCOPE_ID,
        "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value, "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "voucher_row_limit": VOUCHER_LIMIT, "probe_date": probe_date,
        "must_verify_before_import": [
            "company_data_restored_from_the_existing_backup_and_a_fresh_backup_taken_first",
            "probe_date_inside_the_fiscal_period_with_no_existing_journal",
            "tax_settings: 税抜・原則課税・一括比例配分, 端数 売上=切上げ / 仕入=四捨五入, 振替伝票入力行数=16",
            "accounts_in_the_probe_exist_in_the_master",
        ],
    }
    manifests = {}
    for name, note, cases in files:
        if not cases:
            continue
        control = control_case(f"CTL-{name}", accounts)
        all_cases = [control, *cases]
        manifests[name] = write_file(name, note, all_cases, day, probe_date, names, synthetic, context, company_id,
                                     output_dir, common, check_lengths=not name.startswith("G4") and not name.startswith("G5"))
    return {"files": manifests, "plan": {k: v for k, v in plan.items() if not k.startswith("_") and k != "minimal_probe_signatures"}}


class _Rows(list):
    """Physical rows of a cell signature, for scoped.layout_of."""

    def __init__(self, signature):
        super().__init__(SimpleNamespace(debit=None if d == "-" else 1, credit=None if c == "-" else 1) for d, c in signature)


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
        "plan": result["plan"],
        "files": {n: {"file": m["probe_file"], "sha256": m["probe_sha256"][:16], "journals": m["expected_logical_journals"],
                      "rows": m["expected_physical_rows"], "max_rows": max(c["physical_rows"] for c in m["cases"])}
                  for n, m in result["files"].items()},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

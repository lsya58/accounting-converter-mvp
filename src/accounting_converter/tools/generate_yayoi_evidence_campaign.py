"""One NOT_FOR_PRODUCTION JDL Evidence campaign batch for a Yayoi company.

Fully synthetic: no customer amounts, descriptions or dates. Only the
*structure* of the company's journals is reused (physical rows and which side
carries which JDL tax semantic), taken from `yayoi_evidence_campaign`. Accounts
are real codes from the company's own JDL master (needed for the target), with
fixed synthetic amounts (multiples of 1,100) and per-row case markers as
descriptions. Rows are produced by the production tax-literal and JDL preflight
code, so a PASS proves the serializer formal output will use.

Group A (this batch): JDL representations already known (課税売上10%,
課税仕入10%, 非課税, 対象外). Group B (輸出免税, 軽減8%, 経過措置80%, 控除不可,
決算仕訳) has no known JDL representation: the Human first enters examples on
the JDL screen and self-exports them; it is written as a separate sheet.

Every case has its own ID, purpose, expected result and the campaign keys it
settles. `yayoi_probe_check` judges each case on its own after one Import and
one re-export of the probe date. Nothing here confirms, registers or changes
READY; registering a PASS is a separate, explicit code change.

  generate --source S --company-store DIR --company-id ID --probe-date YYYYMMDD --output-dir data/private/...
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JDLOutputAdapter,
    JdlEvidenceProfile,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.yayoi_sources import detect_format
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
    journal_physical_rows,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import yayoi_evidence_campaign as campaign
from accounting_converter.tools.yayoi_probe_check import check, manifest_path_for

UNIT = Decimal("1100")
# Already passed on the real JDL test copy (2026-11-04, sales 10% on every
# credit row). Not probed again; registration is a later, explicit change.
EXISTING_SYNTHETIC_EVIDENCE = {
    "SHAPE:3D3C/3rows": "EVID-YAYOI-JDL-35-5-BUDDIES-3D3C-SALES10-SYNTHETIC-ROUNDTRIP-001",
    "MULTI_TAXED:3D3C": "EVID-YAYOI-JDL-35-5-BUDDIES-3D3C-SALES10-SYNTHETIC-ROUNDTRIP-001",
    "SHAPE:4D4C/4rows": "EVID-YAYOI-JDL-35-5-BUDDIES-4D4C-SALES10-SYNTHETIC-ROUNDTRIP-001",
    "MULTI_TAXED:4D4C": "EVID-YAYOI-JDL-35-5-BUDDIES-4D4C-SALES10-SYNTHETIC-ROUNDTRIP-001",
}
# Synthetic JDL tax mapping per short semantic code: (JDL 税区, JDL 課区).
LITERALS = {"S10": ("10%", "売　上"), "P10": ("10%", "仕　入"), "NP": ("", "非仕入"), "NS": ("", "非売上"), "NO": ("", "")}


class CampaignError(ValueError):
    pass


@dataclass(frozen=True)
class LineSpec:
    tax: str  # S10 / P10 / NP / NS / NO
    account: str  # JDL account code from the company's master
    amount: Decimal
    explicit_tax: Decimal | None = None


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    purpose: str
    settles: tuple[str, ...]
    expected: str
    rows: tuple[tuple[LineSpec | None, LineSpec | None], ...]

    @property
    def shape(self) -> tuple[int, int, int]:
        return (sum(d is not None for d, _ in self.rows), sum(c is not None for _, c in self.rows), len(self.rows))


KEEP = "再Exportで全列が一致（既知の正規化のみ）。税額を含めて変化しない"


def one(case_id, purpose, settles, debit: LineSpec, credit: LineSpec, expected=KEEP, group="A-TAX") -> Case:
    return Case(case_id, group, purpose, tuple(settles), expected, ((debit, credit),))


def fixed_cases(accounts) -> list[Case]:
    """Cases independent of the journal structure: rounding, sides, target accounts."""
    a = accounts
    s = lambda code, amount=UNIT, tax=None: LineSpec("S10", code, Decimal(amount), tax)  # noqa: E731
    p = lambda code, amount=UNIT, tax=None: LineSpec("P10", code, Decimal(amount), tax)  # noqa: E731
    no = lambda code, amount=UNIT: LineSpec("NO", code, Decimal(amount))  # noqa: E731
    cases = [
        # Explicit tax with this company's 端数処理 (売上 切上げ / 仕入 四捨五入).
        one("EXP-S-CEIL-6121", "課税売上10%（貸方6121）。明示税額＝会社の切上げ値（≠切捨て）。JDLが保持または会社設定で再計算すれば一致",
            ["EXPLICIT_TAX:EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED:CREDIT:JDL_SALES_10_EXTERNAL", "SALES10_ROUNDING_ACCOUNT"],
            no(a["cash"], 1105), s("6121", 1105, Decimal("101"))),
        one("EXP-S-FLOOR-6121", "課税売上10%（貸方6121）。明示税額＝切捨て値（≠会社の切上げ値）。JDLが明示税額を保持するか、会社設定で再計算するかを判定",
            ["EXPLICIT_TAX:EXPLICIT_TAX_KEEP_UNVERIFIED:CREDIT:JDL_SALES_10_EXTERNAL"],
            no(a["cash"], 1105), s("6121", 1105, Decimal("100")),
            expected="税額100のまま→JDLは明示税額を保持（PASS）。101に変わる→会社設定で再計算（FAIL＝該当仕訳はそのまま出せない）"),
        one("EXP-P-HALFUP", "課税仕入10%（借方）。明示税額＝会社の四捨五入値（≠切捨て）",
            ["EXPLICIT_TAX:EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED:DEBIT:JDL_PURCHASE_10_INTERNAL"],
            p(a["purchase"], 1106, Decimal("101")), no(a["cash"], 1106)),
        one("EXP-DS-FLOOR", "借方の課税売上10%（売上の戻り）。明示税額＝切捨て値（≠会社の切上げ値）",
            ["EXPLICIT_TAX:EXPLICIT_TAX_KEEP_UNVERIFIED:DEBIT:JDL_SALES_10_EXTERNAL"],
            s("6131", 1105, Decimal("100")), no(a["cash"], 1105),
            expected="税額100のまま→保持（PASS）。101に変わる→再計算（FAIL）"),
    ]
    for code in ("6131", "6181"):
        cases += [
            one(f"S10-{code}", f"課税売上10%を貸方{code}で（端数なし）。売上科目ごとのEvidence",
                ["SALES10_TARGET_ACCOUNT"], no(a["cash"]), s(code)),
            one(f"EXP-S-CEIL-{code}", f"課税売上10%を貸方{code}で、切上げの明示税額",
                ["SALES10_ROUNDING_ACCOUNT", "EXPLICIT_TAX:EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED:CREDIT:JDL_SALES_10_EXTERNAL"],
                no(a["cash"], 1105), s(code, 1105, Decimal("101"))),
        ]
    for code in ("6121", "6131", "6181"):
        cases.append(one(f"DS10-{code}", f"借方の課税売上10%（売上の戻り）を{code}で。3科目で科目に依らない扱いにする",
                         ["TAX_SIDE:DEBIT:JDL_SALES_10_EXTERNAL"], s(code), no(a["cash"])))
    for code in a["credit_purchase"]:
        cases.append(one(f"CP10-{code}", f"貸方の課税仕入10%（仕入の戻り）を{code}で。3科目で科目に依らない扱いにする",
                         ["TAX_SIDE:CREDIT:JDL_PURCHASE_10_INTERNAL"], no(a["cash"]), p(code)))
    for code in a["nonpur"]:
        cases.append(one(f"NP-{code}", f"借方の非課税仕入を{code}で。3科目目以降で科目に依らない扱いにする",
                         ["NONPUR_TARGET_ACCOUNT"], LineSpec("NP", code, UNIT), no(a["cash"])))
    cases.append(one("CNP-7121", "貸方の非課税仕入（7121）", ["TAX_SIDE:CREDIT:JDL_NON_TAXABLE_PURCHASE"],
                     no(a["cash"]), LineSpec("NP", "7121", UNIT)))
    return cases


def _account_for(tax: str, side: str, accounts) -> str:
    return {
        ("S10", "CREDIT"): "6121", ("S10", "DEBIT"): "6121",
        ("P10", "DEBIT"): accounts["purchase"], ("P10", "CREDIT"): accounts["purchase"],
        ("NP", "DEBIT"): accounts["nonpur"][0], ("NP", "CREDIT"): "7121",
        ("NS", "CREDIT"): "9111", ("NS", "DEBIT"): "9111",
        ("NO", "DEBIT"): accounts["cash"], ("NO", "CREDIT"): accounts["no_tax_credit"],
    }[(tax, side)]


def structural_case(case_id, purpose, settles, signature, accounts) -> Case:
    """Synthetic journal with this row signature.

    Every line is 1,100; the side with fewer lines gets the difference on its
    last line, so the journal balances and every amount stays a multiple of
    1,100 (10% tax is exact, no rounding question in a structural case).
    """
    debit_lines = sum(d != "-" for d, _ in signature)
    credit_lines = sum(c != "-" for _, c in signature)
    extra_side = "CREDIT" if credit_lines < debit_lines else "DEBIT"
    extra = UNIT * abs(debit_lines - credit_lines)
    last = max(index for index, row in enumerate(signature) if row[0 if extra_side == "DEBIT" else 1] != "-")

    def spec(tax, side, amount):
        if tax == "-":
            return None
        explicit = (amount / 11).quantize(Decimal("1")) if tax in {"S10", "P10"} else None
        return LineSpec(tax, _account_for(tax, side, accounts), amount, explicit)

    rows = []
    for index, (debit, credit) in enumerate(signature):
        debit_amount = UNIT + (extra if extra_side == "DEBIT" and index == last else 0)
        credit_amount = UNIT + (extra if extra_side == "CREDIT" and index == last else 0)
        rows.append((spec(debit, "DEBIT", debit_amount), spec(credit, "CREDIT", credit_amount)))
    return Case(case_id, "A-SHAPE", purpose, tuple(settles), KEEP, tuple(rows))


def structural_cases(analysis, accounts, min_journals: int) -> list[Case]:
    """One case per structural key with enough journals, using its most common real signature."""
    by_key: dict[str, Counter] = defaultdict(Counter)
    for journal in analysis:
        if journal["self_export_first"] or journal["signature"] is None:
            continue
        for key in journal["keys"]:
            if campaign.family(key) in {"SHAPE", "MULTI_TAXED", "TAXED_2D2C_LAYOUT"} and key not in EXISTING_SYNTHETIC_EVIDENCE:
                by_key[key][journal["signature"]] += 1
    cases, covered = [], set()
    for key, signatures in sorted(by_key.items(), key=lambda item: -sum(item[1].values())):
        if key in covered or sum(signatures.values()) < min_journals:
            continue
        signature, _ = signatures.most_common(1)[0]
        settles = {k for k, sigs in by_key.items() if signature in sigs}
        covered |= settles
        label = "".join(f"[{d}|{c}]" for d, c in signature)
        case_id = f"SH-{key.split(':', 1)[1].replace('/', '-').replace(',', '+').replace(':', '')}"[:24]
        cases.append(structural_case(case_id, f"{key} の代表構造 {label}（{sum(signatures.values())}仕訳）",
                                     sorted(settles), signature, accounts))
    return cases


def _rows_in(pattern: str) -> int:
    import re

    return sum(int(part[1:]) for part in re.findall(r"[BDC]\d+", pattern))


def boundary_cases(analysis, settled: set[str], accounts) -> list[Case]:
    """Largest remaining shape per structural class (only useful if a class rule is adopted).

    The rare shapes left after the main batch (each 1-2 journals) are not
    probed one by one. One boundary case per row-pattern class, the longest
    one, gives the Evidence a later class-level rule would need, in the same
    Import, without another JDL round.
    """
    best: dict[str, tuple[int, int, object, str]] = {}
    for journal in analysis:
        if journal["self_export_first"] or journal["signature"] is None:
            continue
        open_shape = {k for k in journal["keys"] - settled if campaign.family(k) in {"SHAPE", "MULTI_TAXED", "TAXED_2D2C_LAYOUT"}}
        if not open_shape:
            continue
        cls = campaign.pattern_class(journal["pattern"])
        taxed = sum(1 for d, c in journal["signature"] for x in (d, c) if x not in {"-", "NO"})
        candidate = (_rows_in(journal["pattern"]), taxed, journal["signature"], journal["pattern"])
        if cls not in best or candidate[:2] > best[cls][:2]:
            best[cls] = candidate
    cases = []
    for cls, (rows, _taxed, signature, pattern) in sorted(best.items()):
        tag = cls.split("(")[0].replace("_", "")[:10]
        cases.append(structural_case(
            f"BD-{tag}-{rows}R"[:24],
            f"境界ケース：{cls} の最長 {pattern}（{rows}行）。クラス単位の規則を採用する場合の根拠",
            [], signature, accounts))
    return [Case(case.case_id, "A-BOUNDARY", case.purpose, case.settles, case.expected, case.rows) for case in cases]


def _synthetic_profile(context):
    digest = ev.tax_context_identity_sha256(context)
    return SimpleNamespace(tax_mappings={
        f"PROBE:{code}": MappingValue(f"PROBE:{code}", target, MappingStatus.USER_CONFIRMED,
                                      metadata={"jdl_tax_scope": scope, "jdl_tax_context_identity_sha256": digest})
        for code, (target, scope) in LITERALS.items()
    })


def _entry(case: Case, index: int, probe_day: date, names, profile, context) -> JournalEntry:
    reference = SourceReference("synthetic-campaign", index)
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
    source = JournalEntry(f"probe:{case.case_id}", reference, probe_day, source_lines)
    mapped = JournalEntry(f"probe:{case.case_id}", reference, probe_day, mapped_lines)
    literal = ev.apply_tax_literals(source, mapped, f"PENDING:{case.case_id}", profile=profile, context=context)
    d, c, _rows = case.shape
    taxed = [line for line in source_lines if line.tax_info.category not in {"PROBE:NO"}]
    if (d, c) == (1, 1):
        semantic = {"S10": "JDL_SALES_10_EXTERNAL", "P10": "JDL_PURCHASE_10_INTERNAL",
                    "NP": "JDL_NON_TAXABLE_PURCHASE", "NS": "JDL_NON_TAXABLE_SALES"}
        tax = taxed[0].tax_info.category.split(":")[1] if taxed else None
        evidence_profile = ev.TAXED_IDENTITY_PROFILES_1D1C[semantic[tax]] if tax else JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111
    elif (d, c) == (2, 2) and taxed:
        evidence_profile = JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL
    else:
        evidence_profile = JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL
    markers = tuple({"row_number": n, "value": f"{case.case_id}-R{n}" if len(case.rows) > 1 else case.case_id}
                    for n in range(1, len(case.rows) + 1))
    return JournalEntry(
        literal.id, reference, probe_day, literal.lines,
        description=case.case_id if len(case.rows) == 1 else None,
        metadata={JDL_OUTPUT_METADATA_KEY: evidence_profile.value, "moneyforward_descriptions": markers,
                  ROW_ORDER_KEY: tuple(range(1, len(case.rows) + 1))},
    )


def _accounts(context) -> tuple[dict, dict]:
    names = {item.target_master_code: item.mapping_value for item in context.account_master}
    with_subaccounts = {item.parent_account_code for item in context.subaccounts}
    usable = lambda code: code in names and code not in with_subaccounts  # noqa: E731
    pick = lambda options: next((code for code in options if usable(code)), None)  # noqa: E731
    accounts = {
        "cash": pick(["1111"]),
        "purchase": pick(["8471", "8481", "8681", "7121"]),
        "no_tax_credit": pick(["3181", "3141", "3161", "3221", "3271", "1311"]),
        "credit_purchase": [code for code in ("8471", "8991", "8681", "8481", "7151", "8611") if usable(code)][:3],
        "nonpur": [code for code in ("7131", "7121", "8991", "7141", "8641") if usable(code)][:3],
    }
    missing = [key for key, value in accounts.items() if not value or isinstance(value, list) and len(value) < 3]
    missing += [code for code in ("6121", "6131", "6181", "7121", "9111") if not usable(code)]
    if missing:
        raise CampaignError(f"target master lacks usable (no-subaccount) accounts: {missing}")
    return accounts, names


def self_export_sheet(probe_day: date, accounts) -> list[dict]:
    """Group B: entered by the Human on the JDL screen, then self-exported (no Import)."""
    day = probe_day.strftime("%Y-%m-%d")
    rows = [
        ("B-EXPORT", "輸出売上（免税・0%）", "借方 現金(1111) / 貸方 売上(6121)", 11000,
         "貸方の税区分で JDL の『輸出売上』『免税売上』に当たるものを選ぶ", "TAX_UNAVAILABLE:EXPORT_EXEMPT:CREDIT", 35),
        ("B-RED8", "課税仕入 軽減8%（適格）", f"借方 {accounts['purchase']} / 貸方 現金(1111)", 1080,
         "借方の税区分で 軽減8%・内税 の仕入を選ぶ", "TAX_UNAVAILABLE:REDUCED_8:DEBIT", 15),
        ("B-TRANS80", "課税仕入10% 区分記載・80%経過措置", f"借方 {accounts['purchase']} / 貸方 現金(1111)", 1100,
         "借方の税区分で 10%・内税 の仕入を選び、インボイス区分を『経過措置80%（区分記載）』にする", "TAX_UNAVAILABLE:TRANSITIONAL_80:DEBIT", 21),
        ("B-NODED10", "課税仕入10% 区分記載・控除不可", f"借方 {accounts['purchase']} / 貸方 現金(1111)", 1100,
         "借方の税区分で 10% の仕入を選び、控除できない扱い（控除不可・経過措置なし）を指定する", "TAX_UNAVAILABLE:NON_DEDUCTIBLE:DEBIT", 3),
        ("B-NODED8", "課税仕入 軽減8% 区分記載・控除不可", f"借方 {accounts['purchase']} / 貸方 現金(1111)", 1080,
         "B-RED8 と同じ軽減8%で、控除不可を指定する", "TAX_UNAVAILABLE:NON_DEDUCTIBLE:DEBIT", 1),
        ("B-CLOSING", "決算仕訳（決算整理）", f"借方 {accounts['purchase']} / 貸方 現金(1111)", 1000,
         "出納帳で決算仕訳（決算区分）を入力できるか確認し、できる場合だけ入力。できなければ『入力不可』と記録", "CLOSING_ENTRY", 7),
    ]
    # Hand-entered examples are BM-*; the later Import of group B uses BI-* on
    # another date, so the two can never be confused or matched to each other.
    return [{"case": case.replace("B-", "BM-", 1), "what": what, "accounts": acc, "amount": amount, "date": day, "description": case.replace("B-", "BM-", 1),
             "how_on_jdl_screen": how, "settles": key, "journals": journals}
            for case, what, acc, amount, how, key, journals in rows]


def generate(source: Path, company_store: Path, company_id: str, probe_date: str, output_dir: Path,
             min_journals: int = 3) -> dict:
    if "data/private" not in output_dir.resolve().as_posix():
        raise CampaignError("probe files contain the company's JDL master names; write them under data/private only")
    probe_day = date(int(probe_date[:4]), int(probe_date[4:6]), int(probe_date[6:]))
    profiles = ConversionProfileStore(company_store / "profiles")
    resolved = CompanySettingStore(company_store / "companies", profiles).resolve(company_id)
    context = resolved.context
    if context is None or not ev.context_is_verified(context):
        raise CampaignError("the company has no confirmed Tax Context in the verified 税抜・原則・一括比例 Context")
    entries = detect_format(source).diagnose(source).entries
    if any(entry.date == probe_day for entry in entries):
        raise CampaignError("the probe date has source journals; choose a day without any")
    analysis = []
    for entry in entries:
        keys, profile = campaign.journal_keys(entry, context)
        analysis.append({"keys": keys, "signature": profile["signature"], "pattern": profile["pattern"],
                         "self_export_first": any(campaign.family(k) in {"TAX_UNAVAILABLE", "CLOSING_ENTRY"} for k in keys)})
    accounts, names = _accounts(context)
    cases = fixed_cases(accounts) + structural_cases(analysis, accounts, min_journals)
    settled_by_cases = {key for case in cases for key in case.settles} | set(EXISTING_SYNTHETIC_EVIDENCE)
    cases += boundary_cases(analysis, settled_by_cases, accounts)
    if len({case.case_id for case in cases}) != len(cases):
        raise CampaignError("duplicate case ids")
    synthetic = _synthetic_profile(context)
    output_dir.mkdir(parents=True, exist_ok=True)
    risky = [case for case in cases if import_may_be_rejected(case)]
    safe = [case for case in cases if not import_may_be_rejected(case)]
    common = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_activation_allowed": False,
        "status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_kind": "fully_synthetic_JDL_target_probe_with_company_structure",
        "target": "JDL IBEX 出納帳 35.5",
        "company_setting_id": company_id,
        "tax_context_identity_sha256": ev.tax_context_identity_sha256(context),
        "sales_tax_rounding": context.sales_tax_rounding.value,
        "purchase_tax_rounding": context.purchase_tax_rounding.value,
        "probe_date": probe_date,
        "must_verify_before_import": [
            "independent_test_copy_of_the_company_JDL_data (restorable backup taken first)",
            "probe_date_inside_the_test_copy_fiscal_period",
            "no_existing_journal_on_the_probe_date_in_the_test_copy",
            "test_copy_tax_settings: 税抜・原則課税・一括比例配分, 端数 売上/仕入 = manifest values",
            "accounts_in_the_probe_exist_in_the_test_copy_master",
        ],
        "known_limitations": [
            "synthetic target probe, not a Yayoi-source formal conversion",
            "does not confirm any Human tax or account mapping",
            "structural cases prove the row layout and tax placement, not other accounts",
        ],
        "settled_by_existing_evidence_not_reprobed": EXISTING_SYNTHETIC_EVIDENCE,
    }
    manifests = {}
    for batch, subset, note in (
        ("A1", safe, "既知の表現だけ。まとめて取り込む"),
        ("A2", risky, "税の付く側が通常と逆（売上の戻り・仕入の戻りなど）。取込自体を拒否される可能性があるため別ファイル"),
    ):
        if not subset:
            continue
        manifests[batch] = _write_batch(batch, note, subset, probe_day, probe_date, names, synthetic, context,
                                        company_id, output_dir, common)
    sheet = output_dir / f"GROUP_B_SELF_EXPORT_{probe_date}.json"
    if sheet.exists():
        raise CampaignError("group B sheet already exists; nothing is overwritten")
    sheet.write_text(json.dumps({"NOT_FOR_PRODUCTION": True, "probe_date": probe_date,
                                 "examples": self_export_sheet(probe_day, accounts)},
                                ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"batches": manifests, "group_b_sheet": sheet.name}


def import_may_be_rejected(case: Case) -> bool:
    """Tax on the side JDL has never accepted for it: the whole file could be refused."""
    for debit, credit in case.rows:
        if debit is not None and debit.tax in {"S10", "NS"}:
            return True
        if credit is not None and credit.tax in {"P10", "NP"}:
            return True
    return False


def _write_batch(batch, note, cases, probe_day, probe_date, names, synthetic, context, company_id, output_dir, common):
    entries = [_entry(case, index, probe_day, names, synthetic, context) for index, case in enumerate(cases)]
    guards = production_guards(entries, context)
    rows = serialize(entries, context)
    JDLOutputAdapter._validate_field_lengths(rows)
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
    payload = buffer.getvalue().encode("cp932", errors="strict")
    candidate = output_dir / f"YAYOI_EVIDENCE_CAMPAIGN_{batch}_{probe_date}_NOT_FOR_PRODUCTION.csv"
    if candidate.exists() or manifest_path_for(candidate).exists():
        raise CampaignError("probe files already exist; nothing is overwritten")
    candidate.write_bytes(payload)
    manifest = {
        **common,
        "batch": batch,
        "batch_note": note,
        "probe_file": candidate.name,
        "probe_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_logical_journals": len(cases),
        "expected_physical_rows": len(rows),
        "cases": [
            {"case": case.case_id, "journal_index": index, "physical_rows": len(case.rows),
             "pending_evidence_id": f"PENDING:EVID-YAYOI-JDL-35-5-{company_id.upper()}-{case.case_id}-SYNTHETIC-ROUNDTRIP-001",
             "group": case.group, "purpose": case.purpose, "expected": case.expected, "settles": list(case.settles),
             "shape": "%dD%dC/%drows" % case.shape}
            for index, case in enumerate(cases)
        ],
        "production_guards_today": guards,
    }
    manifest_path_for(candidate).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Sanity: every case must match itself exactly once (grouping and manifest agree).
    self_check = check(candidate, candidate, manifest)
    if any(result["verdict"] != "PASS" for result in self_check["cases"].values()):
        raise CampaignError(f"{batch}: self-comparison failed; the manifest does not match the probe")
    return manifest


def production_guards(entries, context) -> dict[str, list[str]]:
    """Which production preflight guards refuse each case today (expected: the probed capability)."""
    result = {}
    for entry in entries:
        preflight = JdlOutputPreflight(context).evaluate([entry], jdl_ibex_35_5_output_profile())
        result[entry.id.split(":", 1)[1]] = sorted({item.rule_id for item in preflight.validation_results})
    return result


def serialize(entries, context) -> tuple[tuple[str, ...], ...]:
    """Rows from the production row builder (`JdlOutputPreflight._row`) and its flag rules.

    Only the acceptance guards are skipped (they refuse exactly the unverified
    capability a probe exists to test); every column value comes from the same
    code formal output uses: 1D1C one row flagged 1111, compound rows flagged
    1110 / 1100... / 1101 in physical-row order with per-row descriptions.
    """
    builder = JdlOutputPreflight(context)
    rows = []
    for entry in entries:
        physical = journal_physical_rows(entry)
        if physical is None:
            raise CampaignError(f"{entry.id}: physical rows could not be resolved")
        if len(physical) == 1:
            row = physical[0]
            rows.append(builder._row("1111", entry, row.debit, row.credit, entry.description or ""))
            continue
        flags = ("1110", *("1100",) * (len(physical) - 2), "1101")
        for flag, row in zip(flags, physical, strict=True):
            rows.append(builder._row(flag, entry, row.debit, row.credit, row.description))
    return tuple(row.columns() for row in rows)


def coverage(source: Path, context, settled: set[str]) -> dict:
    """Journals whose every key would be settled, for a planning estimate."""
    entries = detect_format(source).diagnose(source).entries
    needs = [campaign.journal_keys(entry, context)[0] for entry in entries]
    open_ = [keys for keys in needs if keys]
    return {"journals": len(entries), "without_keys_now": len(entries) - len(open_),
            "unblocked_by_campaign": sum(1 for keys in open_ if keys <= settled),
            "still_open": sum(1 for keys in open_ if not keys <= settled),
            "still_open_by_family": dict(Counter(
                campaign.family(k) for keys in open_ if not keys <= settled for k in keys - settled).most_common())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--company-store", type=Path, required=True)
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--probe-date", required=True, help="YYYYMMDD: a day with no journals in the test copy")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-journals", type=int, default=3)
    args = parser.parse_args()
    result = generate(args.source, args.company_store, args.company_id, args.probe_date, args.output_dir,
                      args.min_journals)
    all_cases = [case for manifest in result["batches"].values() for case in manifest["cases"]]
    profiles = ConversionProfileStore(args.company_store / "profiles")
    context = CompanySettingStore(args.company_store / "companies", profiles).resolve(args.company_id).context
    settled = {key for case in all_cases for key in case["settles"]}
    settled |= {"NONSALE_TARGET_ACCOUNT"}  # 9111 is the exact candidate and already verified
    settled |= set(EXISTING_SYNTHETIC_EVIDENCE)
    print(json.dumps({
        "batches": {batch: {"file": m["probe_file"], "sha256": m["probe_sha256"], "cases": len(m["cases"]),
                            "physical_rows": m["expected_physical_rows"],
                            "cases_by_group": dict(Counter(case["group"] for case in m["cases"]))}
                    for batch, m in result["batches"].items()},
        "group_b_sheet": result["group_b_sheet"],
        "planning_estimate_if_every_case_passes": coverage(args.source, context, settled),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

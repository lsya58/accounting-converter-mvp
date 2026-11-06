"""Generate one synthetic, pending JDL roundtrip batch for newly added accounts."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.output.jdl.models import JdlAccountIdentity
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.tools import generate_yayoi_evidence_campaign as campaign
from accounting_converter.tools import generate_yayoi_gap_probes as gap


NEW_SALES = ("6122", "6123", "6124", "6132", "6142")
NEW_PURCHASE = ("7122", "8672")
NEW_CODES = frozenset((*NEW_SALES, *NEW_PURCHASE))


def cases(cash: str, credit: str) -> list[gap.Case]:
    amount = Decimal("1100")
    fractional = Decimal("1106")
    result = []
    sales_specs = (
        ("6122", "FLOOR", fractional, Decimal("100")),
        ("6123", "WHOLE", amount, Decimal("100")),
        *((code, relation, fractional, tax)
          for code in ("6124", "6132", "6142")
          for relation, tax in (("COMPANY", Decimal("101")), ("FLOOR", Decimal("100")))),
    )
    for code, relation, value, tax in sales_specs:
        result.append(gap.one_row(
            f"NA-S10-{code}-{relation}", "NEW_ACCOUNT", "新売上科目の貸方・課税売上10%・明示税額",
            gap.KEEP, gap.Line("NO", cash, value), gap.Line("S10", code, value, tax),
            proves=[f"ACCOUNT:CREDIT:{code}:S10:{relation}"],
        ))
    result.extend((
        gap.one_row("NA-XS-6142", "NEW_ACCOUNT", "6142貸方・輸出売上", gap.KEEP,
                    gap.Line("NO", cash, amount), gap.Line("XS", "6142", amount),
                    proves=["ACCOUNT:CREDIT:6142:XS"]),
        gap.one_row("NA-DS10-6142", "NEW_ACCOUNT", "6142借方・課税売上10%", gap.KEEP,
                    gap.Line("S10", "6142", fractional, Decimal("100")), gap.Line("NO", cash, fractional),
                    proves=["ACCOUNT:DEBIT:6142:S10"]),
    ))
    for code in NEW_PURCHASE:
        result.append(gap.one_row(
            f"NA-P10-{code}-COMPANY", "NEW_ACCOUNT", "新仕入科目の借方・課税仕入10%・会社端数",
            gap.KEEP, gap.Line("P10", code, fractional, Decimal("101")),
            gap.Line("NO", credit, fractional),
            proves=[f"ACCOUNT:DEBIT:{code}:P10:COMPANY"],
        ))
    assert len(result) == 12
    return result


def generate(diff_path: Path, pdf_path: Path, context_path: Path, output_dir: Path, probe_day: date) -> Path:
    if "data/private/yayoi_buddies/" not in output_dir.resolve().as_posix() + "/":
        raise ValueError("probe output must stay under data/private/yayoi_buddies")
    if not output_dir.is_dir() or any(output_dir.iterdir()):
        raise ValueError("probe output directory must exist and be empty")
    diff = json.loads(diff_path.read_text(encoding="utf-8"))
    pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    if diff["diff"]["sources"]["new"] != pdf_hash:
        raise ValueError("latest PDF does not match the audited master diff")
    old = {(r["code"], r["name"]) for r in diff["old"] if r["kind"] in ("coded", "parent")}
    new_rows = [r for r in diff["new"] if r["kind"] in ("coded", "parent")]
    new = {(r["code"], r["name"]) for r in new_rows}
    if not old <= new:
        raise ValueError("master diff is not additive")
    targets = {r["code"]: r for r in new_rows if r["code"] in NEW_CODES}
    if set(targets) != NEW_CODES or any(r["use"] != "○" for r in targets.values()):
        raise ValueError("new account is absent or disabled")
    if any(r.get("parent") in NEW_CODES for r in diff["new"] if r["kind"] == "sub"):
        raise ValueError("new account has subaccounts; blank-subaccount probe is unsafe")
    context = JdlTargetContextLoader().load(context_path)
    if not context.confirmation_state.value == "CONFIRMED" or not gap.ev.context_is_verified(context):
        raise ValueError("confirmed matching tax context is required")
    additions = tuple(
        JdlAccountIdentity(r["abbr"][1:], code, r["abbr"][1:], r["name"])
        for code, r in sorted(targets.items())
    )
    if any(not targets[item.target_master_code]["abbr"].startswith(("借", "貸")) for item in additions):
        raise ValueError("printed abbreviation has no balance-side prefix")
    if any(item.target_master_code in {old.target_master_code for old in context.account_master} for item in additions):
        raise ValueError("new target code already exists in saved context")
    context = replace(
        context,
        accounts=context.accounts | frozenset(item.mapping_value for item in additions),
        account_master=(*context.account_master, *additions),
    )
    accounts, names = campaign._accounts(context)
    all_cases = cases(accounts["cash"], accounts["no_tax_credit"])
    common = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False,
        "evidence_activation_allowed": False, "status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "master_diff_sha256": hashlib.sha256(diff_path.read_bytes()).hexdigest(),
        "target_pdf_sha256": pdf_hash,
        "tax_context_identity_sha256": gap.ev.tax_context_identity_sha256(context),
        "probe_date": probe_day.isoformat(), "import_period": [probe_day.isoformat()] * 2,
        "voucher_row_limit": 16, "expected_new_codes": sorted(NEW_CODES),
    }
    manifest = gap.write_file(
        "NEW_ACCOUNT_12", "new account exact tax and rounding conditions", all_cases,
        probe_day, probe_day.strftime("%Y%m%d"), names, gap.synthetic_profile(context), context,
        "buddies", output_dir, common, check_lengths=True,
    )
    return output_dir / manifest["probe_file"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    print(generate(args.diff, args.pdf, args.context, args.output_dir, args.date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

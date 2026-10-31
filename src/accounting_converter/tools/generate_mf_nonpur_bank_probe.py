from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.application.moneyforward_tax_excluded_evidence import context_is_verified, tax_context_identity_sha256
from accounting_converter.domain.journal import Side
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import ExactShapeProbeError, _atomic_write_pair
from accounting_converter.tools.mf_tax_context_probe import _journal_rows
from accounting_converter.tools.generate_mf_pending_tax_probe import _confirmed_target


MARKER = "MF-TAX-NONPUR-1311-PENDING"


def generate(
    source: Path, template: Path, company_path: Path, profile_path: Path,
    output_dir: Path, *, probe_date: str = "20260528",
) -> tuple[Path, Path]:
    """Only the unverified 8571/no-sub to 1311/0002 non-taxable purchase signature."""
    if datetime.strptime(probe_date, "%Y%m%d").strftime("%Y%m%d") != probe_date:
        raise ValueError("probe date must be YYYYMMDD")
    company = json.loads(company_path.read_text(encoding="utf-8"))
    context_path = company_path.parent / company["jdl_context_relative_path"]
    if hashlib.sha256(context_path.read_bytes()).hexdigest() != company["context_fingerprint"]:
        raise ExactShapeProbeError("CompanySetting context revision changed")
    store = ConversionProfileStore(profile_path.parent)
    profile = store.from_json_text(profile_path.read_text(encoding="utf-8"))
    if (
        profile.profile_id != company["conversion_profile_id"]
        or hashlib.sha256(store.to_json_text(profile).encode("utf-8")).hexdigest() != company["profile_fingerprint"]
    ):
        raise ExactShapeProbeError("CompanySetting profile revision changed")
    context = JdlTargetContextLoader().load(context_path)
    if not context_is_verified(context):
        raise ExactShapeProbeError("current JDL tax context is not confirmed")
    accounts = {item.target_master_code: item for item in context.account_master}
    subs = {(item.parent_account_code, item.output_code): item for item in context.subaccounts}
    if any(code not in accounts for code in ("8571", "1311")) or ("1311", "0002") not in subs:
        raise ExactShapeProbeError("required target account/subaccount is absent")
    if any(item.parent_account_code == "8571" for item in context.subaccounts):
        raise ExactShapeProbeError("debit account acquired a subaccount requirement")
    entries = MoneyForwardObservedParser().parse_path(source)
    matches = []
    for entry in entries:
        if len(entry.lines) != 2:
            continue
        by_side = {line.side: line for line in entry.lines}
        if set(by_side) != {Side.DEBIT, Side.CREDIT}:
            continue
        debit, credit = by_side[Side.DEBIT], by_side[Side.CREDIT]
        if (
            debit.account == "保険料" and debit.sub_account is None
            and debit.tax_info is not None and debit.tax_info.category == "非課税仕入"
            and credit.account == "普通預金" and credit.tax_info is not None
            and credit.tax_info.category == "対象外" and credit.sub_account is not None
            and not any(line.department or line.metadata.get("moneyforward_trade_partner") or line.tax_info.invoice_classification for line in entry.lines)
            and not entry.metadata.get("moneyforward_tags") and not entry.metadata.get("moneyforward_memos")
        ):
            matches.append(entry)
    if len(matches) != 1:
        raise ExactShapeProbeError("expected one exact real-source non-taxable purchase residual")
    source_sides = {line.side: line for line in matches[0].lines}
    actual_debit = _confirmed_target(source_sides[Side.DEBIT], profile, accounts, subs)
    actual_credit = _confirmed_target(source_sides[Side.CREDIT], profile, accounts, subs)
    if (
        actual_debit[0].target_master_code != "8571" or actual_debit[1] is not None
        or actual_credit[0].target_master_code != "1311" or actual_credit[1] is None
        or actual_credit[1].output_code != "0002"
    ):
        raise ExactShapeProbeError("current confirmed mapping differs from the residual signature")
    old_rows = _journal_rows(template)
    old = next((row for row in old_rows if row[23] == "MF-TAX-NONPUR-PENDING"), None)
    if old is None or (
        old[3], old[6], old[8], old[9], old[10], old[13], old[16], old[18], old[19], old[20]
    ) != ("8571", "", "非仕入", "", "", "3181", "0001", "", "", ""):
        raise ExactShapeProbeError("earlier successful non-taxable purchase candidate differs")
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    row = list(old)
    row[1] = ""
    row[2] = probe_date
    bank = accounts["1311"]
    bank_sub = subs[("1311", "0002")]
    row[13:18] = ["1311", bank.target_name, bank.target_formal_name, "0002", bank_sub.output_name]
    row[23] = MARKER
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// MF NONPUR RESIDUAL PROBE / NOT FOR PRODUCTION", *([""] * 29)])
    writer.writerow([f"// 出力期間 ： {probe_date} ～ {probe_date}", *([""] * 29)])
    writer.writerow([""] * 30)
    writer.writerow(header)
    writer.writerow(row)
    payload = stream.getvalue().encode("cp932", errors="strict")
    output = output_dir / "mf_nonpur_8571_1311_sub0002_pending.csv"
    manifest = output_dir / "mf_nonpur_8571_1311_sub0002_pending.manifest.private.json"
    metadata = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_journal_sha256": hashlib.sha256(matches[0].id.encode("utf-8")).hexdigest(),
        "source_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "tax_context_identity_sha256": tax_context_identity_sha256(context),
        "import_period": {"start": probe_date, "end": probe_date},
        "journal_count": 1, "physical_row_count": 1,
        "target_signature": ["8571/blank", "1311/0002", "非仕入", "opposite blank"],
        "strict_comparison_required": True,
    }
    _atomic_write_pair((output, payload), (manifest, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
    return output, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("company", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(generate(args.source, args.template, args.company, args.profile, args.output_dir))


if __name__ == "__main__":
    main()

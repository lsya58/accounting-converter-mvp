from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.application.moneyforward_tax_excluded_evidence import context_is_verified, tax_context_identity_sha256
from accounting_converter.domain.mapping import DEFAULT_SUBACCOUNT_SOURCE_VALUE
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import (
    ExactShapeProbeError, _atomic_write_pair, _compound_flags, _descriptions_by_row,
    _encode, _physical_rows, _shape, _target_row,
)
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.tools.mf_tax_context_probe import _journal_count


SHAPES = Counter({"4D6C": 5, "5D7C": 1, "5D8C": 5})
EVIDENCE_ID = "EVID-MF-JDL-35-5-OUTPUR-8471-1111-ROUNDTRIP-001"


def generate(source: Path, company_path: Path, profile_path: Path, output_dir: Path, *, probe_date: str = "20260527") -> tuple[Path, Path]:
    """Build a gated real-source witness; this is never the formal conversion route."""
    if datetime.strptime(probe_date, "%Y%m%d").strftime("%Y%m%d") != probe_date:
        raise ValueError("probe date must be YYYYMMDD")
    company = json.loads(company_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != company.get("conversion_profile_id"):
        raise ExactShapeProbeError("CompanySetting profile reference changed")
    if "Money Forward" not in company.get("expected_source_format_key", "") or "JDL" not in company.get("expected_target_format_key", ""):
        raise ExactShapeProbeError("CompanySetting route differs from MF-to-JDL")
    context_path = company_path.parent / company["jdl_context_relative_path"]
    context = JdlTargetContextLoader().load(context_path)
    if not context_is_verified(context):
        raise ExactShapeProbeError("current tax context is not confirmed")
    setup_hash = company["context_fingerprint"]
    accounts = {item.target_master_code: item for item in context.account_master}
    subs = {(item.parent_account_code, item.output_code): item for item in context.subaccounts}
    account_mappings = {}
    for item in profile["account_mappings"]:
        if item["status"] != "USER_CONFIRMED":
            continue
        metadata = item["metadata"]
        code = metadata.get("target_code")
        master = accounts.get(code)
        if metadata.get("setup_context_sha256") != setup_hash or master is None:
            continue
        if metadata.get("target_formal_name") != master.target_formal_name:
            continue
        account_mappings[item["source_value"]] = {
            "human_confirmed": True, "code": code,
            "name": master.target_name, "formal_name": master.target_formal_name,
        }
    sub_mappings = []
    for item in profile["subaccount_context_mappings"]:
        if item["status"] != "USER_CONFIRMED":
            continue
        metadata = item["metadata"]
        if metadata.get("setup_context_sha256") != setup_hash:
            continue
        sub_mappings.append({
            "source_parent": item["parent_account"],
            "source_subaccount": item["source_value"],
            "human_confirmed": True,
            "policy": metadata.get("subaccount_policy"),
            "target_code": metadata.get("target_code", ""),
            "target_name": metadata.get("output_name", item.get("target_value", "")),
        })
    entries = tuple(
        entry for entry in MoneyForwardObservedParser().parse_path(source)
        if any(line.tax_info and line.tax_info.category == "対象外仕入" for line in entry.lines)
    )
    if len(entries) != 11 or Counter(_shape(entry) for entry in entries) != SHAPES:
        raise ExactShapeProbeError("source no longer matches the audited 11 compound journals")
    target_rows = []
    case_manifest = []
    for entry in entries:
        if entry.metadata.get("moneyforward_tags") or entry.metadata.get("moneyforward_memos"):
            raise ExactShapeProbeError("optional field outside probe scope")
        physical = _physical_rows(entry)
        descriptions = _descriptions_by_row(entry)
        if len(descriptions) != len(physical):
            raise ExactShapeProbeError("every compound row requires its original description")
        if sum(line.tax_info and line.tax_info.category == "対象外仕入" for line in entry.lines) != 1:
            raise ExactShapeProbeError("unexpected source tax placement")
        line_taxes = {}
        for index, (_, debit, credit) in enumerate(physical):
            for side, line in (("DEBIT", debit), ("CREDIT", credit)):
                if line is None:
                    continue
                if line.tax_info is None or line.tax_info.category not in {"対象外仕入", "対象外"}:
                    raise ExactShapeProbeError("source tax outside observed blank/zero probe scope")
                if line.department or line.metadata.get("moneyforward_trade_partner") or line.tax_info.invoice_classification:
                    raise ExactShapeProbeError("optional field outside probe scope")
                target = account_mappings.get(line.account)
                if target is None:
                    raise ExactShapeProbeError("source account has no current confirmed mapping")
                if line.sub_account:
                    matches = [m for m in sub_mappings if (m["source_parent"], m["source_subaccount"]) == (line.account, line.sub_account)]
                    if len(matches) != 1 or matches[0]["policy"] != "PRESERVE_SUBACCOUNT":
                        raise ExactShapeProbeError("source subaccount has no current exact preserve mapping")
                    code = matches[0]["target_code"]
                    master_sub = subs.get((target["code"], code))
                    if master_sub is None or master_sub.output_name != matches[0]["target_name"]:
                        raise ExactShapeProbeError("confirmed target subaccount differs from current master")
                elif any(s.parent_account_code == target["code"] for s in context.subaccounts):
                    default = [m for m in sub_mappings if (m["source_parent"], m["source_subaccount"]) == (line.account, DEFAULT_SUBACCOUNT_SOURCE_VALUE)]
                    if len(default) != 1 or default[0]["policy"] != "PRESERVE_SUBACCOUNT":
                        raise ExactShapeProbeError("blank source subaccount requires confirmed target choice")
                line_taxes[f"{index}:{side}"] = {"human_confirmed": True, "scope": "", "category": "", "input_method": "", "tax_amount": "0"}
        start = len(target_rows)
        for index, (source_row, debit, credit) in enumerate(physical):
            description = descriptions[source_row]
            if not 1 <= len(description) <= 32:
                raise ExactShapeProbeError("description outside JDL limit")
            description.encode("cp932", errors="strict")
            target_rows.append(_target_row(
                flag=_compound_flags(len(physical))[index], journal_date=probe_date,
                description=description, debit=debit, credit=credit,
                physical_index=index, account_mappings=account_mappings,
                subaccount_mappings=sub_mappings, line_tax_mappings=line_taxes,
            ))
        case_manifest.append({
            "journal_sha256": hashlib.sha256(entry.id.encode("utf-8")).hexdigest(),
            "shape": _shape(entry), "start_row_zero_based": start,
            "physical_row_count": len(physical),
            "description_sha256_by_row": [hashlib.sha256(descriptions[row].encode("utf-8")).hexdigest() for row, _, _ in physical],
            "dimensions": {
                "tax_representation": "PENDING_COMPOUND_INTERACTION",
                "compound_grouping": "PENDING_REAL_IMPORT_REEXPORT",
                "row_specific_description": "PENDING_REAL_IMPORT_REEXPORT",
            },
        })
    if len(target_rows) != 127 or _journal_count(tuple(target_rows)) != 11:
        raise ExactShapeProbeError("source physical row count or grouping changed")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    payload = _encode((
        ("// MF OUTPUR COMPOUND PROBE / NOT FOR PRODUCTION", *([""] * 29)),
        (f"// 出力期間 ： {probe_date} ～ {probe_date}", *([""] * 29)),
        ("",) * 30, header, *target_rows,
    ))
    output = output_dir / "mf_outpur_compound_11_pending.csv"
    manifest = output_dir / "mf_outpur_compound_11_pending.manifest.private.json"
    metadata = {
        "NOT_FOR_PRODUCTION": True, "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "setup_context_sha256": setup_hash,
        "tax_context_identity_sha256": tax_context_identity_sha256(context),
        "tax_literal_evidence_id": EVIDENCE_ID,
        "source_tax_identity": "対象外仕入",
        "source_tax_mapping_status": next((m["status"] for m in profile["tax_mappings"] if m["source_value"] == "対象外仕入"), "MISSING"),
        "probe_uses_observed_blank_zero_representation_not_formal_mapping": True,
        "journal_count": len(entries), "physical_row_count": len(target_rows),
        "import_period": {"start": probe_date, "end": probe_date},
        "cases": case_manifest,
        "strict_comparison_required": True,
        "overwrite_allowed": False,
    }
    _atomic_write_pair((output, payload), (manifest, (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
    return output, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("company", type=Path)
    parser.add_argument("profile", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--probe-date", default="20260527")
    args = parser.parse_args()
    print(generate(args.source, args.company, args.profile, args.output_dir, probe_date=args.probe_date))


if __name__ == "__main__":
    main()

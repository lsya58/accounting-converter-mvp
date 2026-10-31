from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.application.moneyforward_tax_excluded_evidence import context_is_verified, tax_context_identity_sha256
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, SubaccountPolicy
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools.generate_mf_exact_shape_probe import ExactShapeProbeError, _atomic_write_pair
from accounting_converter.tools.mf_tax_context_probe import _journal_rows
from accounting_converter.tools.export_mf_probe_snapshot import build_snapshot


CASES = (
    ("課税売上 10%", "tax_sales_10_with_subaccount.csv", "CREDIT", "20260520", "MF-TAX-SALES10-PENDING"),
    ("非課税仕入", "tax_non_taxable_purchase_with_subaccount.csv", "DEBIT", "20260521", "MF-TAX-NONPUR-PENDING"),
    ("非課税売上", "tax_non_taxable_sales_with_subaccount.csv", "CREDIT", "20260522", "MF-TAX-NONSALE-PENDING"),
)


def generate_pending_tax_probe(
    source: Path,
    template_dir: Path,
    output_dir: Path,
    company_id: str,
    company_root: Path,
    profile_root: Path,
) -> tuple[Path, Path]:
    profiles = ConversionProfileStore(profile_root)
    companies = CompanySettingStore(company_root, profiles)
    setting = companies.get(company_id)
    profile = profiles.get(setting.conversion_profile_id)
    context_path = companies.context_path(setting)
    if (
        setting.profile_fingerprint != hashlib.sha256(profiles.to_json_text(profile).encode("utf-8")).hexdigest()
        or setting.context_fingerprint != hashlib.sha256(context_path.read_bytes()).hexdigest()
    ):
        raise ExactShapeProbeError("company profile or context revision is stale")
    context = JdlTargetContextLoader().load(context_path)
    build_snapshot(setting, profile, context)
    if not context_is_verified(context):
        raise ExactShapeProbeError("current JDL tax context is not verified")
    if tax_context_identity_sha256(context) == "a300dc8750b7fe6417f2d3c092a6cae2055ccf0256cd539a7036e4b67b0de3e0" and any(
        case[0] == "課税売上 10%" for case in CASES
    ):
        raise ExactShapeProbeError(
            "sales-10 literal 売一種 was rejected by this target; use the JDL self-export-derived rev2 generator"
        )
    if output_dir.exists():
        raise FileExistsError("pending tax probe directory already exists")
    entries = MoneyForwardObservedParser().parse_path(source)
    accounts = {item.target_master_code: item for item in context.account_master}
    subaccounts = {(item.parent_account_code, item.target_master_code): item for item in context.subaccounts}
    header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
    positions = {name: index for index, name in enumerate(header)}
    rows: list[list[str]] = []
    cases: list[dict[str, object]] = []
    for tax_identity, template_name, tax_side, probe_date, marker in CASES:
        template_path = template_dir / template_name
        template_rows = _journal_rows(template_path)
        if len(template_rows) != 1:
            raise ExactShapeProbeError("tax template must be one physical row")
        template = template_rows[0]
        prefix = "借方" if tax_side == "DEBIT" else "貸方"
        observed_tax = tuple(template[positions[f"{prefix}{field}"]] for field in ("課区", "税区", "税入力方法", "消費税"))
        expected_tax = {
            "課税売上 10%": ("売一種", "10%", "", ""),
            "非課税仕入": ("非仕入", "", "", ""),
            "非課税売上": ("非売上", "", "", ""),
        }[tax_identity]
        if observed_tax != expected_tax:
            raise ExactShapeProbeError("observed JDL tax template changed")
        selected = None
        selected_sides = None
        for entry in entries:
            if len(entry.lines) != 2 or not any(
                line.tax_info and line.tax_info.category == tax_identity for line in entry.lines
            ):
                continue
            if any(line.metadata.get("moneyforward_trade_partner") for line in entry.lines):
                continue
            by_side = {line.side.value: line for line in entry.lines}
            if set(by_side) != {"DEBIT", "CREDIT"}:
                continue
            if by_side[tax_side].tax_info.category != tax_identity:
                continue
            if any(
                line.tax_info is None or line.tax_info.category not in (tax_identity, "対象外")
                for line in entry.lines
            ):
                continue
            try:
                identities = {side: _confirmed_target(line, profile, accounts, subaccounts)
                              for side, line in by_side.items()}
            except ExactShapeProbeError:
                continue
            selected, selected_sides = entry, identities
            break
        if selected is None or selected_sides is None:
            raise ExactShapeProbeError(f"no exact mapped 1D1C witness for {tax_identity}")
        row = ["" for _ in header]
        row[0] = "1111"
        row[2] = probe_date
        for side, offset in (("DEBIT", 3), ("CREDIT", 13)):
            account, subaccount = selected_sides[side]
            row[offset:offset + 5] = [
                account.target_master_code, account.target_name,
                account.target_formal_name,
                subaccount.output_code if subaccount else "",
                subaccount.output_name if subaccount else "",
            ]
            row[offset + 8] = "1100"
        tax_offset = 3 if tax_side == "DEBIT" else 13
        row[tax_offset + 5:tax_offset + 8] = list(observed_tax[:3])
        row[tax_offset + 9] = observed_tax[3]
        row[23] = marker
        rows.append(row)
        cases.append({
            "source_tax_identity": tax_identity,
            "source_journal_sha256": hashlib.sha256(selected.id.encode("utf-8")).hexdigest(),
            "tax_side": tax_side,
            "date": probe_date,
            "target_account_codes": [selected_sides[side][0].target_master_code for side in ("DEBIT", "CREDIT")],
            "target_subaccount_codes": [selected_sides[side][1].output_code if selected_sides[side][1] else "" for side in ("DEBIT", "CREDIT")],
            "candidate_tax_fields": observed_tax,
            "tax_template_sha256": hashlib.sha256(template_path.read_bytes()).hexdigest(),
            "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        })
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["// MF TAX DISCOVERY PROBE / NOT FOR PRODUCTION", *([""] * 29)])
    writer.writerow(["// 出力期間 ： 20260520 ～ 20260522", *([""] * 29)])
    writer.writerow([""] * 30)
    writer.writerow(header)
    writer.writerows(rows)
    payload = stream.getvalue().encode("cp932", errors="strict")
    output = output_dir / "mf_tax_three_case_pending.csv"
    manifest_path = output_dir / "mf_tax_three_case_pending.manifest.private.json"
    manifest = {
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "evidence_status": "PENDING_REAL_JDL_IMPORT_REEXPORT",
        "tax_context_identity_sha256": tax_context_identity_sha256(context),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(payload).hexdigest(),
        "journal_count": len(cases),
        "physical_row_count": len(rows),
        "import_period": {"start": "20260520", "end": "20260522"},
        "cases": cases,
        "comparator": "accounting_converter.tools.mf_tax_context_probe.compare_probe_patterns",
        "caution": "Prior JDL tax templates have a different company/context; these are discovery candidates, not verified mappings.",
    }
    _atomic_write_pair(
        (output, payload),
        (manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")),
    )
    return output, manifest_path


def _confirmed_target(line, profile, accounts, subaccounts):
    mapping = profile.account_mappings.get(line.account)
    if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
        raise ExactShapeProbeError("account is not Human-confirmed")
    code = str(mapping.metadata.get("target_code", ""))
    account = accounts.get(code)
    if account is None or account.mapping_value != mapping.target_value:
        raise ExactShapeProbeError("account differs from current master")
    children = [item for (parent, _), item in subaccounts.items() if parent == code]
    if line.sub_account is None:
        if children:
            raise ExactShapeProbeError("blank source requires confirmed target default subaccount")
        return account, None
    key = MappingKey(MappingType.SUBACCOUNT, line.sub_account, line.account)
    sub_mapping = profile.subaccount_context_mappings.get(key)
    if sub_mapping is None or sub_mapping.status is not MappingStatus.USER_CONFIRMED:
        raise ExactShapeProbeError("subaccount is not Human-confirmed")
    policy = sub_mapping.metadata.get("subaccount_policy", SubaccountPolicy.PRESERVE_SUBACCOUNT.value)
    if policy == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value and not children:
        return account, None
    if policy != SubaccountPolicy.PRESERVE_SUBACCOUNT.value:
        raise ExactShapeProbeError("subaccount policy is outside probe scope")
    sub_code = str(sub_mapping.metadata.get("target_code", ""))
    sub = subaccounts.get((code, sub_code))
    if sub is None or sub.mapping_value != sub_mapping.target_value:
        raise ExactShapeProbeError("subaccount differs from current master")
    return account, sub


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("source", "template_dir", "output_dir", "company_id", "company_root", "profile_root"):
        parser.add_argument(name, type=Path if name != "company_id" else str)
    args = parser.parse_args()
    print(generate_pending_tax_probe(
        args.source, args.template_dir, args.output_dir, args.company_id,
        args.company_root, args.profile_root,
    ))


if __name__ == "__main__":
    main()

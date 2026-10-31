from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.application.jdl_master_identity import target_context_master_identity_sha256
from accounting_converter.domain.journal import Side
from accounting_converter.domain.mapping import (
    DEFAULT_SUBACCOUNT_SOURCE_VALUE,
    MappingKey,
    MappingStatus,
    MappingType,
    SubaccountPolicy,
)
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.tools.generate_mf_exact_shape_probe import (
    ExactShapeProbeError,
    generate,
)
from accounting_converter.tools.export_mf_probe_snapshot import build_snapshot


def prepare_and_generate(
    source: Path,
    skeleton: Path,
    output_dir: Path,
    company_id: str,
    company_root: Path,
    profile_root: Path,
    *,
    probe_date: str,
) -> tuple[Path, Path]:
    profiles = ConversionProfileStore(profile_root)
    companies = CompanySettingStore(company_root, profiles)
    setting = companies.get(company_id)
    profile = profiles.get(setting.conversion_profile_id)
    context = JdlTargetContextLoader().load(companies.context_path(setting))
    snapshot = build_snapshot(setting, profile, context)
    if snapshot["tax_context"] != {
        "processing": "TAXABLE_TAX_EXCLUDED",
        "taxation": "STANDARD",
        "credit_method": "PROPORTIONAL",
        "business_category": None,
        "confirmation_state": "CONFIRMED",
    }:
        raise ExactShapeProbeError("current tax context is outside verified purchase-10 scope")
    config = json.loads(skeleton.read_text(encoding="utf-8"))
    if config.get("shape") not in ("1D2C", "10D9C"):
        raise ExactShapeProbeError("unsupported exact shape config")
    entries = MoneyForwardObservedParser().parse_path(source)
    import hashlib
    matches = [
        entry for entry in entries
        if hashlib.sha256(entry.id.encode("utf-8")).hexdigest() == config["journal_sha256"]
    ]
    if len(matches) != 1:
        raise ExactShapeProbeError("source journal identity changed")
    entry = matches[0]
    accounts_by_code = {item.target_master_code: item for item in context.account_master}
    subs_by_identity = {
        (item.parent_account_code, item.target_master_code): item
        for item in context.subaccounts
    }
    target_codes: dict[str, str] = {}
    for source_name, target in config["account_mappings"].items():
        mapping = profile.account_mappings.get(source_name)
        if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
            raise ExactShapeProbeError("required account mapping is not Human-confirmed")
        code = str(mapping.metadata.get("target_code", ""))
        identity = accounts_by_code.get(code)
        if identity is None or mapping.target_value != identity.mapping_value:
            raise ExactShapeProbeError("confirmed account is absent from current master")
        target.update({
            "code": code,
            "name": identity.target_name,
            "formal_name": identity.target_formal_name,
            "human_confirmed": True,
        })
        target_codes[source_name] = code
    default_targets: set[str] = set()
    for line in entry.lines:
        if not line.account:
            continue
        parent_code = target_codes[line.account]
        if line.sub_account is None and any(
            item.parent_account_code == parent_code for item in context.subaccounts
        ):
            default = profile.subaccount_context_mappings.get(MappingKey(
                MappingType.SUBACCOUNT, DEFAULT_SUBACCOUNT_SOURCE_VALUE, line.account
            ))
            if default is None or default.status is not MappingStatus.USER_CONFIRMED:
                raise ExactShapeProbeError("required default target subaccount is unconfirmed")
            if default.metadata.get("subaccount_policy") != SubaccountPolicy.PRESERVE_SUBACCOUNT.value:
                raise ExactShapeProbeError("default target subaccount must use an exact preserve policy")
            if line.account not in default_targets:
                config["subaccount_mappings"].append({
                    "source_parent": line.account,
                    "source_subaccount": DEFAULT_SUBACCOUNT_SOURCE_VALUE,
                })
                default_targets.add(line.account)
    for target in config["subaccount_mappings"]:
        mapping = profile.subaccount_context_mappings.get(MappingKey(
            MappingType.SUBACCOUNT, target["source_subaccount"], target["source_parent"]
        ))
        if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
            raise ExactShapeProbeError("required subaccount mapping is not Human-confirmed")
        policy = mapping.metadata.get("subaccount_policy", SubaccountPolicy.PRESERVE_SUBACCOUNT.value)
        target["policy"] = policy
        target["human_confirmed"] = True
        if policy == SubaccountPolicy.PRESERVE_SUBACCOUNT.value:
            parent_code = target_codes[target["source_parent"]]
            code = str(mapping.metadata.get("target_code", ""))
            identity = subs_by_identity.get((parent_code, code))
            if identity is None or mapping.target_value != identity.mapping_value:
                raise ExactShapeProbeError("confirmed subaccount is absent from current master")
            target["target_code"] = identity.output_code
            target["target_name"] = identity.output_name
        elif policy == SubaccountPolicy.PARENT_ONLY_CONFIRMED.value:
            parent_code = target_codes[target["source_parent"]]
            if any(item.parent_account_code == parent_code for item in context.subaccounts):
                raise ExactShapeProbeError("parent-only mapping conflicts with current master")
            target["target_code"] = ""
            target["target_name"] = ""
        else:
            raise ExactShapeProbeError("unsupported subaccount policy")
    rows = {}
    for line in entry.lines:
        row_number = line.metadata.get("journal_row_number")
        if not isinstance(row_number, int):
            raise ExactShapeProbeError("source physical row identity is missing")
        rows.setdefault(row_number, {})[line.side.value] = line
    for index, row_number in enumerate(sorted(rows)):
        for side, line in rows[row_number].items():
            target = config["line_tax_mappings"][f"{index}:{side}"]
            source_tax = line.tax_info.category if line.tax_info else ""
            mapping = profile.tax_mappings.get(source_tax)
            if (
                source_tax != target["source_tax_identity"]
                or mapping is None
                or mapping.status is not MappingStatus.USER_CONFIRMED
                or not mapping.metadata.get("jdl_evidence_id")
            ):
                raise ExactShapeProbeError("required tax mapping lacks Human confirmation or Evidence")
            if source_tax == "対象外":
                target.update({"scope": "", "category": "", "input_method": "", "tax_amount": "", "human_confirmed": True})
            elif source_tax == "課税仕入 10%":
                tax_amount = (line.amount * Decimal("10") / Decimal("110")).quantize(Decimal("1"), rounding=ROUND_DOWN)
                target.update({"scope": "仕　入", "category": "10%", "input_method": "内税", "tax_amount": str(tax_amount), "human_confirmed": True})
            else:
                raise ExactShapeProbeError("tax identity is outside existing exact Evidence")
    if output_dir.exists():
        raise FileExistsError("probe output directory already exists")
    output_dir.mkdir(parents=True)
    config["probe_date"] = probe_date
    config["target_master_identity_sha256"] = target_context_master_identity_sha256(context)
    config_path = output_dir / "confirmed_config.private.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return generate(source, config_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("skeleton", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("company_id")
    parser.add_argument("company_root", type=Path)
    parser.add_argument("profile_root", type=Path)
    parser.add_argument("--probe-date", required=True)
    args = parser.parse_args()
    print(prepare_and_generate(
        args.source, args.skeleton, args.output_dir, args.company_id,
        args.company_root, args.profile_root, probe_date=args.probe_date,
    ))


if __name__ == "__main__":
    main()

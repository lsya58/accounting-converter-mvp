from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.adapters.output.jdl import (
    JdlContextConfirmationState,
    JdlContextProvenance,
)
from accounting_converter.infrastructure.company_setting_store import (
    CompanySettingStore,
    default_company_store_dir,
)
from accounting_converter.infrastructure.conversion_profile_store import (
    ConversionProfileStore,
    default_profile_store_dir,
)
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.application.jdl_master_identity import target_context_master_identity_sha256
from accounting_converter.profiles.known_formats import (
    moneyforward_cloud_journal_export_observed_schema,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


def identity_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_snapshot(setting, profile, context) -> dict[str, object]:
    source_key = moneyforward_cloud_journal_export_observed_schema().identity.stable_key
    target_key = jdl_ibex_cashbook_official_journal_import_schema_definition().identity.stable_key
    if (
        profile.source_format_identity.stable_key != source_key
        or profile.target_format_identity.stable_key != target_key
        or setting.expected_source_format_key != source_key
        or setting.expected_target_format_key != target_key
    ):
        raise ValueError("only the exact MF-to-JDL company route may be exported")
    if context.product != "JDL IBEX 出納帳" or context.version != "35.5":
        raise ValueError("target product/version is outside this probe scope")
    if (
        context.confirmation_state is not JdlContextConfirmationState.CONFIRMED
        or context.provenance is not JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT
    ):
        raise ValueError("target tax context is not Human-confirmed")

    accounts = []
    for source, mapping in sorted(profile.account_mappings.items()):
        if mapping.status is MappingStatus.USER_CONFIRMED:
            accounts.append({
                "source_identity_sha256": identity_hash(source),
                "target_code": str(mapping.metadata.get("target_code", "")),
                "status": "USER_CONFIRMED",
            })
    subaccounts = []
    for key, mapping in sorted(profile.subaccount_context_mappings.items(), key=lambda item: item[0].stable_key):
        if mapping.status is MappingStatus.USER_CONFIRMED:
            subaccounts.append({
                "source_parent_sha256": identity_hash(key.parent_account or ""),
                "source_subaccount_sha256": identity_hash(key.source_value),
                "target_code": str(mapping.metadata.get("target_code", "")),
                "output_code": str(mapping.metadata.get("output_code", "")),
                "policy": str(mapping.metadata.get("subaccount_policy", "")),
                "status": "USER_CONFIRMED",
            })
    taxes = [
        {"source_identity": source, "status": mapping.status.value}
        for source, mapping in sorted(profile.tax_mappings.items())
    ]
    return {
        "schema_version": "1",
        "NOT_FOR_PRODUCTION": True,
        "production_allowed": False,
        "company_setting_id": setting.company_setting_id,
        "profile_revision_id": profile.profile_id,
        "profile_fingerprint": setting.profile_fingerprint,
        "context_fingerprint": setting.context_fingerprint,
        "target_master_identity_sha256": target_context_master_identity_sha256(context),
        "source_format_key": source_key,
        "target_format_key": target_key,
        "product": context.product,
        "version": context.version,
        "tax_context": {
            "processing": context.tax_processing_mode.value,
            "taxation": context.effective_taxation_method.value,
            "credit_method": context.effective_input_tax_credit_method.value,
            "business_category": (
                context.simplified_business_category.value
                if context.simplified_business_category else None
            ),
            "confirmation_state": context.confirmation_state.value,
        },
        "confirmed_accounts": accounts,
        "confirmed_subaccounts": subaccounts,
        "tax_mapping_states": taxes,
    }


def export_snapshot(company_setting_id: str, destination: Path, *, company_root: Path | None = None, profile_root: Path | None = None) -> Path:
    private_root = (Path.cwd() / "data" / "private").resolve()
    if not destination.resolve().is_relative_to(private_root):
        raise ValueError("probe snapshot must be written under data/private")
    if destination.exists():
        raise FileExistsError("probe snapshot already exists")
    profiles = ConversionProfileStore(profile_root or default_profile_store_dir())
    companies = CompanySettingStore(company_root or default_company_store_dir(), profiles)
    setting = companies.get(company_setting_id)
    profile = profiles.get(setting.conversion_profile_id)
    context_path = companies.context_path(setting)
    if (
        setting.profile_fingerprint != hashlib.sha256(profiles.to_json_text(profile).encode("utf-8")).hexdigest()
        or setting.context_fingerprint != hashlib.sha256(context_path.read_bytes()).hexdigest()
    ):
        raise ValueError("company/profile/context revision is stale")
    context = JdlTargetContextLoader().load(context_path)
    payload = build_snapshot(setting, profile, context)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".probe-snapshot-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Private, read-only MF probe mapping snapshot")
    parser.add_argument("company_setting_id")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(export_snapshot(args.company_setting_id, args.destination))


if __name__ == "__main__":
    main()

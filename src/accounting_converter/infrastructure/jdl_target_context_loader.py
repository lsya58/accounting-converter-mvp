from __future__ import annotations

import json
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlDepartmentIdentity,
    JdlInputTaxCreditMethod,
    JdlSimplifiedBusinessCategory,
    JdlSubaccountIdentity,
    JdlTaxationMethod,
    JdlTargetContext,
    JdlTargetContextBuilder,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class JdlTargetContextLoadError(ValueError):
    pass


class JdlTargetContextLoader:
    """Loads an explicitly selected, local JDL target snapshot."""

    SCHEMA_VERSION = "2"

    def to_json_text(self, context: JdlTargetContext) -> str:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "product": context.product,
            "version": context.version,
            "account_master": [
                {
                    "mapping_value": item.mapping_value,
                    "target_master_code": item.target_master_code,
                    "target_name": item.target_name,
                    "target_formal_name": item.target_formal_name,
                }
                for item in context.account_master
            ],
            "subaccounts": [item.__dict__ for item in context.subaccounts],
            "departments": [item.__dict__ for item in context.departments],
            "tax_processing_mode": context.tax_processing_mode.value,
            "department_processing_enabled": context.department_processing_enabled,
            "standard_taxation_confirmed": context.standard_taxation_confirmed,
            "individual_credit_method_confirmed": (
                context.individual_credit_method_confirmed
            ),
            "taxation_method": context.effective_taxation_method.value,
            "input_tax_credit_method": (
                context.effective_input_tax_credit_method.value
            ),
            "simplified_business_category": (
                context.simplified_business_category.value
                if context.simplified_business_category is not None
                else None
            ),
            "confirmation_state": context.confirmation_state.value,
            "provenance": context.provenance.value,
            "no_fuzzy_matching": context.no_fuzzy_matching,
            "no_automatic_replacement": context.no_automatic_replacement,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def load(self, path: Path) -> JdlTargetContext:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            schema_version = str(payload.get("schema_version", ""))
            if schema_version not in {"1", self.SCHEMA_VERSION}:
                raise JdlTargetContextLoadError("unsupported context schema version")
            legacy_standard = bool(payload.get("standard_taxation_confirmed", False))
            legacy_individual = bool(
                payload.get("individual_credit_method_confirmed", False)
            )
            result = JdlTargetContextBuilder().build(
                target_format_identity=(
                    jdl_ibex_cashbook_official_journal_import_schema_definition().identity
                ),
                product=str(payload["product"]),
                version=str(payload["version"]),
                account_master=tuple(
                    JdlAccountIdentity(
                        mapping_value=str(item["mapping_value"]),
                        target_master_code=str(item["target_master_code"]),
                        target_name=str(item["target_name"]),
                        target_formal_name=str(item["target_formal_name"]),
                    )
                    for item in payload.get("account_master", [])
                ),
                subaccounts=tuple(
                    JdlSubaccountIdentity(**item)
                    for item in payload.get("subaccounts", [])
                ),
                departments=tuple(
                    JdlDepartmentIdentity(**item)
                    for item in payload.get("departments", [])
                ),
                tax_processing_mode=JdlTaxProcessingMode(payload["tax_processing_mode"]),
                department_processing_enabled=bool(
                    payload["department_processing_enabled"]
                ),
                standard_taxation_confirmed=legacy_standard,
                individual_credit_method_confirmed=legacy_individual,
                taxation_method=JdlTaxationMethod(
                    payload.get(
                        "taxation_method",
                        "STANDARD" if legacy_standard else "UNCONFIRMED",
                    )
                ),
                input_tax_credit_method=JdlInputTaxCreditMethod(
                    payload.get(
                        "input_tax_credit_method",
                        "INDIVIDUAL" if legacy_individual else "UNCONFIRMED",
                    )
                ),
                simplified_business_category=(
                    JdlSimplifiedBusinessCategory(
                        payload["simplified_business_category"]
                    )
                    if payload.get("simplified_business_category")
                    else None
                ),
                confirmation_state=JdlContextConfirmationState(
                    payload["confirmation_state"]
                ),
                provenance=JdlContextProvenance(payload["provenance"]),
                no_fuzzy_matching=bool(payload.get("no_fuzzy_matching", False)),
                no_automatic_replacement=bool(
                    payload.get("no_automatic_replacement", False)
                ),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, JdlTargetContextLoadError):
                raise
            raise JdlTargetContextLoadError("JDL設定ファイルを読み込めません。") from exc
        if not result.success or result.context is None:
            raise JdlTargetContextLoadError("JDL設定ファイルの確認に失敗しました。")
        return result.context

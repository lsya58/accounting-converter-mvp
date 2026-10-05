from __future__ import annotations

import json
from pathlib import Path

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlDepartmentIdentity,
    JdlSubaccountIdentity,
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

    SCHEMA_VERSION = "1"

    def load(self, path: Path) -> JdlTargetContext:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.SCHEMA_VERSION:
                raise JdlTargetContextLoadError("unsupported context schema version")
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
                standard_taxation_confirmed=bool(
                    payload.get("standard_taxation_confirmed", False)
                ),
                individual_credit_method_confirmed=bool(
                    payload.get("individual_credit_method_confirmed", False)
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

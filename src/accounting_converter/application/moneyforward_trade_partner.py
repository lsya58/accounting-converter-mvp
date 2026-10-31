from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Sequence

from accounting_converter.application.journal_route import JournalRouteResult
from accounting_converter.application.moneyforward_tax_excluded_evidence import (
    tax_context_identity_sha256,
)
from accounting_converter.application.description_replacement import JDL_DESCRIPTION_LIMIT
from accounting_converter.domain.conversion_profile import (
    ConversionProfile,
    LossPolicy,
    TRADE_PARTNER_LOSS_POLICY_KEY,
    TRADE_PARTNER_TRANSFORMATION_KEY,
)
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.domain.validation import Severity, ValidationResult
from accounting_converter.infrastructure.jdl_target_context_loader import (
    JdlTargetContextLoader,
)


TRADE_PARTNER_DESCRIPTION_PREFIX = "取引先:"
TRADE_PARTNER_DESCRIPTION_SEPARATOR = " / "
TRADE_PARTNER_POLICY_SCOPE_KEY = "trade_partner_policy_scope_sha256"
TRADE_PARTNER_CAPABILITY_KEY = "trade_partner_target_capability_sha256"


def trade_partner_target_capability_sha256(context: object) -> str | None:
    identity = getattr(context, "target_format_identity", None)
    product = getattr(context, "product", None)
    version = getattr(context, "version", None)
    if identity is None or not product or not version:
        return None
    payload = {
        "target_format": identity.stable_key,
        "product": product,
        "version": version,
        "description_encoding": "cp932",
        "description_limit": JDL_DESCRIPTION_LIMIT,
        "description_prefix": TRADE_PARTNER_DESCRIPTION_PREFIX,
        "description_separator": TRADE_PARTNER_DESCRIPTION_SEPARATOR,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def trade_partner_policy_context_matches(metadata, context: object) -> bool:
    capability = metadata.get(TRADE_PARTNER_CAPABILITY_KEY)
    if capability is not None:
        current = trade_partner_target_capability_sha256(context)
        return current is not None and capability == current
    scoped = metadata.get(TRADE_PARTNER_POLICY_SCOPE_KEY)
    if scoped is not None:
        return scoped == tax_context_identity_sha256(context)
    legacy = hashlib.sha256(
        JdlTargetContextLoader().to_json_text(context).encode("utf-8")
    ).hexdigest()
    if metadata.get("jdl_context_sha256") == legacy:
        return True
    # Policies saved before the capability key existed only carry a whole-context
    # hash, which changes on every unrelated tax/master update. Such a policy
    # could only be confirmed against the 35.5 1D1C Evidence, so it keeps the
    # same capability boundary as a newly saved one: valid while the target
    # format/product/version still equal that Evidence's capability.
    current = trade_partner_target_capability_sha256(context)
    return bool(
        metadata.get("jdl_context_sha256")
        and metadata.get("jdl_evidence_id") == TRADE_PARTNER_1D1C_EVIDENCE_ID
        and current is not None
        and current == _legacy_evidence_capability_sha256()
    )


def _legacy_evidence_capability_sha256() -> str | None:
    from types import SimpleNamespace

    from accounting_converter.profiles.known_formats import (
        jdl_ibex_cashbook_official_journal_import_schema_definition,
    )

    return trade_partner_target_capability_sha256(SimpleNamespace(
        target_format_identity=(
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        ),
        product="JDL IBEX 出納帳",
        version="35.5",
    ))


def upgrade_trade_partner_policy(mapping, old_context: object, new_context: object):
    if mapping is None:
        return None
    old_capability = trade_partner_target_capability_sha256(old_context)
    if (
        mapping.status is not MappingStatus.USER_CONFIRMED
        or mapping.target_value
        != LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value
        or mapping.metadata.get("jdl_evidence_id") != TRADE_PARTNER_1D1C_EVIDENCE_ID
        or not trade_partner_policy_context_matches(mapping.metadata, old_context)
        or old_capability is None
        or old_capability != trade_partner_target_capability_sha256(new_context)
    ):
        return mapping
    return replace(mapping, metadata={
        **mapping.metadata,
        TRADE_PARTNER_CAPABILITY_KEY: old_capability,
    })
TRADE_PARTNER_1D1C_EVIDENCE_ID = (
    "EVID-MF-JDL-TRADE-PARTNER-1D1C-DESCRIPTION-ROUNDTRIP-001"
)
TRADE_PARTNER_2D2C_TAXABLE_EVIDENCE_ID = (
    "EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-DESCRIPTION-ROUNDTRIP-001"
)
TRADE_PARTNER_2D2C_TAXABLE_NO_SUBACCOUNT_EVIDENCE_ID = (
    "EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-NO-SUBACCOUNT-"
    "DESCRIPTION-ROUNDTRIP-001"
)


class MoneyForwardTradePartnerDescriptionPolicy:
    """Applies one explicitly confirmed 1D1C trade-partner transformation."""

    def __init__(self, profile: ConversionProfile, context: object) -> None:
        self._profile = profile
        self._context = context

    def apply(self, entries: Sequence[JournalEntry]) -> JournalRouteResult:
        transformed: list[JournalEntry] = []
        errors: list[ValidationResult] = []
        for entry in entries:
            result, error = self._transform(entry)
            transformed.append(result)
            if error is not None:
                errors.append(error)
        return JournalRouteResult(tuple(transformed), tuple(errors))

    def _transform(
        self, entry: JournalEntry
    ) -> tuple[JournalEntry, ValidationResult | None]:
        marker = entry.metadata.get(TRADE_PARTNER_TRANSFORMATION_KEY)
        if marker is not None:
            expected = hashlib.sha256((entry.description or "").encode("utf-8")).hexdigest()
            if (
                isinstance(marker, dict)
                and marker.get("policy")
                == LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value
                and marker.get("target_description_sha256") == expected
            ):
                return entry, None
            return entry, self._error(entry, "MF-JDL-PARTNER-MARKER", "取引先変換の状態を確認できません。")

        partner_lines = tuple(
            line
            for line in entry.lines
            if line.metadata.get("moneyforward_trade_partner")
        )
        if not partner_lines:
            return entry, None

        policy = self._profile.loss_policy_mappings.get(
            TRADE_PARTNER_LOSS_POLICY_KEY
        )
        if (
            policy is None
            or policy.status is not MappingStatus.USER_CONFIRMED
            or policy.target_value
            != LossPolicy.APPEND_TRADE_PARTNER_TO_DESCRIPTION_CONFIRMED.value
            or not trade_partner_policy_context_matches(policy.metadata, self._context)
            or policy.metadata.get("jdl_evidence_id")
            != TRADE_PARTNER_1D1C_EVIDENCE_ID
        ):
            return entry, self._error(
                entry,
                "MF-JDL-PARTNER-POLICY",
                "取引先情報を摘要へ記録する設定の確認が必要です。",
            )

        debit_count = sum(line.side.value == "DEBIT" for line in entry.lines)
        credit_count = sum(line.side.value == "CREDIT" for line in entry.lines)
        sides = {line.side.value for line in partner_lines}
        partners = {
            str(line.metadata["moneyforward_trade_partner"])
            for line in partner_lines
        }
        if (debit_count, credit_count) not in {(1, 1), (2, 2)}:
            return entry, self._error(entry, "MF-JDL-PARTNER-SHAPE", "取引先付き複合仕訳は現在の対応範囲外です。")
        if len(sides) != 1 or len(partners) != 1:
            return entry, self._error(entry, "MF-JDL-PARTNER-IDENTITY", "複数側または複数の取引先を持つ仕訳は現在の対応範囲外です。")

        partner = next(iter(partners))
        suffix = f"{TRADE_PARTNER_DESCRIPTION_PREFIX}{partner}"
        source_description = entry.description
        if (debit_count, credit_count) == (2, 2):
            observed_description = partner_lines[0].metadata.get(
                "journal_row_description"
            )
            if not isinstance(observed_description, str):
                return entry, self._error(
                    entry,
                    "MF-JDL-PARTNER-ROW-DESCRIPTION",
                    "取引先を保持する行の摘要を確認できません。",
                )
            source_description = observed_description
        description = (
            f"{source_description}{TRADE_PARTNER_DESCRIPTION_SEPARATOR}{suffix}"
            if source_description
            else suffix
        )
        if len(description) > 32:
            return entry, self._error(entry, "MF-JDL-PARTNER-DESCRIPTION-LENGTH", "取引先を含む摘要がJDLの32文字制限を超えます。")
        try:
            description.encode("cp932", errors="strict")
        except UnicodeEncodeError:
            return entry, self._error(entry, "MF-JDL-PARTNER-DESCRIPTION-CP932", "取引先を含む摘要をJDLで表現できません。")

        lines = list(entry.lines)
        if (debit_count, credit_count) == (2, 2):
            row_number = partner_lines[0].metadata.get("journal_row_number")
            if not isinstance(row_number, int):
                return entry, self._error(entry, "MF-JDL-PARTNER-ROW", "取引先を保持する行を確認できません。")
            lines = [
                replace(
                    line,
                    metadata={**line.metadata, "journal_row_description": description},
                )
                if line.metadata.get("journal_row_number") == row_number
                else line
                for line in lines
            ]
            observed = tuple(
                {
                    **item,
                    "value": description,
                }
                if item.get("row_number") == row_number
                else item
                for item in entry.metadata.get("moneyforward_descriptions", ())
            )
        else:
            observed = entry.metadata.get("moneyforward_descriptions", ())
        metadata = {
            **entry.metadata,
            "moneyforward_descriptions": observed,
            TRADE_PARTNER_TRANSFORMATION_KEY: {
                "policy": policy.target_value,
                "source_side": next(iter(sides)),
                "jdl_combination_evidence_id": self._combination_evidence_id(
                    lines, debit_count, credit_count
                ),
                "target_description_sha256": hashlib.sha256(
                    description.encode("utf-8")
                ).hexdigest(),
            },
        }
        return replace(entry, lines=lines, description=description, metadata=metadata), None

    @staticmethod
    def _combination_evidence_id(
        lines: list, debit_count: int, credit_count: int
    ) -> str | None:
        if (debit_count, credit_count) != (2, 2):
            return None
        tax_lines = [
            line
            for line in lines
            if line.side.value == "DEBIT"
            and line.tax_info is not None
            and line.tax_info.category == "課税仕入 10%"
        ]
        if len(tax_lines) != 1:
            return None
        return (
            TRADE_PARTNER_2D2C_TAXABLE_EVIDENCE_ID
            if tax_lines[0].sub_account
            else TRADE_PARTNER_2D2C_TAXABLE_NO_SUBACCOUNT_EVIDENCE_ID
        )

    @staticmethod
    def _error(entry: JournalEntry, rule_id: str, message: str) -> ValidationResult:
        return ValidationResult(
            severity=Severity.ERROR,
            rule_id=rule_id,
            journal_id=entry.id,
            source_reference=entry.source_reference,
            field="trade_partner",
            message=message,
            suggested_action=(
                "会社設定の「取引先情報の扱い」で「取引先名を摘要に引き継ぐ」"
                "を確認してください。"
            ),
        )

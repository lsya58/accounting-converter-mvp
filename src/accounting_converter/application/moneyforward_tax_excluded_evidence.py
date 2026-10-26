from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN
import hashlib
import json

from accounting_converter.adapters.output.jdl import (
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlInputTaxCreditMethod,
    JdlTargetContext,
    JdlTaxationMethod,
)
from accounting_converter.domain.journal import JournalEntry, Side
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode


BATCH_EVIDENCE_ID = "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-BATCH-001"


def tax_context_identity_sha256(context: JdlTargetContext) -> str:
    payload = {
        "product": context.product,
        "version": context.version,
        "tax_processing_mode": context.tax_processing_mode.value,
        "taxation_method": context.effective_taxation_method.value,
        "input_tax_credit_method": context.effective_input_tax_credit_method.value,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MfTaxExcludedPatternEvidence:
    evidence_id: str
    account_signature: tuple[tuple[str, str, str, str], ...]
    profile: JdlEvidenceProfile
    trade_partner: bool = False


EVIDENCE = (
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P01-2D2C-PURCHASE-10-001", (("DEBIT","3231","","対象外"),("CREDIT","1311","0002","対象外"),("DEBIT","8681","","課税仕入 10%"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P02-OUT-3231-1311-SUB-001", (("DEBIT","3231","","対象外"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P03-OUT-3241-1311-SUB-001", (("DEBIT","3241","","対象外"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P04-PARTNER-001", (("DEBIT","8691","","課税仕入 10%"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111, True),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-001", (("DEBIT","8471","","課税仕入 10%"),("CREDIT","3181","","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P06-OUT-1311-SUB-3161-001", (("DEBIT","1311","0002","対象外"),("CREDIT","3161","","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-001", (("DEBIT","8481","","課税仕入 10%"),("CREDIT","3181","","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
)


def context_is_verified(context: JdlTargetContext) -> bool:
    return bool(
        context.product == "JDL IBEX 出納帳"
        and context.version == "35.5"
        and context.tax_processing_mode is JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED
        and context.effective_taxation_method is JdlTaxationMethod.STANDARD
        and context.effective_input_tax_credit_method is JdlInputTaxCreditMethod.PROPORTIONAL
        and context.confirmation_state is JdlContextConfirmationState.CONFIRMED
        and context.provenance is JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT
    )


def confirmed_mapping_is_in_scope(
    source_tax_category: str,
    mapping: MappingValue | None,
    context: JdlTargetContext,
) -> bool:
    """Check the Human tax choice against this narrow Evidence family."""
    expected = {
        "課税仕入 10%": ("10%", "仕　入"),
        "対象外": ("", ""),
    }.get(source_tax_category)
    return bool(
        expected is not None
        and mapping is not None
        and mapping.status is MappingStatus.USER_CONFIRMED
        and (mapping.target_value, mapping.metadata.get("jdl_tax_scope", ""))
        == expected
        and mapping.metadata.get("jdl_evidence_id") == BATCH_EVIDENCE_ID
        and mapping.metadata.get("jdl_tax_processing_mode")
        == context.tax_processing_mode.value
        and context_is_verified(context)
        and mapping.metadata.get("jdl_tax_context_identity_sha256")
        == tax_context_identity_sha256(context)
    )


def confirmed_mapping_mismatch_fields(
    source_tax_category: str,
    mapping: MappingValue | None,
    context: JdlTargetContext,
) -> tuple[str, ...]:
    expected = {
        "課税仕入 10%": ("10%", "仕　入"),
        "対象外": ("", ""),
    }.get(source_tax_category)
    mismatches: list[str] = []
    if not context_is_verified(context):
        mismatches.append("TAX_CONTEXT")
    if mapping is None or mapping.status is not MappingStatus.USER_CONFIRMED:
        return (*mismatches, "HUMAN_CONFIRMATION")
    if expected is None:
        mismatches.append("SOURCE_TAX_IDENTITY")
    else:
        if mapping.target_value != expected[0]:
            mismatches.append("TARGET_TAX_IDENTITY")
        if mapping.metadata.get("jdl_tax_scope", "") != expected[1]:
            mismatches.append("TARGET_TAX_SCOPE")
    if mapping.metadata.get("jdl_evidence_id") != BATCH_EVIDENCE_ID:
        mismatches.append("EVIDENCE_ID")
    if (
        mapping.metadata.get("jdl_tax_processing_mode")
        != context.tax_processing_mode.value
    ):
        mismatches.append("TAX_PROCESSING_MODE")
    saved_identity = mapping.metadata.get("jdl_tax_context_identity_sha256")
    if saved_identity != tax_context_identity_sha256(context):
        mismatches.append("TAX_CONTEXT_IDENTITY")
    return tuple(dict.fromkeys(mismatches))


def evidence_for_occurrence(
    source: JournalEntry, mapped: JournalEntry, context: JdlTargetContext
) -> MfTaxExcludedPatternEvidence | None:
    if not context_is_verified(context):
        return None
    signature = tuple(
        (
            source_line.side.value,
            _account_code(mapped_line.account, context),
            _subaccount_code(mapped_line.account, mapped_line.sub_account, context),
            source_line.tax_info.category if source_line.tax_info else "",
        )
        for source_line, mapped_line in zip(source.lines, mapped.lines, strict=True)
    )
    has_partner = any(
        bool(line.metadata.get("moneyforward_trade_partner")) for line in source.lines
    )
    return next(
        (
            item for item in EVIDENCE
            if item.account_signature == signature and item.trade_partner == has_partner
        ),
        None,
    )


def apply_verified_tax_semantics(
    source: JournalEntry,
    mapped: JournalEntry,
    context: JdlTargetContext,
) -> JournalEntry:
    evidence = evidence_for_occurrence(source, mapped, context)
    if evidence is None:
        return mapped
    lines = []
    for source_line, mapped_line in zip(source.lines, mapped.lines, strict=True):
        if source_line.tax_info and source_line.tax_info.category == "課税仕入 10%":
            info = replace(
                mapped_line.tax_info,
                category="10%",
                rate=Decimal("10"),
                tax_inclusion="INCLUDED",
                tax_amount=(mapped_line.amount * Decimal("10") / Decimal("110")).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                ),
                metadata={
                    **mapped_line.tax_info.metadata,
                    "jdl_tax_scope": "仕　入",
                    "jdl_tax_input_method": "内税",
                    "jdl_evidence_id": evidence.evidence_id,
                },
            )
            lines.append(replace(mapped_line, tax_info=info))
        else:
            lines.append(replace(mapped_line, tax_info=None))
    return replace(mapped, lines=lines)


def _account_code(value: str | None, context: JdlTargetContext) -> str:
    item = next((item for item in context.account_master if item.mapping_value == value), None)
    return item.target_master_code if item else ""


def _subaccount_code(
    account: str | None, value: str | None, context: JdlTargetContext
) -> str:
    if not value:
        return ""
    item = next(
        (
            item for item in context.subaccounts
            if item.parent_account == account and item.mapping_value == value
        ),
        None,
    )
    return item.output_code.zfill(4) if item else ""

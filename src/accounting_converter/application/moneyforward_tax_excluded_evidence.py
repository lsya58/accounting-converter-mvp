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
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    PARENT_ONLY_CANONICAL_SUBACCOUNT,
    canonical_subaccount_target,
    is_confirmed_parent_only,
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
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


@dataclass(frozen=True)
class MfTaxEvidenceMatchResult:
    evidence: MfTaxExcludedPatternEvidence | None
    actual_signature: tuple[tuple[str, str, str, str], ...]
    expected_signature: tuple[tuple[str, str, str, str], ...] | None
    mismatch_fields: tuple[str, ...]
    expected_evidence_id: str | None = None
    expected_pattern_id: str | None = None


@dataclass(frozen=True)
class CanonicalTargetIdentity:
    account_code: str
    subaccount_code: str
    mismatch_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class MfTaxEvidenceRegistry:
    """Select only a verified variant with an exact canonical dependency signature."""

    evidence: tuple[MfTaxExcludedPatternEvidence, ...]

    def exact(
        self,
        signature: tuple[tuple[str, str, str, str], ...],
        *,
        trade_partner: bool,
    ) -> MfTaxExcludedPatternEvidence | None:
        matches = tuple(
            item
            for item in self.evidence
            if item.account_signature == signature
            and item.trade_partner == trade_partner
        )
        return matches[0] if len(matches) == 1 else None


EVIDENCE = (
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P01-2D2C-PURCHASE-10-001", (("DEBIT","3231","","対象外"),("CREDIT","1311","0002","対象外"),("DEBIT","8681","","課税仕入 10%"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P02-OUT-3231-1311-SUB-001", (("DEBIT","3231","","対象外"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P03-OUT-3241-1311-SUB-001", (("DEBIT","3241","","対象外"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P04-PARTNER-001", (("DEBIT","8691","","課税仕入 10%"),("CREDIT","1311","0002","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111, True),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-001", (("DEBIT","8471","","課税仕入 10%"),("CREDIT","3181",PARENT_ONLY_CANONICAL_SUBACCOUNT,"対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P05-8471-3181-SUB0001-001", (("DEBIT","8471","","課税仕入 10%"),("CREDIT","3181","0001","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P06-OUT-1311-SUB-3161-001", (("DEBIT","1311","0002","対象外"),("CREDIT","3161","","対象外")), JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-001", (("DEBIT","8481","","課税仕入 10%"),("CREDIT","3181",PARENT_ONLY_CANONICAL_SUBACCOUNT,"対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence("EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P07-8481-3181-SUB0001-001", (("DEBIT","8481","","課税仕入 10%"),("CREDIT","3181","0001","対象外")), JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111),
    MfTaxExcludedPatternEvidence(
        "EVID-MF-JDL-35-5-1D2C-REAL-ROUNDTRIP-001",
        (("DEBIT", "7121", "", "課税仕入 10%"),
         ("CREDIT", "3141", "", "対象外"),
         ("CREDIT", "3271", "0002", "対象外")),
        JdlEvidenceProfile.MF_COMPOUND_1D2C_TAX_EXCLUDED_PROPORTIONAL,
    ),
)
EVIDENCE_REGISTRY = MfTaxEvidenceRegistry(EVIDENCE)


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
    source: JournalEntry,
    mapped: JournalEntry,
    context: JdlTargetContext,
    profile: ConversionProfile | None = None,
) -> MfTaxExcludedPatternEvidence | None:
    return match_evidence_for_occurrence(
        source, mapped, context, profile
    ).evidence


def match_evidence_for_occurrence(
    source: JournalEntry,
    mapped: JournalEntry,
    context: JdlTargetContext,
    profile: ConversionProfile | None = None,
) -> MfTaxEvidenceMatchResult:
    if not context_is_verified(context):
        return MfTaxEvidenceMatchResult(None, (), None, ("TAX_CONTEXT_MISMATCH",))
    identities = tuple(
        canonical_target_identity(
            source_account=source_line.account,
            source_subaccount=source_line.sub_account,
            side=source_line.side.value,
            mapped_account=mapped_line.account,
            mapped_subaccount=mapped_line.sub_account,
            context=context,
            profile=profile,
        )
        for source_line, mapped_line in zip(source.lines, mapped.lines, strict=True)
    )
    signature = tuple(
        (
            source_line.side.value,
            identity.account_code,
            identity.subaccount_code,
            source_line.tax_info.category if source_line.tax_info else "",
        )
        for source_line, identity in zip(source.lines, identities, strict=True)
    )
    has_partner = any(
        bool(line.metadata.get("moneyforward_trade_partner")) for line in source.lines
    )
    exact = EVIDENCE_REGISTRY.exact(
        signature,
        trade_partner=has_partner,
    )
    identity_mismatches = tuple(
        dict.fromkeys(
            field
            for identity in identities
            for field in identity.mismatch_fields
        )
    )
    if exact is not None and not identity_mismatches:
        return MfTaxEvidenceMatchResult(
            exact,
            signature,
            exact.account_signature,
            (),
            exact.evidence_id,
            _pattern_id(exact),
        )

    candidates = tuple(
        item for item in EVIDENCE
        if len(item.account_signature) == len(signature)
        and item.trade_partner == has_partner
        and tuple(row[0] for row in item.account_signature)
        == tuple(row[0] for row in signature)
    )
    expected = min(
        candidates,
        key=lambda item: sum(
            expected_field != actual_field
            for expected_row, actual_row in zip(
                item.account_signature, signature, strict=True
            )
            for expected_field, actual_field in zip(
                expected_row, actual_row, strict=True
            )
        ),
        default=None,
    )
    mismatches = list(identity_mismatches)
    if expected is None:
        mismatches.append("SHAPE_MISMATCH")
    else:
        for expected_row, actual_row in zip(
            expected.account_signature, signature, strict=True
        ):
            if expected_row[1] != actual_row[1]:
                mismatches.append("ACCOUNT_CODE_MISMATCH")
            if expected_row[2] != actual_row[2]:
                if (
                    not expected_row[2]
                    and actual_row[2]
                    and _target_subaccount_exists(
                        context, actual_row[1], actual_row[2]
                    )
                ):
                    mismatches.append("EVIDENCE_SCOPE_CHANGED_BY_MASTER")
                else:
                    mismatches.append("SUBACCOUNT_CODE_MISMATCH")
            if expected_row[3] != actual_row[3]:
                mismatches.append("TAX_CATEGORY_MISMATCH")
    return MfTaxEvidenceMatchResult(
        None,
        signature,
        expected.account_signature if expected is not None else None,
        tuple(dict.fromkeys(mismatches)),
        expected.evidence_id if expected is not None else None,
        _pattern_id(expected) if expected is not None else None,
    )


def _pattern_id(evidence: MfTaxExcludedPatternEvidence) -> str:
    for part in evidence.evidence_id.split("-"):
        if len(part) == 3 and part.startswith("P") and part[1:].isdigit():
            return part
    return "UNKNOWN"


def _target_subaccount_exists(
    context: JdlTargetContext,
    parent_code: str,
    subaccount_code: str,
) -> bool:
    return any(
        item.parent_account_code == parent_code
        and item.output_code.zfill(4) == subaccount_code.zfill(4)
        for item in context.subaccounts
    )


def canonical_target_identity(
    *,
    source_account: str | None,
    source_subaccount: str | None,
    side: str,
    mapped_account: str | None,
    mapped_subaccount: str | None,
    context: JdlTargetContext,
    profile: ConversionProfile | None,
) -> CanonicalTargetIdentity:
    account_code, account_mismatches = _account_code(
        source_account, mapped_account, context, profile
    )
    subaccount_code, subaccount_mismatches = _subaccount_code(
        source_account,
        source_subaccount,
        side,
        mapped_account,
        mapped_subaccount,
        account_code,
        context,
        profile,
    )
    return CanonicalTargetIdentity(
        account_code,
        subaccount_code,
        tuple(dict.fromkeys((*account_mismatches, *subaccount_mismatches))),
    )


def apply_verified_tax_semantics(
    source: JournalEntry,
    mapped: JournalEntry,
    context: JdlTargetContext,
    profile: ConversionProfile | None = None,
) -> JournalEntry:
    evidence = evidence_for_occurrence(source, mapped, context, profile)
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


def _account_code(
    source_value: str | None,
    mapped_value: str | None,
    context: JdlTargetContext,
    profile: ConversionProfile | None,
) -> tuple[str, tuple[str, ...]]:
    mapping = (
        profile.account_mappings.get(source_value or "")
        if profile is not None else None
    )
    if mapping is not None and mapping.status is MappingStatus.USER_CONFIRMED:
        code = mapping.metadata.get("target_code", "")
        matches = tuple(
            item for item in context.account_master
            if item.target_master_code == code
        )
        if len(matches) == 1:
            identity = matches[0]
            saved_names = {
                value for value in (
                    mapping.metadata.get("target_printed_name"),
                    mapping.metadata.get("target_formal_name"),
                ) if value
            }
            if not saved_names and mapping.target_value:
                saved_names.add(mapping.target_value)
            current_names = {
                identity.mapping_value,
                identity.target_name,
                identity.target_formal_name,
            }
            if saved_names & current_names:
                return code, ()
            return "", ("ACCOUNT_IDENTITY_MISMATCH",)
        return "", ("ACCOUNT_CODE_MISMATCH",)
    matches = tuple(
        item
        for item in context.account_master
        if mapped_value in {
            item.mapping_value,
            item.target_name,
            item.target_formal_name,
        }
    )
    if len(matches) == 1:
        return matches[0].target_master_code, ()
    return "", ("ACCOUNT_CODE_MISMATCH",)


def _subaccount_code(
    source_account: str | None,
    source_value: str | None,
    side: str,
    mapped_account: str | None,
    mapped_value: str | None,
    parent_code: str,
    context: JdlTargetContext,
    profile: ConversionProfile | None,
) -> tuple[str, tuple[str, ...]]:
    mapping = None
    if profile is not None and source_value:
        mapping = profile.subaccount_context_mappings.get(
            MappingKey(
                MappingType.SUBACCOUNT, source_value, source_account, side
            )
        )
    if is_confirmed_parent_only(mapping):
        if (
            canonical_subaccount_target(mapping)
            != PARENT_ONLY_CANONICAL_SUBACCOUNT
            or mapped_value not in {None, PARENT_ONLY_CANONICAL_SUBACCOUNT}
        ):
            return "", ("PARENT_ONLY_REPRESENTATION_MISMATCH",)
        return PARENT_ONLY_CANONICAL_SUBACCOUNT, ()
    if not mapped_value:
        return "", ()
    if mapping is not None and mapping.status is MappingStatus.USER_CONFIRMED:
        code = mapping.metadata.get("output_code") or mapping.metadata.get(
            "target_code", ""
        )
        matches = tuple(
            item for item in context.subaccounts
            if item.parent_account_code == parent_code
            and item.output_code.zfill(4) == code.zfill(4)
            and mapping.target_value in {
                item.mapping_value, item.target_name, item.output_name,
            }
            and mapped_value in {
                item.mapping_value, item.target_name, item.output_name,
            }
        )
        if len(matches) == 1:
            return code.zfill(4), ()
        return "", ("SUBACCOUNT_CODE_MISMATCH",)
    matches = tuple(
        item for item in context.subaccounts
        if (
            item.parent_account_code == parent_code
            or item.parent_account == mapped_account
        )
        and mapped_value in {
            item.mapping_value,
            item.target_name,
            item.output_name,
        }
    )
    if len(matches) == 1:
        return matches[0].output_code.zfill(4), ()
    return "", ("SUBACCOUNT_CODE_MISMATCH",)

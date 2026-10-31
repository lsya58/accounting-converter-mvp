from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
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
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, TaxInfo
from accounting_converter.domain.mf_outpur_scope import (
    OUTPUR_SHAPE_EVIDENCE_IDS,
    OUTPUR_TAX_MAPPING_EVIDENCE_ID,
    outpur_signature,
)
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
NONPUR_3181_EVIDENCE_ID = "EVID-MF-JDL-35-5-NONPUR-8571-3181-SUB0001-001"
NONPUR_1311_EVIDENCE_ID = "EVID-MF-JDL-35-5-NONPUR-8571-1311-SUB0002-001"
NONSALE_EVIDENCE_ID = "EVID-MF-JDL-35-5-NONSALE-1311-SUB0002-9111-001"
SALES10_EVIDENCE_ID = "EVID-MF-JDL-35-5-SALES10-1111-6121-ROUNDTRIP-001"
SALES10_9251_EVIDENCE_ID = "EVID-MF-JDL-35-5-SALES10-9251-ROUNDTRIP-001"
SALES10_ROUNDING_EVIDENCE_ID = "EVID-MF-JDL-35-5-SALES10-ROUNDING-6121-ROUNDTRIP-001"
# 0877: JDL kept an explicit floor tax (364458 -> 33132, half-up would be 33133)
# on 6121. Only this account is verified for floor/half-up-divergent amounts.
SALES10_ROUNDING_VERIFIED_ACCOUNTS = frozenset({"6121"})
COMPOSITION_ROUTE_ID = "MF-JDL-35-5-TAX-EXCLUDED-PROPORTIONAL-CAPABILITY-COMPOSITION-V1"

MF_SALES_10 = "課税売上 10%"
MF_PURCHASE_10 = "課税仕入 10%"
MF_NON_TAXABLE_PURCHASE = "非課税仕入"
MF_NON_TAXABLE_SALES = "非課税売上"
MF_OUT_OF_SCOPE = "対象外"
MF_OUT_OF_SCOPE_PURCHASE = "対象外仕入"

# Human tax mapping in this Context: MF identity -> (JDL 税区, JDL 課区, Evidence
# that verified this exact JDL literal by real Import and re-export).
TAX_MAPPING_SPECS: dict[str, tuple[str, str, str]] = {
    MF_PURCHASE_10: ("10%", "仕　入", BATCH_EVIDENCE_ID),
    MF_OUT_OF_SCOPE: ("", "", BATCH_EVIDENCE_ID),
    MF_OUT_OF_SCOPE_PURCHASE: ("", "", OUTPUR_TAX_MAPPING_EVIDENCE_ID),
    MF_NON_TAXABLE_PURCHASE: ("", "非仕入", NONPUR_3181_EVIDENCE_ID),
    MF_NON_TAXABLE_SALES: ("", "非売上", NONSALE_EVIDENCE_ID),
    MF_SALES_10: ("10%", "売　上", SALES10_EVIDENCE_ID),
}


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
    # Set only for a composed route: the real Evidence behind each capability.
    supporting_evidence_ids: tuple[str, ...] = ()


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
    MfTaxExcludedPatternEvidence(
        OUTPUR_SHAPE_EVIDENCE_IDS[(4, 6)], outpur_signature((4, 6)),
        JdlEvidenceProfile.MF_OUTPUR_COMPOUND_4D6C,
    ),
    MfTaxExcludedPatternEvidence(
        OUTPUR_SHAPE_EVIDENCE_IDS[(5, 7)], outpur_signature((5, 7)),
        JdlEvidenceProfile.MF_OUTPUR_COMPOUND_5D7C,
    ),
    MfTaxExcludedPatternEvidence(
        OUTPUR_SHAPE_EVIDENCE_IDS[(5, 8)], outpur_signature((5, 8)),
        JdlEvidenceProfile.MF_OUTPUR_COMPOUND_5D8C,
    ),
    MfTaxExcludedPatternEvidence(
        NONPUR_3181_EVIDENCE_ID,
        (("DEBIT", "8571", "", MF_NON_TAXABLE_PURCHASE),
         ("CREDIT", "3181", "0001", MF_OUT_OF_SCOPE)),
        JdlEvidenceProfile.MF_NONPUR_PROPORTIONAL_1111,
    ),
    MfTaxExcludedPatternEvidence(
        NONPUR_1311_EVIDENCE_ID,
        (("DEBIT", "8571", "", MF_NON_TAXABLE_PURCHASE),
         ("CREDIT", "1311", "0002", MF_OUT_OF_SCOPE)),
        JdlEvidenceProfile.MF_NONPUR_PROPORTIONAL_1111,
    ),
    MfTaxExcludedPatternEvidence(
        NONSALE_EVIDENCE_ID,
        (("DEBIT", "1311", "0002", MF_OUT_OF_SCOPE),
         ("CREDIT", "9111", "", MF_NON_TAXABLE_SALES)),
        JdlEvidenceProfile.MF_NONSALE_PROPORTIONAL_1111,
    ),
    MfTaxExcludedPatternEvidence(
        SALES10_EVIDENCE_ID,
        (("DEBIT", "1111", "", MF_OUT_OF_SCOPE),
         ("CREDIT", "6121", "", MF_SALES_10)),
        JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111,
    ),
    MfTaxExcludedPatternEvidence(
        SALES10_9251_EVIDENCE_ID,
        (("DEBIT", "3181", "0001", MF_OUT_OF_SCOPE),
         ("CREDIT", "9251", "", MF_SALES_10)),
        JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111,
    ),
)
EVIDENCE_REGISTRY = MfTaxEvidenceRegistry(EVIDENCE)

# Composition is only allowed for these source tax identities. 対象外仕入 stays
# exact-only because its Evidence is a single 1D1C pair plus three fixed shapes.
COMPOSABLE_TAX_IDENTITIES = frozenset({
    MF_OUT_OF_SCOPE, MF_PURCHASE_10, MF_SALES_10,
    MF_NON_TAXABLE_PURCHASE, MF_NON_TAXABLE_SALES,
})
# A tax line capability is treated as account-independent only when real
# Evidence shows the same JDL representation surviving Import/re-export on at
# least this many distinct target accounts on the same side. Otherwise it is
# limited to the exact accounts that were verified.
ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS = 3
TAXED_IDENTITY_PROFILES_1D1C = {
    MF_PURCHASE_10: JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111,
    MF_SALES_10: JdlEvidenceProfile.MF_SALES10_EXCLUDED_PROPORTIONAL_1111,
    MF_NON_TAXABLE_PURCHASE: JdlEvidenceProfile.MF_NONPUR_PROPORTIONAL_1111,
    MF_NON_TAXABLE_SALES: JdlEvidenceProfile.MF_NONSALE_PROPORTIONAL_1111,
}
# Shapes whose grouping/row order is verified in this Tax Context, with the
# Evidence for that shape. 2D2C is P01 (one 課税仕入 10% debit row).
COMPOSABLE_SHAPES = {
    (1, 1): BATCH_EVIDENCE_ID,
    (2, 2): "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P01-2D2C-PURCHASE-10-001",
}
# Other compound shapes in this Context use one generic serializer. A shape is
# released only after its own real round trip; until then it stays PENDING.
# Verified by the 0877 final batch (2026-05-29, strict PASS per case).
VERIFIED_COMPOUND_SHAPES: dict[tuple[int, int], str] = {
    (2, 1): "EVID-MF-JDL-35-5-2D1C-PURCHASE10-ROUNDTRIP-001",
    (2, 3): "EVID-MF-JDL-35-5-2D3C-PURCHASE10-ROUNDTRIP-001",
    (10, 9): "EVID-MF-JDL-35-5-10D9C-ROUNDTRIP-001",
}
PENDING_COMPOUND_SHAPE_EVIDENCE: dict[tuple[int, int], str] = {}
TRADE_PARTNER_DESCRIPTION_EVIDENCE = {
    (1, 1): "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P04-PARTNER-001",
    (2, 2): "EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-NO-SUBACCOUNT-DESCRIPTION-ROUNDTRIP-001",
}


@dataclass(frozen=True)
class TaxLineCapability:
    side: str
    source_tax: str
    verified_accounts: frozenset[str]
    evidence_ids: tuple[str, ...]

    @property
    def account_independent(self) -> bool:
        return len(self.verified_accounts) >= ACCOUNT_INDEPENDENCE_MIN_ACCOUNTS

    def covers(self, account_code: str) -> bool:
        return self.account_independent or account_code in self.verified_accounts


def verified_mf_shapes() -> frozenset[tuple[int, int]]:
    """(debit, credit) shapes with real JDL Evidence in this Tax Context."""
    exact = {
        (
            sum(row[0] == "DEBIT" for row in item.account_signature),
            sum(row[0] == "CREDIT" for row in item.account_signature),
        )
        for item in EVIDENCE
    }
    return frozenset(exact | set(COMPOSABLE_SHAPES) | set(VERIFIED_COMPOUND_SHAPES))


def _line_capabilities() -> dict[tuple[str, str], TaxLineCapability]:
    accounts: dict[tuple[str, str], set[str]] = {}
    evidence_ids: dict[tuple[str, str], list[str]] = {}
    for item in EVIDENCE:
        for side, account, _subaccount, tax in item.account_signature:
            if tax not in COMPOSABLE_TAX_IDENTITIES or not account:
                continue
            accounts.setdefault((side, tax), set()).add(account)
            ids = evidence_ids.setdefault((side, tax), [])
            if item.evidence_id not in ids:
                ids.append(item.evidence_id)
    return {
        key: TaxLineCapability(
            key[0], key[1], frozenset(accounts[key]), tuple(evidence_ids[key])
        )
        for key in accounts
    }


LINE_CAPABILITIES = _line_capabilities()


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
    spec = TAX_MAPPING_SPECS.get(source_tax_category)
    return bool(
        spec is not None
        and mapping is not None
        and mapping.status is MappingStatus.USER_CONFIRMED
        and (mapping.target_value, mapping.metadata.get("jdl_tax_scope", ""))
        == spec[:2]
        and mapping.metadata.get("jdl_evidence_id") == spec[2]
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
    spec = TAX_MAPPING_SPECS.get(source_tax_category)
    expected = spec[:2] if spec is not None else None
    evidence_id = spec[2] if spec is not None else None
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
    if mapping.metadata.get("jdl_evidence_id") != evidence_id:
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
    composition_gaps: tuple[str, ...] = ()
    if not identity_mismatches:
        composed, composition_gaps = compose_capabilities(
            source, signature, has_partner=has_partner, context=context
        )
        if composed is not None:
            return MfTaxEvidenceMatchResult(
                composed,
                signature,
                composed.account_signature,
                (),
                composed.evidence_id,
                "COMPOSED",
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
    mismatches = [*identity_mismatches, *composition_gaps]
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


def compose_capabilities(
    source: JournalEntry,
    signature: tuple[tuple[str, str, str, str], ...],
    *,
    has_partner: bool,
    context: JdlTargetContext,
) -> tuple[MfTaxExcludedPatternEvidence | None, tuple[str, ...]]:
    """Release a journal only when every independent capability has Evidence.

    Formal READY = shape AND every tax line AND account/subaccount AND
    description (trade partner). Each part cites the real JDL Evidence behind
    it; anything without Evidence returns a gap code instead.
    """
    gaps: list[str] = []
    support: list[str] = []
    debit_count = sum(row[0] == "DEBIT" for row in signature)
    shape = (debit_count, len(signature) - debit_count)
    shape_evidence = COMPOSABLE_SHAPES.get(shape) or VERIFIED_COMPOUND_SHAPES.get(shape)
    if shape_evidence is None:
        gaps.append("SHAPE_UNVERIFIED_IN_TAX_CONTEXT")
    else:
        support.append(shape_evidence)
    taxed: list[tuple[JournalLine, str, str]] = []
    for line, (side, account, subaccount, tax) in zip(
        source.lines, signature, strict=True
    ):
        if not account:
            gaps.append("ACCOUNT_CODE_MISMATCH")
            continue
        if subaccount in {"", PARENT_ONLY_CANONICAL_SUBACCOUNT} and any(
            item.parent_account_code == account for item in context.subaccounts
        ):
            # JDL rejected blank subaccounts on 1311/1551 when the master has
            # subaccounts. Only an explicit Human target subaccount can fix it.
            gaps.append("SUBACCOUNT_REQUIRED_BY_MASTER")
        if tax not in COMPOSABLE_TAX_IDENTITIES:
            gaps.append("TAX_IDENTITY_NOT_COMPOSABLE")
            continue
        capability = LINE_CAPABILITIES.get((side, tax))
        if capability is None:
            gaps.append("TAX_SIDE_UNVERIFIED")
            continue
        if not capability.covers(account):
            gaps.append("TAX_ACCOUNT_UNVERIFIED")
            continue
        support.extend(capability.evidence_ids)
        if tax != MF_OUT_OF_SCOPE:
            taxed.append((line, tax, subaccount))
        if (
            tax == MF_SALES_10
            and not _tax_rounding_is_unambiguous(line.amount)
            and account not in SALES10_ROUNDING_VERIFIED_ACCOUNTS
        ):
            gaps.append("TAX_AMOUNT_ROUNDING_UNVERIFIED")
        elif tax == MF_SALES_10 and not _tax_rounding_is_unambiguous(line.amount):
            support.append(SALES10_ROUNDING_EVIDENCE_ID)
    generic_compound = shape in VERIFIED_COMPOUND_SHAPES
    if len(taxed) > 1 and not generic_compound:
        gaps.append("MULTIPLE_TAXED_LINES_UNVERIFIED")
    profile: JdlEvidenceProfile | None = None
    if shape == (1, 1) and len(taxed) <= 1:
        profile = (
            TAXED_IDENTITY_PROFILES_1D1C[taxed[0][1]]
            if taxed else JdlEvidenceProfile.MF_NO_TAX_PROPORTIONAL_1111
        )
    elif shape == (2, 2):
        if (
            len(taxed) != 1
            or taxed[0][1] != MF_PURCHASE_10
            or taxed[0][0].side is not Side.DEBIT
        ):
            gaps.append("SHAPE_TAX_COMBINATION_UNVERIFIED")
        else:
            profile = JdlEvidenceProfile.MF_COMPOUND_2D2C_TAX_EXCLUDED_PROPORTIONAL
    elif generic_compound:
        profile = JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL
    if has_partner:
        partner_evidence = TRADE_PARTNER_DESCRIPTION_EVIDENCE.get(shape)
        if partner_evidence is None:
            gaps.append("TRADE_PARTNER_SHAPE_UNVERIFIED")
        elif shape == (2, 2) and taxed and taxed[0][2]:
            support.append(
                "EVID-MF-JDL-TRADE-PARTNER-2D2C-TAXABLE-DESCRIPTION-ROUNDTRIP-001"
            )
        else:
            support.append(partner_evidence)
    if gaps or profile is None:
        return None, tuple(dict.fromkeys(gaps or ["SHAPE_TAX_COMBINATION_UNVERIFIED"]))
    return (
        MfTaxExcludedPatternEvidence(
            COMPOSITION_ROUTE_ID,
            signature,
            profile,
            has_partner,
            tuple(dict.fromkeys(support)),
        ),
        (),
    )


def _tax_rounding_is_unambiguous(amount: Decimal) -> bool:
    """Only amounts where floor and half-up agree match the verified 1100->100."""
    raw = amount * Decimal("10") / Decimal("110")
    return raw.quantize(Decimal("1"), rounding=ROUND_DOWN) == raw.quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )


def ten_percent_tax_amount(amount: Decimal) -> Decimal:
    return (amount * Decimal("10") / Decimal("110")).quantize(
        Decimal("1"), rounding=ROUND_DOWN
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
    return apply_tax_literals(source, mapped, evidence.evidence_id)


def apply_tax_literals(
    source: JournalEntry, mapped: JournalEntry, evidence_id: str
) -> JournalEntry:
    """Write the verified JDL tax literal for each MF tax identity.

    Callers decide whether the journal may use these literals; probe generation
    calls this directly with a PENDING Evidence ID, production only through
    apply_verified_tax_semantics.
    """
    lines = []
    for source_line, mapped_line in zip(source.lines, mapped.lines, strict=True):
        category = source_line.tax_info.category if source_line.tax_info else None
        if category == MF_PURCHASE_10:
            info = replace(
                mapped_line.tax_info,
                category="10%",
                rate=Decimal("10"),
                tax_inclusion="INCLUDED",
                tax_amount=ten_percent_tax_amount(mapped_line.amount),
                metadata={
                    **mapped_line.tax_info.metadata,
                    "jdl_tax_scope": "仕　入",
                    "jdl_tax_input_method": "内税",
                    "jdl_evidence_id": evidence_id,
                },
            )
            lines.append(replace(mapped_line, tax_info=info))
        elif category == MF_SALES_10:
            # 0872 literal: 売　上 / 10% / 外税 / explicit tax amount.
            info = TaxInfo(
                category="10%",
                rate=Decimal("10"),
                tax_inclusion="EXCLUDED",
                tax_amount=ten_percent_tax_amount(mapped_line.amount),
                metadata={
                    "jdl_tax_scope": "売　上",
                    "jdl_tax_input_method": "外税",
                    "jdl_evidence_id": evidence_id,
                },
            )
            lines.append(replace(mapped_line, tax_info=info))
        elif category in {MF_NON_TAXABLE_PURCHASE, MF_NON_TAXABLE_SALES}:
            # 0870/0876 literal: 課区 only; 税区, 税入力方法 and tax amount blank.
            info = TaxInfo(
                category="",
                metadata={
                    "jdl_tax_scope": TAX_MAPPING_SPECS[category][1],
                    "jdl_evidence_id": evidence_id,
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

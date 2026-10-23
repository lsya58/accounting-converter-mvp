from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from accounting_converter.adapters.input.jdl import jdl_source_tax_key
from accounting_converter.adapters.output.jdl import JdlTargetContext


JDL_TO_JDL_TARGET_MASTER_SHA256 = (
    "5c53f4a613b0046913b42a4af41fd89023477ff84d5cdc27abf799d2ef3ca822"
)
JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256 = (
    "c1a4edeb39a59aba8fcefd6fbe6a2db2095c02a30749a7cc7f9b0f9ba1a233b9"
)


def tax_context_identity_sha256(context: JdlTargetContext) -> str:
    """Hash only tax semantics that can affect Evidence activation."""
    payload = {
        "product": context.product,
        "version": context.version,
        "tax_processing_mode": context.tax_processing_mode.value,
        "taxation_method": context.effective_taxation_method.value,
        "input_tax_credit_method": context.effective_input_tax_credit_method.value,
        "simplified_business_category": (
            context.simplified_business_category.value
            if context.simplified_business_category is not None
            else None
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "product": "JDL IBEX 出納帳",
            "version": "35.5",
            "tax_processing_mode": "TAXABLE_TAX_INCLUDED",
            "taxation_method": "SIMPLIFIED",
            "input_tax_credit_method": "UNCONFIRMED",
            "simplified_business_category": "FIRST",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True)
class JdlMigrationTaxEvidence:
    evidence_id: str
    source_tax_key: str
    target_master_sha256: str
    confirmed_context_fingerprint: str | None = None
    required_account_identities: tuple[tuple[str, str], ...] = ()
    required_blank_subaccount_parent_codes: tuple[str, ...] = ()


JDL_MIGRATION_TAX_EVIDENCE = (
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-ROUNDTRIP-001",
        jdl_source_tax_key("売二種", "10%", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
        SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
        (("111", "現金"), ("612", "売上高")),
        ("111", "612"),
    ),
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
        SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
        (("111", "現金"), ("612", "売上高")),
        ("111", "612"),
    ),
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-NON-TAXABLE-SALES-ROUNDTRIP-001",
        jdl_source_tax_key("非売上", "", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
        SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
        (("111", "現金"), ("612", "売上高")),
        ("111", "612"),
    ),
)


def evidence_for_source_tax_key(
    source_tax_key: str,
) -> JdlMigrationTaxEvidence | None:
    """Return known Evidence without activating it for any target master."""
    return next(
        (
            item
            for item in JDL_MIGRATION_TAX_EVIDENCE
            if item.source_tax_key == source_tax_key
        ),
        None,
    )


def evidence_for(
    source_tax_key: str, target_master_sha256: str
) -> JdlMigrationTaxEvidence | None:
    return next(
        (
            item
            for item in JDL_MIGRATION_TAX_EVIDENCE
            if item.source_tax_key == source_tax_key
            and item.target_master_sha256 == target_master_sha256
        ),
        None,
    )


def evidence_for_master_identity(
    source_tax_key: str, target_master_identity_sha256: str
) -> JdlMigrationTaxEvidence | None:
    if target_master_identity_sha256 != JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256:
        return None
    return next(
        (
            item
            for item in JDL_MIGRATION_TAX_EVIDENCE
            if item.source_tax_key == source_tax_key
            and item.target_master_sha256 == JDL_TO_JDL_TARGET_MASTER_SHA256
        ),
        None,
    )


def evidence_for_target_context(
    source_tax_key: str, context: JdlTargetContext
) -> JdlMigrationTaxEvidence | None:
    """Activate Evidence only for the master identities used by its probe."""
    evidence = evidence_for_source_tax_key(source_tax_key)
    if evidence is None:
        return None
    if evidence.confirmed_context_fingerprint != tax_context_identity_sha256(context):
        return None
    if not target_master_dependencies_match(evidence, context):
        return None
    return evidence


def target_master_dependencies_match(
    evidence: JdlMigrationTaxEvidence, context: JdlTargetContext
) -> bool:
    """Check only target-master identities that the Evidence actually used."""
    return target_master_inventory_dependencies_match(
        evidence, context.account_master, context.subaccounts
    )


def target_master_inventory_dependencies_match(
    evidence: JdlMigrationTaxEvidence,
    accounts,
    subaccounts,
) -> bool:
    """Evaluate relevant master dependencies before tax context confirmation."""
    return not target_master_dependency_mismatches(
        evidence, accounts, subaccounts
    )


def target_master_dependency_mismatches(
    evidence: JdlMigrationTaxEvidence,
    accounts,
    subaccounts,
) -> tuple[str, ...]:
    by_code = {item.target_master_code: item for item in accounts}
    reasons: list[str] = []
    for code, formal_name in evidence.required_account_identities:
        account = by_code.get(code)
        if account is None:
            reasons.append(f"RELEVANT_ACCOUNT_CODE_MISSING:{code}")
        elif account.target_formal_name != formal_name:
            reasons.append(f"RELEVANT_ACCOUNT_NAME_MISMATCH:{code}")
    for code in evidence.required_blank_subaccount_parent_codes:
        if any(item.parent_account_code == code for item in subaccounts):
            reasons.append(f"RELEVANT_SUBACCOUNT_REQUIREMENT_CHANGED:{code}")
    return tuple(reasons)


def verified_tax_keys_for_target_context(
    context: JdlTargetContext,
) -> frozenset[str]:
    return frozenset(
        item.source_tax_key
        for item in JDL_MIGRATION_TAX_EVIDENCE
        if evidence_for_target_context(item.source_tax_key, context) is not None
    )


def evidence_supports_occurrence(
    source_tax_key: str,
    entry,
    taxed_line,
    context: JdlTargetContext,
) -> bool:
    """Match the route, shape, accounts and optional fields used by the probe."""
    evidence = evidence_for_target_context(source_tax_key, context)
    if evidence is None:
        return False
    if entry.metadata.get("source") != "jdl_30_column_migration_input":
        return False
    if tuple(entry.metadata.get("identifier_flags", ())) != ("1111",):
        return False
    if len(entry.metadata.get("physical_rows", ())) != 1 or len(entry.lines) != 2:
        return False
    debit = next((line for line in entry.lines if line.side.value == "DEBIT"), None)
    credit = next((line for line in entry.lines if line.side.value == "CREDIT"), None)
    if debit is None or credit is None or taxed_line is not credit:
        return False
    if (
        str(debit.metadata.get("jdl_source_account_code", "")),
        str(debit.metadata.get("jdl_source_account_formal_name", "")),
    ) != ("111", "現金"):
        return False
    if (
        str(credit.metadata.get("jdl_source_account_code", "")),
        str(credit.metadata.get("jdl_source_account_formal_name", "")),
    ) != ("612", "売上高"):
        return False
    if any(
        line.sub_account or line.department
        for line in (debit, credit)
    ):
        return False
    if debit.tax_info is not None:
        return False
    return bool(
        credit.tax_info is not None
        and credit.tax_info.category == source_tax_key
        and not credit.tax_info.tax_amount
    )


def verified_tax_keys_for_context(
    target_master_sha256: str, context_fingerprint: str
) -> frozenset[str]:
    """Activate Evidence only after its exact target context is confirmed."""
    return frozenset(
        item.source_tax_key
        for item in JDL_MIGRATION_TAX_EVIDENCE
        if item.target_master_sha256 == target_master_sha256
        and item.confirmed_context_fingerprint is not None
        and item.confirmed_context_fingerprint == context_fingerprint
    )


def verified_tax_keys_for_master_identity(
    target_master_identity_sha256: str, context_fingerprint: str
) -> frozenset[str]:
    if target_master_identity_sha256 != JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256:
        return frozenset()
    return frozenset(
        item.source_tax_key
        for item in JDL_MIGRATION_TAX_EVIDENCE
        if item.confirmed_context_fingerprint == context_fingerprint
    )

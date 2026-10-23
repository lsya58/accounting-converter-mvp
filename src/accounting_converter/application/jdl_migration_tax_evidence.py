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


@dataclass(frozen=True)
class JdlMigrationTaxOccurrenceEvidence:
    evidence_id: str
    source_tax_key: str
    occurrence_signature_sha256: str
    canonical_flag_sequence: tuple[str, ...] | None = None


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


JDL_MIGRATION_TAX_OCCURRENCE_EVIDENCE = (
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-COMPOUND-7ROW-DEPARTMENT-ROUNDTRIP-001",
        jdl_source_tax_key("売二種", "10%", ""),
        "840234453299a9409d405b84906d41d2ef261fd2a40608a698603dc956ca3297",
    ),
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-DEPARTMENT-ACCOUNT-A-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        "ea8adee6c522c33a03c0ebace619012f8a474322c319e1bdfa41fab27a6504e9",
    ),
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-DEPARTMENT-ACCOUNT-B-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        "eb2d4d265b9a494b06d63bba153df8250ba0f2a299723a48672fa764c9e7f278",
    ),
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1000-SUBACCOUNT-DEPARTMENT-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        "8728aa9748176495068924bf27b27fdd83ff1a76dcfabd36f85e713973277c4c",
    ),
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-1111-SUBACCOUNT-DEPARTMENT-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        "213abe9055da358877aa99c7e5020a6470893c9b954a8985f8dcd5be28b8ddeb",
    ),
    JdlMigrationTaxOccurrenceEvidence(
        "EVID-JDL-MIGRATION-NON-TAXABLE-1000-TO-1111-CANONICALIZATION-001",
        jdl_source_tax_key("非売上", "", ""),
        "aab34380bc65a32288ad9c01f1f6ddd060ad343167ff36c3d69efd13573fe4dd",
        ("1111",),
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
    return not evidence_occurrence_mismatches(
        source_tax_key, entry, taxed_line, context
    )


def evidence_occurrence_mismatches(
    source_tax_key: str,
    entry,
    taxed_line,
    context: JdlTargetContext,
) -> tuple[str, ...]:
    """Return stable reasons why a tax occurrence exceeds verified scope."""
    evidence = evidence_for_target_context(source_tax_key, context)
    if evidence is None:
        return ("CONTEXT_MISMATCH",)
    occurrence_signature = occurrence_signature_sha256(entry, taxed_line)
    if any(
        item.source_tax_key == source_tax_key
        and item.occurrence_signature_sha256 == occurrence_signature
        for item in JDL_MIGRATION_TAX_OCCURRENCE_EVIDENCE
    ):
        return ()
    reasons: list[str] = []
    if entry.metadata.get("source") != "jdl_30_column_migration_input":
        reasons.append("ROUTE_MISMATCH")
    if (
        tuple(entry.metadata.get("identifier_flags", ())) != ("1111",)
        or len(entry.metadata.get("physical_rows", ())) != 1
        or len(entry.lines) != 2
    ):
        reasons.append("SHAPE_MISMATCH")
    debit = next((line for line in entry.lines if line.side.value == "DEBIT"), None)
    credit = next((line for line in entry.lines if line.side.value == "CREDIT"), None)
    if debit is None or credit is None or taxed_line.side.value != "CREDIT":
        reasons.append("SIDE_MISMATCH")
    if debit is None or credit is None or (
        str(debit.metadata.get("jdl_source_account_code", "")),
        str(debit.metadata.get("jdl_source_account_formal_name", "")),
    ) != ("111", "現金"):
        reasons.append("ACCOUNT_SCOPE_MISMATCH")
    if credit is None or (
        str(credit.metadata.get("jdl_source_account_code", "")),
        str(credit.metadata.get("jdl_source_account_formal_name", "")),
    ) != ("612", "売上高"):
        if "ACCOUNT_SCOPE_MISMATCH" not in reasons:
            reasons.append("ACCOUNT_SCOPE_MISMATCH")
    if any(line.sub_account for line in entry.lines):
        reasons.append("SUBACCOUNT_SCOPE_MISMATCH")
    if any(line.department for line in entry.lines):
        reasons.append("OPTIONAL_FIELD_MISMATCH")
    if any(line is not taxed_line and line.tax_info is not None for line in entry.lines):
        reasons.append("OPPOSITE_TAX_MISMATCH")
    if (
        taxed_line.tax_info is None
        or taxed_line.tax_info.category != source_tax_key
        or taxed_line.tax_info.tax_amount
    ):
        reasons.append("TAX_SEMANTICS_MISMATCH")
    return tuple(reasons)


def occurrence_signature_sha256(entry, taxed_line) -> str:
    """Hash the exact private occurrence dependency without storing its values."""
    payload = {
        "route": entry.metadata.get("source"),
        "flags": tuple(entry.metadata.get("identifier_flags", ())),
        "taxed_side": taxed_line.side.value,
        "tax_key": taxed_line.tax_info.category if taxed_line.tax_info else None,
        "taxed_account_code": str(
            taxed_line.metadata.get("jdl_source_account_code", "")
        ),
        "taxed_account_name": str(
            taxed_line.metadata.get("jdl_source_account_formal_name", "")
        ),
        "taxed_line_has_subaccount": bool(taxed_line.sub_account),
        "other_line_has_subaccount": any(
            line.sub_account for line in entry.lines if line is not taxed_line
        ),
        "taxed_line_has_department": bool(taxed_line.department),
        "other_line_has_department": any(
            line.department for line in entry.lines if line is not taxed_line
        ),
        "opposite_tax_keys": tuple(
            line.tax_info.category
            for line in entry.lines
            if line is not taxed_line and line.tax_info is not None
        ),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_flag_normalization_evidence(
    entry, canonical_flags: tuple[str, ...]
) -> JdlMigrationTaxOccurrenceEvidence | None:
    tax_lines = tuple(line for line in entry.lines if line.tax_info is not None)
    if len(tax_lines) != 1:
        return None
    signature = occurrence_signature_sha256(entry, tax_lines[0])
    return next(
        (
            item
            for item in JDL_MIGRATION_TAX_OCCURRENCE_EVIDENCE
            if item.occurrence_signature_sha256 == signature
            and item.canonical_flag_sequence == canonical_flags
        ),
        None,
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

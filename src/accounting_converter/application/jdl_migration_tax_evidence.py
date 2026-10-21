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


JDL_MIGRATION_TAX_EVIDENCE = (
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-ROUNDTRIP-001",
        jdl_source_tax_key("売二種", "10%", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
        SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
    ),
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
        SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
    ),
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

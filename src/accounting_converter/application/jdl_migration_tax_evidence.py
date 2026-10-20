from __future__ import annotations

from dataclasses import dataclass

from accounting_converter.adapters.input.jdl import jdl_source_tax_key


JDL_TO_JDL_TARGET_MASTER_SHA256 = (
    "5c53f4a613b0046913b42a4af41fd89023477ff84d5cdc27abf799d2ef3ca822"
)


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
    ),
    JdlMigrationTaxEvidence(
        "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-ROUNDTRIP-001",
        jdl_source_tax_key("売五種", "10%", ""),
        JDL_TO_JDL_TARGET_MASTER_SHA256,
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

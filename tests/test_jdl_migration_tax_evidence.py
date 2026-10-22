from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from accounting_converter.adapters.input.jdl import jdl_source_tax_key
from accounting_converter.application.jdl_migration_tax_evidence import (
    JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256,
    JDL_TO_JDL_TARGET_MASTER_SHA256,
    SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
    evidence_for,
    evidence_for_master_identity,
    evidence_for_source_tax_key,
    verified_tax_keys_for_context,
    verified_tax_keys_for_master_identity,
)
from accounting_converter.adapters.output.jdl import (
    JdlSimplifiedBusinessCategory,
    JdlTargetContext,
    JdlTaxationMethod,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.application.jdl_migration_tax_evidence import (
    tax_context_identity_sha256,
)
from accounting_converter.tools.generate_jdl_migration_tax_probes import (
    compare_in_reexport,
)


class JdlMigrationTaxEvidenceTests(unittest.TestCase):
    ROOT = Path(__file__).parent / "evidence/e2e"
    CASES = (
        (
            "jdl_migration_tax_sales_second_10",
            "売二種",
            "EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-ROUNDTRIP-001",
        ),
        (
            "jdl_migration_tax_sales_fifth_10",
            "売五種",
            "EVID-JDL-MIGRATION-TAX-SALES-FIFTH-10-ROUNDTRIP-001",
        ),
    )

    def test_hashes_and_strict_roundtrips(self) -> None:
        for folder, scope, evidence_id in self.CASES:
            root = self.ROOT / folder
            expected = {}
            for line in (root / "SHA256SUMS").read_text("ascii").splitlines():
                digest, name = line.split("  ", 1)
                expected[name] = digest
            self.assertEqual(
                {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                    for name in expected
                },
                expected,
            )
            result = compare_in_reexport(
                root / "generated_jdl_candidate.csv",
                root / "jdl_reexport_batch.csv",
            )
            self.assertTrue(result["comparison_pass"])
            self.assertEqual(result["mismatched_fields"], [])
            evidence = evidence_for(
                jdl_source_tax_key(scope, "10%", ""),
                JDL_TO_JDL_TARGET_MASTER_SHA256,
            )
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.evidence_id, evidence_id)
            by_identity = evidence_for_master_identity(
                jdl_source_tax_key(scope, "10%", ""),
                JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256,
            )
            self.assertEqual(by_identity, evidence)

    def test_master_identity_mismatch_does_not_reuse_evidence(self) -> None:
        self.assertIsNone(
            evidence_for_master_identity(
                jdl_source_tax_key("売二種", "10%", ""), "wrong-master"
            )
        )
        self.assertEqual(
            verified_tax_keys_for_master_identity(
                "wrong-master", SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256
            ),
            frozenset(),
        )
        known = evidence_for_source_tax_key(
            jdl_source_tax_key("売二種", "10%", "")
        )
        self.assertIsNotNone(known)
        self.assertEqual(
            known.evidence_id,
            "EVID-JDL-MIGRATION-TAX-SALES-SECOND-10-ROUNDTRIP-001",
        )

    def test_evidence_does_not_activate_without_confirmed_context(self) -> None:
        self.assertEqual(
            verified_tax_keys_for_context(
                JDL_TO_JDL_TARGET_MASTER_SHA256, "unconfirmed-context"
            ),
            frozenset(),
        )

    def test_evidence_activates_only_for_exact_simplified_first_context(self) -> None:
        context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=JdlTaxationMethod.SIMPLIFIED,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
        )
        identity = tax_context_identity_sha256(context)
        self.assertEqual(identity, SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256)
        self.assertEqual(
            len(verified_tax_keys_for_context(
                JDL_TO_JDL_TARGET_MASTER_SHA256, identity
            )),
            2,
        )


if __name__ == "__main__":
    unittest.main()
    SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,

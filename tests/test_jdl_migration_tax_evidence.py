from __future__ import annotations

import hashlib
import csv
import io
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.input.jdl import (
    JdlMigrationParser,
    jdl_source_tax_key,
)
from accounting_converter.application.jdl_migration_tax_evidence import (
    JDL_TO_JDL_TARGET_MASTER_IDENTITY_SHA256,
    JDL_TO_JDL_TARGET_MASTER_SHA256,
    SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,
    evidence_for,
    evidence_for_master_identity,
    evidence_for_source_tax_key,
    evidence_for_target_context,
    evidence_supports_occurrence,
    target_master_dependency_mismatches,
    verified_tax_keys_for_context,
    verified_tax_keys_for_master_identity,
    verified_tax_keys_for_target_context,
)
from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlSimplifiedBusinessCategory,
    JdlSubaccountIdentity,
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
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
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
        (
            "jdl_migration_tax_non_taxable_sales",
            "非売上",
            "EVID-JDL-MIGRATION-TAX-NON-TAXABLE-SALES-ROUNDTRIP-001",
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
            category = "" if scope == "非売上" else "10%"
            evidence = evidence_for(
                jdl_source_tax_key(scope, category, ""),
                JDL_TO_JDL_TARGET_MASTER_SHA256,
            )
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.evidence_id, evidence_id)
            by_identity = evidence_for_master_identity(
                jdl_source_tax_key(scope, category, ""),
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
        context = self._context()
        identity = tax_context_identity_sha256(context)
        self.assertEqual(identity, SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256)
        self.assertEqual(
            len(verified_tax_keys_for_context(
                JDL_TO_JDL_TARGET_MASTER_SHA256, identity
            )),
            3,
        )

    def test_unrelated_account_and_subaccount_changes_preserve_evidence(self) -> None:
        context = self._context(
            extra_accounts=(JdlAccountIdentity("衛生費", "7742", "衛生費", "衛生費"),),
            extra_subaccounts=(self._subaccount("152", "売掛金"),),
        )

        self.assertIsNotNone(evidence_for_target_context(
            jdl_source_tax_key("売二種", "10%", ""), context
        ))
        self.assertEqual(len(verified_tax_keys_for_target_context(context)), 3)

    def test_non_taxable_sales_requires_exact_verified_route_and_shape(self) -> None:
        row = [""] * 30
        row[0:6] = ["1111", "1", "20260329", "111", "現金", "現金"]
        row[11:16] = ["1100", "0", "612", "売上高", "売上高"]
        row[18] = "非売上"
        row[21:24] = ["1100", "0", "JDL-MIG-TAX-NONTAX-SALES"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(jdl_ibex_cashbook_official_journal_import_spec().column_names)
        writer.writerow(row)
        entry = JdlMigrationParser().parse_text(stream.getvalue()).entries[0]
        taxed_line = next(line for line in entry.lines if line.tax_info is not None)
        key = jdl_source_tax_key("非売上", "", "")

        self.assertTrue(evidence_supports_occurrence(
            key, entry, taxed_line, self._context()
        ))
        changed = dict(taxed_line.metadata)
        changed["jdl_source_account_code"] = "613"
        changed_line = replace(taxed_line, metadata=changed)
        changed_entry = replace(
            entry,
            lines=tuple(
                changed_line if line is taxed_line else line for line in entry.lines
            ),
        )
        self.assertFalse(evidence_supports_occurrence(
            key, changed_entry, changed_line, self._context()
        ))

    def test_relevant_account_change_blocks_evidence(self) -> None:
        context = self._context(sales_name="変更後売上")

        self.assertIsNone(evidence_for_target_context(
            jdl_source_tax_key("売二種", "10%", ""), context
        ))
        evidence = evidence_for_source_tax_key(
            jdl_source_tax_key("売二種", "10%", "")
        )
        self.assertEqual(
            target_master_dependency_mismatches(
                evidence, context.account_master, context.subaccounts
            ),
            ("RELEVANT_ACCOUNT_NAME_MISMATCH:612",),
        )

    def test_relevant_subaccount_requirement_blocks_evidence(self) -> None:
        context = self._context(
            extra_subaccounts=(self._subaccount("612", "売上高"),)
        )

        self.assertEqual(verified_tax_keys_for_target_context(context), frozenset())
        evidence = evidence_for_source_tax_key(
            jdl_source_tax_key("売五種", "10%", "")
        )
        self.assertEqual(
            target_master_dependency_mismatches(
                evidence, context.account_master, context.subaccounts
            ),
            ("RELEVANT_SUBACCOUNT_REQUIREMENT_CHANGED:612",),
        )

    def test_missing_relevant_account_reports_code_mismatch(self) -> None:
        context = self._context()
        evidence = evidence_for_source_tax_key(
            jdl_source_tax_key("売二種", "10%", "")
        )

        self.assertEqual(
            target_master_dependency_mismatches(
                evidence,
                tuple(
                    item for item in context.account_master
                    if item.target_master_code != "111"
                ),
                context.subaccounts,
            ),
            ("RELEVANT_ACCOUNT_CODE_MISSING:111",),
        )

    def test_context_change_blocks_relevant_master(self) -> None:
        context = self._context(taxation_method=JdlTaxationMethod.STANDARD)

        self.assertEqual(verified_tax_keys_for_target_context(context), frozenset())

    def test_occurrence_requires_exact_verified_route_and_shape(self) -> None:
        row = [""] * 30
        row[0:6] = ["1111", "1", "20261201", "111", "現金", "現金"]
        row[11:16] = ["1100", "0", "612", "売上高", "売上高"]
        row[18:21] = ["売二種", "10%", ""]
        row[21:24] = ["1100", "0", "SYNTHETIC-TAX"]
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(jdl_ibex_cashbook_official_journal_import_spec().column_names)
        writer.writerow(row)
        entry = JdlMigrationParser().parse_text(stream.getvalue()).entries[0]
        taxed_line = next(line for line in entry.lines if line.tax_info is not None)
        key = jdl_source_tax_key("売二種", "10%", "")

        self.assertTrue(evidence_supports_occurrence(
            key, entry, taxed_line, self._context()
        ))
        changed = dict(taxed_line.metadata)
        changed["jdl_source_account_code"] = "613"
        changed_line = replace(taxed_line, metadata=changed)
        changed_entry = replace(
            entry,
            lines=[
                changed_line if line is taxed_line else line
                for line in entry.lines
            ],
        )
        self.assertFalse(evidence_supports_occurrence(
            key, changed_entry, changed_line, self._context()
        ))

    @staticmethod
    def _context(
        *,
        sales_name: str = "売上高",
        taxation_method: JdlTaxationMethod = JdlTaxationMethod.SIMPLIFIED,
        extra_accounts=(),
        extra_subaccounts=(),
    ) -> JdlTargetContext:
        accounts = (
            JdlAccountIdentity("現金", "111", "現金", "現金"),
            JdlAccountIdentity(sales_name, "612", sales_name, sales_name),
            *extra_accounts,
        )
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset(item.mapping_value for item in accounts),
            tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            taxation_method=taxation_method,
            simplified_business_category=JdlSimplifiedBusinessCategory.FIRST,
            account_master=accounts,
            subaccounts=tuple(extra_subaccounts),
        )

    @staticmethod
    def _subaccount(parent_code: str, parent_name: str) -> JdlSubaccountIdentity:
        return JdlSubaccountIdentity(
            parent_account=parent_name,
            mapping_value="合成補助",
            target_master_code="0001",
            output_code="0001",
            output_name="合成補助",
            output_representation_confirmed=True,
            parent_account_code=parent_code,
            target_name="合成補助",
        )


if __name__ == "__main__":
    unittest.main()
    SIMPLIFIED_FIRST_INCLUDED_CONTEXT_IDENTITY_SHA256,

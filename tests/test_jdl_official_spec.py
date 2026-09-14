from __future__ import annotations

import unittest

from accounting_converter.domain.format_metadata import (
    CapabilityStatus,
    EvidenceLevel,
    FormatDirection,
)
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import (
    JdlDocumentedSpecificationStatus,
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_35_5_observed_schema_definition,
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class JdlOfficialSpecTests(unittest.TestCase):
    def test_official_manual_schema_has_exact_30_column_header(self) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()

        self.assertEqual(spec.column_count, 30)
        self.assertEqual(spec.column_names[0], "//識別フラグ")
        self.assertEqual(spec.column_names[23], "摘要")
        self.assertEqual(spec.column_names[-1], "貸方部門名称")
        self.assertIn(
            JdlDocumentedSpecificationStatus.OFFICIAL_DOCUMENTED,
            spec.statuses,
        )
        self.assertIn(
            JdlDocumentedSpecificationStatus.REAL_IMPORT_VERIFICATION_PENDING,
            spec.statuses,
        )
        self.assertFalse(spec.is_formal_format_profile)

    def test_official_schema_identity_is_output_target_but_not_verified(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(schema.identity.vendor, "JDL")
        self.assertEqual(schema.identity.direction, FormatDirection.OUTPUT)
        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(schema.column_count, 30)
        self.assertEqual(schema.has_header, CapabilityStatus.SUPPORTED)
        self.assertEqual(schema.date_formats, ("%Y%m%d",))
        self.assertIsNone(schema.encoding)
        self.assertIn("Not verified", schema.identity.notes)

    def test_official_and_observed_30_column_headers_match_but_identity_differs(self) -> None:
        official = jdl_ibex_cashbook_official_journal_import_schema_definition()
        observed = jdl_ibex_cashbook_35_5_observed_schema_definition()

        self.assertEqual(
            tuple(field.display_name for field in official.fields),
            tuple(field.display_name for field in observed.fields),
        )
        self.assertEqual(official.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(observed.identity.evidence_level, EvidenceLevel.OBSERVED)
        self.assertNotEqual(official.identity.stable_key, observed.identity.stable_key)
        self.assertEqual(official.date_formats, ("%Y%m%d",))
        self.assertEqual(observed.date_formats, ("UNKNOWN_OBSERVED",))

    def test_identifier_flag_meanings_are_documented(self) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()
        meanings = {flag.value: flag.documented_meaning for flag in spec.identifier_flags}

        self.assertEqual(meanings["1000"], "伝票以外の仕訳")
        self.assertEqual(meanings["1111"], "伝票1行の仕訳")
        self.assertEqual(meanings["1110"], "伝票1行目の仕訳")
        self.assertEqual(meanings["1100"], "伝票n行目の仕訳")
        self.assertEqual(meanings["1101"], "伝票最終行の仕訳")

    def test_tax_conditional_rules_are_documented_without_tax_code_list(self) -> None:
        spec = jdl_ibex_cashbook_official_journal_import_spec()
        rules = {rule.processing_mode: rule for rule in spec.tax_rules}

        self.assertFalse(rules[JdlTaxProcessingMode.EXEMPT].tax_scope_required)
        self.assertTrue(rules[JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED].tax_scope_required)
        self.assertFalse(
            rules[JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED].tax_amount_required
        )
        self.assertTrue(
            rules[JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED].tax_input_method_required
        )
        self.assertTrue(rules[JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED].tax_amount_required)

    def test_official_documented_schema_does_not_enable_production_output(self) -> None:
        registry = production_adapter_registry()
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(
            registry.get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()

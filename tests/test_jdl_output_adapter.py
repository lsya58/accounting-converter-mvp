from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.base import InputAdapter
from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_FORMAT_ID,
    JDL_OUTPUT_METADATA_KEY,
    JDLOutputAdapter,
    JDLOutputValidator,
    JdlDepartmentIdentity,
    JdlEvidenceProfile,
    JdlSubaccountIdentity,
    JdlTargetContext,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine, MappingRuleSet
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.journal import (
    JournalEntry,
    JournalLine,
    Side,
    SourceReference,
    TaxInfo,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import (
    JdlTaxProcessingMode,
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)


class _StaticInputAdapter(InputAdapter):
    def __init__(self, entries: tuple[JournalEntry, ...]) -> None:
        self.entries = entries

    def supports(self, path: Path, profile: FormatProfile) -> bool:
        _ = path, profile
        return True

    def record_count(self, path: Path, profile: FormatProfile) -> int:
        _ = path, profile
        return len(self.entries)

    def read(self, path: Path, profile: FormatProfile) -> list[JournalEntry]:
        _ = path, profile
        return list(self.entries)


class _NoStructuralErrors:
    def validate(self, path: Path, profile: FormatProfile) -> list:
        _ = path, profile
        return []


class JDLOutputAdapterV0Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = jdl_ibex_35_5_output_profile()

    def test_basic_1111_passes(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        rows, result = self.roundtrip((entry,), self.exempt_context())
        self.assertEqual(rows[1][0], "1111")
        self.assertEqual(rows[1][1], "")
        self.assertTrue(result.success)
        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.journal_count, 1)

    def test_basic_1000_passes(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1000)
        rows, result = self.roundtrip((entry,), self.exempt_context())
        self.assertEqual(rows[1][0], "1000")
        self.assertTrue(result.success)

    def test_supported_credit_subaccount_passes_with_parent_context(self) -> None:
        entry = self.simple(JdlEvidenceProfile.SUBACCOUNT_1000)
        entry.lines[1].sub_account = "補助A"
        rows, result = self.roundtrip((entry,), self.exempt_context(subaccount=True))
        self.assertTrue(result.success)
        self.assertEqual(rows[1][16:18], ["0001", "補助A"])

    def test_subaccount_without_confirmed_parent_blocks(self) -> None:
        entry = self.simple(JdlEvidenceProfile.SUBACCOUNT_1000)
        entry.lines[1].sub_account = "補助A"
        errors = JDLOutputAdapter(self.exempt_context()).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-SUBACCOUNT-MASTER", {item.rule_id for item in errors})

    def test_supported_both_side_department_passes(self) -> None:
        entry = self.simple(JdlEvidenceProfile.DEPARTMENT_1111)
        entry.lines[0].department = "部門A"
        entry.lines[1].department = "部門A"
        rows, result = self.roundtrip((entry,), self.exempt_context(department=True))
        self.assertTrue(result.success)
        self.assertEqual(rows[1][26:30], ["1", "部A", "1", "部A"])

    def test_tax_inclusive_exact_literal_passes_without_normalization(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.TAX_INCLUDED_1111, included=True)
        rows, result = self.roundtrip((entry,), self.tax_context(included=True))
        self.assertTrue(result.success)
        self.assertEqual(rows[1][8], "仕　入")
        self.assertEqual([ord(char) for char in rows[1][8]], [0x4ED5, 0x3000, 0x5165])
        self.assertEqual(rows[1][10], "")
        self.assertEqual(rows[1][12], "")

    def test_tax_exclusive_exact_fields_pass(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.TAX_EXCLUDED_1111, included=False)
        rows, result = self.roundtrip((entry,), self.tax_context(included=False))
        self.assertTrue(result.success)
        self.assertEqual(rows[1][8:13], ["仕　入", "10%", "内税", "1100", "100"])

    def test_tax_exclusive_unverified_explicit_amount_blocks(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.TAX_EXCLUDED_1111, included=False)
        entry.lines[0].tax_info = TaxInfo(
            category="10%",
            rate=Decimal("10"),
            tax_amount=Decimal("99"),
            metadata={
                "jdl_tax_scope": "仕　入",
                "jdl_tax_input_method": "内税",
            },
        )
        errors = JDLOutputAdapter(self.tax_context(included=False)).preflight(
            (entry,),
            self.profile,
        )
        self.assertIn(
            "JDL-OUT-TAX-AMOUNT-PATTERN",
            {item.rule_id for item in errors},
        )

    def test_verified_compound_1_debit_3_credit_passes(self) -> None:
        entry = self.compound()
        rows, result = self.roundtrip((entry,), self.exempt_context())
        self.assertTrue(result.success)
        self.assertEqual([row[0] for row in rows[1:]], ["1110", "1100", "1101"])
        self.assertEqual([row[11] for row in rows[1:]], ["1000", "0", "0"])
        self.assertEqual([row[23] for row in rows[1:]], ["複合", "", ""])

    def test_verified_simple_plus_compound_same_date_passes(self) -> None:
        entries = (self.simple(JdlEvidenceProfile.BASIC_1111), self.compound())
        rows, result = self.roundtrip(entries, self.exempt_context())
        self.assertTrue(result.success)
        self.assertEqual([row[0] for row in rows[1:]], ["1111", "1110", "1100", "1101"])
        self.assertEqual(result.record_count, 4)
        self.assertEqual(result.journal_count, 2)
        self.assertIn("EVID-JDL-GENERATOR-MULTIGROUP-SIMPLE-COMPOUND-001", result.evidence_profiles)

    def test_simple_plus_simple_multi_group_blocks(self) -> None:
        entries = (
            self.simple(JdlEvidenceProfile.BASIC_1111, entry_id="A"),
            self.simple(JdlEvidenceProfile.BASIC_1111, entry_id="B"),
        )
        errors = JDLOutputAdapter(self.exempt_context()).preflight(entries, self.profile)
        self.assertIn("JDL-OUT-MULTIGROUP-SCOPE", {item.rule_id for item in errors})

    def test_reduced_or_unknown_tax_blocks(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.TAX_INCLUDED_1111, included=True)
        entry.lines[0].tax_info = TaxInfo(
            category="8%",
            rate=Decimal("8"),
            reduced_rate=True,
            metadata={"jdl_tax_scope": "仕　入"},
        )
        errors = JDLOutputAdapter(self.tax_context(included=True)).preflight((entry,), self.profile)
        self.assertTrue({"JDL-OUT-TAX-LITERAL", "JDL-OUT-TAX-RATE"} & {item.rule_id for item in errors})

    def test_department_plus_tax_combination_blocks(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.DEPARTMENT_1111, included=True)
        entry.lines[0].department = "部門A"
        entry.lines[1].department = "部門A"
        errors = JDLOutputAdapter(self.tax_context(included=True, department=True)).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-DEPARTMENT-COMBINATION", {item.rule_id for item in errors})

    def test_flag_1000_tax_combination_blocks(self) -> None:
        entry = self.tax_entry(JdlEvidenceProfile.BASIC_1000, included=True)
        errors = JDLOutputAdapter(self.tax_context(included=True)).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-BASIC-FEATURE", {item.rule_id for item in errors})

    def test_malformed_compound_blocks(self) -> None:
        entry = self.compound()
        entry.lines.pop()
        entry.lines[1].amount = Decimal("700")
        errors = JDLOutputAdapter(self.exempt_context()).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-COMPOUND-SHAPE", {item.rule_id for item in errors})

    def test_unbalanced_entry_blocks(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        entry.lines[1].amount = Decimal("999")
        errors = JDLOutputAdapter(self.exempt_context()).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-BALANCE", {item.rule_id for item in errors})

    def test_cp932_unencodable_text_blocks_before_write(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        entry.description = "emoji \U0001f600"
        errors = JDLOutputAdapter(self.exempt_context()).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-CP932", {item.rule_id for item in errors})

    def test_unknown_product_or_version_blocks(self) -> None:
        wrong = FormatProfile("JDL", "JDL IBEX 出納帳", "36.0", JDL_OUTPUT_FORMAT_ID, "cp932")
        errors = JDLOutputAdapter(self.exempt_context()).preflight((self.simple(JdlEvidenceProfile.BASIC_1111),), wrong)
        self.assertIn("JDL-OUT-FORMAT-IDENTITY", {item.rule_id for item in errors})

    def test_unknown_evidence_profile_blocks(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        entry.metadata[JDL_OUTPUT_METADATA_KEY] = "UNVERIFIED_COMBINATION"
        errors = JDLOutputAdapter(self.exempt_context()).preflight((entry,), self.profile)
        self.assertIn("JDL-OUT-EVIDENCE-PROFILE", {item.rule_id for item in errors})

    def test_validator_rejects_bom_and_modified_data(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        context = self.exempt_context()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "jdl.csv"
            JDLOutputAdapter(context).write((entry,), path, self.profile)
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
            result = JDLOutputValidator(context).validate(path, (entry,), self.profile)
        self.assertFalse(result.success)
        self.assertTrue({"JDL-VAL-BOM", "JDL-VAL-CP932"} & {item.rule_id for item in result.validation_results})

    def test_conversion_service_success_is_atomic_and_reports_evidence(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            destination = root / "output.csv"
            source.write_text("synthetic", encoding="utf-8")
            result = self.service((entry,), self.exempt_context()).convert(
                ConversionRequest(source, destination, self.input_profile(), self.profile)
            )
            raw = destination.read_bytes()
        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn("JDL Evidence profile:", result.verification_report)
        self.assertIn(JDL_OUTPUT_FORMAT_ID, result.verification_report)

    def test_unresolved_mapping_blocks_before_output(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            destination = root / "output.csv"
            source.write_text("synthetic", encoding="utf-8")
            service = self.service((entry,), self.exempt_context(), resolve_mappings=False)
            result = service.convert(ConversionRequest(source, destination, self.input_profile(), self.profile))
            exists = destination.exists()
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
        self.assertFalse(exists)

    def test_output_preflight_block_does_not_create_formal_file(self) -> None:
        entry = self.compound()
        entry.lines.pop()
        entry.lines[1].amount = Decimal("700")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.txt"
            destination = root / "output.csv"
            source.write_text("synthetic", encoding="utf-8")
            result = self.service((entry,), self.exempt_context()).convert(
                ConversionRequest(source, destination, self.input_profile(), self.profile)
            )
            exists = destination.exists()
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertFalse(exists)
        self.assertIn(
            "unsupported output profile件数: 1",
            result.verification_report,
        )

    def test_source_output_path_conflict_blocks_without_modifying_source(self) -> None:
        entry = self.simple(JdlEvidenceProfile.BASIC_1111)
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.csv"
            source.write_bytes(b"original")
            result = self.service((entry,), self.exempt_context()).convert(
                ConversionRequest(source, source, self.input_profile(), self.profile)
            )
            after = source.read_bytes()
        self.assertEqual(result.status, ConversionStatus.INPUT_OUTPUT_PATH_CONFLICT)
        self.assertEqual(after, b"original")

    def test_production_registry_remains_unavailable(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

    def roundtrip(
        self,
        entries: tuple[JournalEntry, ...],
        context: JdlTargetContext,
    ) -> tuple[list[list[str]], object]:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "jdl.csv"
            JDLOutputAdapter(context).write(entries, path, self.profile)
            raw = path.read_bytes()
            result = JDLOutputValidator(context).validate(path, entries, self.profile)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
        self.assertEqual(tuple(rows[0]), jdl_ibex_cashbook_official_journal_import_spec().column_names)
        self.assertTrue(all(len(row) == 30 for row in rows[1:]))
        return rows, result

    def service(
        self,
        entries: tuple[JournalEntry, ...],
        context: JdlTargetContext,
        *,
        resolve_mappings: bool = True,
    ) -> ConversionService:
        accounts = {line.account for entry in entries for line in entry.lines if line.account}
        rules = {
            account: MappingValue(
                source_value=account,
                target_value=account,
                status=MappingStatus.USER_CONFIRMED,
            )
            for account in accounts
        } if resolve_mappings else {}
        return ConversionService(
            input_adapter=_StaticInputAdapter(entries),
            structural_validator=_NoStructuralErrors(),
            mapping_engine=MappingEngine(MappingRuleSet(rules, {}, {}, {})),
            business_validator=ValidationPipeline((BalanceRule(),)),
            output_adapter=JDLOutputAdapter(context),
            output_validator=JDLOutputValidator(context),
        )

    @staticmethod
    def input_profile() -> FormatProfile:
        return FormatProfile("Synthetic", "Synthetic", "1", "synthetic", "utf-8")

    @staticmethod
    def source(entry_id: str) -> SourceReference:
        return SourceReference("synthetic.csv", 2, entry_id)

    def simple(
        self,
        profile: JdlEvidenceProfile,
        *,
        entry_id: str = "J-1",
    ) -> JournalEntry:
        source = self.source(entry_id)
        return JournalEntry(
            id=entry_id,
            source_reference=source,
            date=date(2099, 1, 1),
            description="テスト",
            lines=[
                JournalLine(Side.DEBIT, "現金", Decimal("1000"), source),
                JournalLine(Side.CREDIT, "預金", Decimal("1000"), source),
            ],
            metadata={JDL_OUTPUT_METADATA_KEY: profile.value},
        )

    def compound(self) -> JournalEntry:
        source = self.source("C-1")
        return JournalEntry(
            id="C-1",
            source_reference=source,
            date=date(2099, 1, 1),
            description="複合",
            lines=[
                JournalLine(Side.DEBIT, "現金", Decimal("1000"), source),
                JournalLine(Side.CREDIT, "預金", Decimal("500"), source),
                JournalLine(Side.CREDIT, "売上", Decimal("300"), source),
                JournalLine(Side.CREDIT, "仕入", Decimal("200"), source),
            ],
            metadata={JDL_OUTPUT_METADATA_KEY: JdlEvidenceProfile.COMPOUND_1D3C.value},
        )

    def tax_entry(self, profile: JdlEvidenceProfile, *, included: bool) -> JournalEntry:
        entry = self.simple(profile)
        entry.lines[0].amount = Decimal("1100")
        entry.lines[1].amount = Decimal("1100")
        entry.lines[0].tax_info = TaxInfo(
            category="10%",
            rate=Decimal("10"),
            tax_amount=None if included else Decimal("100"),
            metadata={
                "jdl_tax_scope": "仕　入",
                "jdl_tax_input_method": "" if included else "内税",
            },
        )
        return entry

    @staticmethod
    def exempt_context(
        *,
        subaccount: bool = False,
        department: bool = False,
    ) -> JdlTargetContext:
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "預金", "売上", "仕入"}),
            tax_processing_mode=JdlTaxProcessingMode.EXEMPT,
            subaccounts=(
                JdlSubaccountIdentity(
                    "預金", "補助A", "1", "0001", "補助A", True
                ),
            ) if subaccount else (),
            departments=(
                JdlDepartmentIdentity("部門A", "1", "1", "部A"),
            ) if department else (),
            department_processing_enabled=department,
        )

    @staticmethod
    def tax_context(*, included: bool, department: bool = False) -> JdlTargetContext:
        return JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=frozenset({"現金", "預金", "売上", "仕入"}),
            tax_processing_mode=(
                JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED
                if included
                else JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED
            ),
            departments=(JdlDepartmentIdentity("部門A", "1", "1", "部A"),) if department else (),
            department_processing_enabled=department,
            standard_taxation_confirmed=True,
            individual_credit_method_confirmed=True,
        )


if __name__ == "__main__":
    unittest.main()

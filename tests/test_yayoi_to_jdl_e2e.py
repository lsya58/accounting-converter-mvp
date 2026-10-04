from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.yayoi import (
    YayoiInputAdapter,
    YayoiStructuralValidator,
)
from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    ExplicitJdlEvidenceRoutePolicy,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlDepartmentIdentity,
    JdlEvidenceProfile,
    JdlTargetContext,
    JdlTargetContextBuilder,
    JdlSubaccountIdentity,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.mapping_review import MappingRequirementExtractor
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.format_metadata import EvidenceLevel
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
    yayoi_ae19_direct_export_observed_schema,
)
from accounting_converter.profiles.yayoi_official import (
    yayoi_accounting_05_official_import_spec,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_YAYOI_TO_JDL_E2E,
    yayoi_to_jdl_e2e_real_import_evidence,
)


class YayoiToJdlFormalE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.yayoi_schema = yayoi_ae19_direct_export_observed_schema()
        self.yayoi_profile = FormatProfile(
            software="Yayoi",
            product="Yayoi Accounting AE 19",
            version="19",
            format_id=self.yayoi_schema.identity.stable_key,
            encoding="cp932",
        )
        self.jdl_profile = jdl_ibex_35_5_output_profile()
        self.accounts = frozenset({"現金", "普通預金", "当座預金", "小口現金"})

    def test_formal_yayoi_to_jdl_simple_plus_compound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "yayoi_to_jdl_source.csv")
            output = root / "jdl_output.csv"
            source_before = source.read_bytes()
            adapter = YayoiInputAdapter()
            parsed = adapter.read(source, self.yayoi_profile)
            profile = self.conversion_profile(self.accounts)
            requirements = MappingRequirementExtractor().extract(parsed, profile)
            routed = self.route_policy().apply(parsed)

            result = self.service(profile).convert(
                self.request(source, output, profile)
            )
            raw = output.read_bytes()
            source_after = source.read_bytes()
            rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))

        self.assertEqual(len(parsed), 2)
        self.assertEqual(sum(entry.is_compound() for entry in parsed), 1)
        self.assertEqual([entry.id for entry in parsed], ["101", "102"])
        self.assertTrue(all(entry.is_balanced() for entry in parsed))
        self.assertEqual(requirements.unresolved_count, 0)
        self.assertEqual(len(requirements.accounts), 4)
        self.assertFalse(routed.validation_results)
        self.assertEqual(
            [entry.metadata[JDL_OUTPUT_METADATA_KEY] for entry in routed.entries],
            [
                JdlEvidenceProfile.BASIC_1111.value,
                JdlEvidenceProfile.COMPOUND_1D3C.value,
            ],
        )
        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertEqual(result.input_record_count, 4)
        self.assertEqual(result.input_journal_count, 2)
        self.assertEqual(result.output_record_count, 4)
        self.assertEqual(result.output_journal_count, 2)
        self.assertEqual(result.debit_total, Decimal("1700"))
        self.assertEqual(result.credit_total, Decimal("1700"))
        self.assertEqual(result.unresolved_mapping_count, 0)
        self.assertIn("target context validation: success", result.verification_report)
        self.assertIn("account master count: 4", result.verification_report)
        self.assertIn("mapping/context consistency: success", result.verification_report)
        self.assertNotIn("1001", result.verification_report)
        self.assertNotIn("現金", result.verification_report)
        self.assertEqual(source_before, source_after)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(
            tuple(rows[0]),
            jdl_ibex_cashbook_official_journal_import_spec().column_names,
        )
        self.assertEqual([row[0] for row in rows[1:]], ["1111", "1110", "1100", "1101"])
        self.assertEqual({row[2] for row in rows[1:]}, {"20261015"})
        self.assertTrue(all(row[1] == "" for row in rows[1:]))
        self.assertTrue(all(len(row) == 30 for row in rows[1:]))
        self.assertEqual(
            [(row[4], row[11], row[14], row[21], row[23]) for row in rows[1:]],
            [
                ("現金", "700", "普通預金", "700", "弥生E2E-SIMPLE"),
                ("現金", "1000", "普通預金", "500", "弥生E2E-COMPOUND"),
                ("", "0", "当座預金", "300", ""),
                ("", "0", "小口現金", "200", ""),
            ],
        )

    def test_unknown_yayoi_account_blocks_at_mapping_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(
                root / "yayoi_unknown.csv",
                rows=[
                    self.row(
                        "2111",
                        "103",
                        debit_account="未知架空科目",
                        debit_amount="700",
                        credit_account="普通預金",
                        credit_amount="700",
                        description="未知科目",
                    )
                ],
            )
            output = root / "must_not_exist.csv"
            profile = self.conversion_profile(self.accounts)
            route = ExplicitJdlEvidenceRoutePolicy(
                {"103": JdlEvidenceProfile.BASIC_1111},
                route_id="YAYOI-AE19-TO-JDL-35.5-BASIC-V0",
            )
            parsed = YayoiInputAdapter().read(source, self.yayoi_profile)
            result = self.service(profile, route).convert(
                self.request(source, output, profile)
            )
            output_exists = output.exists()

        self.assertEqual(len(parsed), 1)
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
        self.assertEqual(result.unresolved_mapping_count, 1)
        self.assertFalse(output_exists)

    def test_missing_target_context_blocks_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "yayoi.csv")
            output = root / "must_not_exist.csv"
            profile = self.conversion_profile(self.accounts)
            result = self.service(profile).convert(
                ConversionRequest(
                    source,
                    output,
                    self.yayoi_profile,
                    self.jdl_profile,
                    conversion_profile=profile,
                    target_runtime_context=None,
                )
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_TARGET_CONTEXT)
        self.assertIn(
            "JDL-CONTEXT-MISSING",
            {item.rule_id for item in result.validation_results},
        )
        self.assertFalse(output.exists())

    def test_wrong_jdl_version_is_rejected_by_context_builder(self) -> None:
        result = self.build_context(version="36.0")

        self.assertFalse(result.success)
        self.assertIn(
            "JDL-CONTEXT-TARGET-IDENTITY",
            {item.rule_id for item in result.validation_results},
        )

    def test_mapping_target_code_mismatch_blocks_context_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "yayoi.csv")
            output = root / "must_not_exist.csv"
            profile = self.conversion_profile(self.accounts)
            profile.account_mappings["現金"].metadata["target_code"] = "9999"
            result = self.service(profile).convert(
                self.request(source, output, profile)
            )

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_TARGET_CONTEXT)
        self.assertIn(
            "JDL-CONTEXT-ACCOUNT-MAPPING-MISMATCH",
            {item.rule_id for item in result.validation_results},
        )
        self.assertFalse(output.exists())

    def test_subaccount_parent_mismatch_makes_context_invalid(self) -> None:
        subaccount = JdlSubaccountIdentity(
            parent_account="普通預金",
            mapping_value="架空補助",
            target_master_code="1",
            output_code="0001",
            output_name="架空補助",
            output_representation_confirmed=True,
            parent_account_code="9999",
            target_name="架空補助",
        )
        result = self.build_context(subaccounts=(subaccount,))

        self.assertFalse(result.success)
        self.assertIn(
            "JDL-CONTEXT-SUBACCOUNT-PARENT",
            {item.rule_id for item in result.validation_results},
        )

    def test_department_mapping_code_mismatch_blocks_context_resolution(self) -> None:
        department = JdlDepartmentIdentity(
            mapping_value="架空部門",
            target_master_code="1",
            output_code="1",
            output_name="部門",
            target_formal_name="架空部門",
        )
        context_result = self.build_context(
            departments=(department,),
            department_processing_enabled=True,
        )
        self.assertTrue(context_result.success)
        profile = self.conversion_profile(self.accounts)
        profile.department_mappings["入力部門"] = MappingValue(
            source_value="入力部門",
            target_value="架空部門",
            status=MappingStatus.USER_CONFIRMED,
            metadata={"target_code": "2", "target_formal_name": "架空部門"},
        )
        factory = self.runtime_factory()
        resolution = factory.resolve(
            self.jdl_profile,
            profile,
            context_result.context,
        )

        self.assertFalse(resolution.resolved)
        self.assertIn(
            "JDL-CONTEXT-DEPARTMENT-MAPPING-MISMATCH",
            {item.rule_id for item in resolution.validation_results},
        )

    def test_tax_profile_vs_exempt_context_blocks_output_preflight(self) -> None:
        result = self.convert_single_with_route(
            JdlEvidenceProfile.TAX_INCLUDED_1111,
            JdlTaxProcessingMode.EXEMPT,
        )
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertIn(
            "JDL-OUT-TAX-MODE",
            {item.rule_id for item in result.validation_results},
        )

    def test_tax_inclusive_profile_vs_exclusive_context_blocks(self) -> None:
        result = self.convert_single_with_route(
            JdlEvidenceProfile.TAX_INCLUDED_1111,
            JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        )
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertIn(
            "JDL-OUT-TAX-MODE",
            {item.rule_id for item in result.validation_results},
        )

    def test_duplicate_target_account_code_makes_context_invalid(self) -> None:
        masters = list(self.account_master())
        masters[1] = JdlAccountIdentity(
            masters[1].mapping_value,
            masters[0].target_master_code,
            masters[1].target_name,
            masters[1].target_formal_name,
        )
        result = self.build_context(account_master=tuple(masters))

        self.assertFalse(result.success)
        self.assertIn(
            "JDL-CONTEXT-ACCOUNT-DUPLICATE",
            {item.rule_id for item in result.validation_results},
        )

    def test_missing_explicit_route_assignment_blocks_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root / "yayoi_missing_route.csv")
            output = root / "must_not_exist.csv"
            profile = self.conversion_profile(self.accounts)
            route = ExplicitJdlEvidenceRoutePolicy(
                {"101": JdlEvidenceProfile.BASIC_1111},
                route_id="INCOMPLETE-ROUTE",
            )
            result = self.service(profile, route).convert(
                self.request(source, output, profile)
            )
            output_exists = output.exists()

        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
        self.assertIn(
            "JDL-ROUTE-MISSING-ASSIGNMENT",
            {item.rule_id for item in result.validation_results},
        )
        self.assertFalse(output_exists)

    def test_structural_validator_rejects_non_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "yayoi.csv"
            path.write_bytes(
                (",".join(self.row("2111", "101")) + "\n").encode("cp932")
            )
            results = YayoiStructuralValidator().validate(path, self.yayoi_profile)

        self.assertIn("YAYOI-STRUCT-LINE-END", {item.rule_id for item in results})

    def test_registry_and_route_readiness_remain_unavailable(self) -> None:
        target = jdl_ibex_cashbook_official_journal_import_schema_definition()
        registry = production_adapter_registry()
        self.assertEqual(
            registry.get_exact_output(target.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )
        implementation = registry.get_exact_output(
            target.identity,
            production_only=False,
        )
        self.assertEqual(implementation.status, AdapterAvailabilityStatus.EXACT)
        self.assertTrue(implementation.registration.requires_runtime_context)
        self.assertFalse(implementation.registration.production_enabled)

    def test_real_import_evidence_is_runtime_verified_but_not_production_enabled(
        self,
    ) -> None:
        evidence = yayoi_to_jdl_e2e_real_import_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_YAYOI_TO_JDL_E2E)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn(
            "formal YayoiInputAdapter and structural validation",
            evidence.verified_scope,
        )
        self.assertIn(
            "post-import JDL self re-export compared across 120 fields",
            evidence.verified_scope,
        )
        self.assertIn(
            "registry factory wiring for explicit target master and tax context",
            evidence.not_verified,
        )
        self.assertIn(
            "tax, subaccount, or department in the Yayoi to JDL route",
            evidence.not_verified,
        )

    def service(
        self,
        profile: ConversionProfile,
        route=None,
    ) -> ConversionService:
        target = jdl_ibex_cashbook_official_journal_import_schema_definition()
        lookup = production_adapter_registry().get_exact_output(
            target.identity,
            production_only=False,
        )
        self.assertIsNotNone(lookup.registration)
        self.assertIsNotNone(lookup.registration.runtime_factory)
        return ConversionService(
            input_adapter=YayoiInputAdapter(),
            structural_validator=YayoiStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(),)),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=route or self.route_policy(),
            runtime_output_factory=lookup.registration.runtime_factory,
        )

    def runtime_factory(self):
        target = jdl_ibex_cashbook_official_journal_import_schema_definition()
        lookup = production_adapter_registry().get_exact_output(
            target.identity,
            production_only=False,
        )
        assert lookup.registration is not None
        assert lookup.registration.runtime_factory is not None
        return lookup.registration.runtime_factory

    def request(
        self,
        source: Path,
        output: Path,
        profile: ConversionProfile,
        context: JdlTargetContext | None = None,
    ) -> ConversionRequest:
        return ConversionRequest(
            source,
            output,
            self.yayoi_profile,
            self.jdl_profile,
            conversion_profile=profile,
            target_runtime_context=context or self.target_context(),
        )

    def target_context(self) -> JdlTargetContext:
        result = self.build_context()
        self.assertTrue(result.success, result.validation_results)
        assert result.context is not None
        return result.context

    def build_context(
        self,
        *,
        version: str = "35.5",
        account_master: tuple[JdlAccountIdentity, ...] | None = None,
        subaccounts: tuple[JdlSubaccountIdentity, ...] = (),
        departments: tuple[JdlDepartmentIdentity, ...] = (),
        department_processing_enabled: bool = False,
        tax_processing_mode: JdlTaxProcessingMode = JdlTaxProcessingMode.EXEMPT,
    ):
        return JdlTargetContextBuilder().build(
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            product="JDL IBEX 出納帳",
            version=version,
            account_master=(
                self.account_master() if account_master is None else account_master
            ),
            subaccounts=subaccounts,
            departments=departments,
            tax_processing_mode=tax_processing_mode,
            department_processing_enabled=department_processing_enabled,
            standard_taxation_confirmed=(
                tax_processing_mode is not JdlTaxProcessingMode.EXEMPT
            ),
            individual_credit_method_confirmed=(
                tax_processing_mode is not JdlTaxProcessingMode.EXEMPT
            ),
            confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True,
            no_automatic_replacement=True,
        )

    def account_master(self) -> tuple[JdlAccountIdentity, ...]:
        return tuple(
            JdlAccountIdentity(account, code, account, account)
            for account, code in self.account_codes().items()
        )

    def convert_single_with_route(
        self,
        evidence_profile: JdlEvidenceProfile,
        tax_processing_mode: JdlTaxProcessingMode,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(
                root / "yayoi.csv",
                rows=[self.row("2111", "101")],
            )
            output = root / "must_not_exist.csv"
            profile = self.conversion_profile(self.accounts)
            route = ExplicitJdlEvidenceRoutePolicy(
                {"101": evidence_profile},
                route_id="TAX-MODE-MISMATCH",
            )
            context_result = self.build_context(
                tax_processing_mode=tax_processing_mode,
            )
            assert context_result.context is not None
            result = self.service(profile, route).convert(
                self.request(source, output, profile, context_result.context)
            )
            self.assertFalse(output.exists())
            return result

    def conversion_profile(self, accounts: frozenset[str]) -> ConversionProfile:
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        return ConversionProfile(
            profile_id="yayoi-ae19-to-jdl-35.5-e2e",
            profile_name="Synthetic Yayoi to JDL E2E",
            source_format_identity=self.yayoi_schema.identity,
            target_format_identity=(
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity
            ),
            account_mappings={
                account: MappingValue(
                    source_value=account,
                    target_value=account,
                    status=MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": self.account_codes()[account],
                        "target_formal_name": account,
                    },
                )
                for account in accounts
            },
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def account_codes() -> dict[str, str]:
        return {
            "現金": "1001",
            "普通預金": "1002",
            "当座預金": "1003",
            "小口現金": "1004",
        }

    @staticmethod
    def route_policy() -> ExplicitJdlEvidenceRoutePolicy:
        return ExplicitJdlEvidenceRoutePolicy(
            {
                "101": JdlEvidenceProfile.BASIC_1111,
                "102": JdlEvidenceProfile.COMPOUND_1D3C,
            },
            route_id="YAYOI-AE19-TO-JDL-35.5-BASIC-COMPOUND-V0",
        )

    def write_source(
        self,
        path: Path,
        *,
        rows: list[tuple[str, ...]] | None = None,
    ) -> Path:
        source_rows = rows or [
            self.row(
                "2111",
                "101",
                debit_account="現金",
                debit_amount="700",
                credit_account="普通預金",
                credit_amount="700",
                description="弥生E2E-SIMPLE",
            ),
            self.row(
                "2110",
                "102",
                debit_account="現金",
                debit_amount="1000",
                credit_account="普通預金",
                credit_amount="500",
                description="弥生E2E-COMPOUND",
            ),
            self.row(
                "2100",
                "102",
                debit_account="",
                debit_amount="0",
                credit_account="当座預金",
                credit_amount="300",
                description="",
            ),
            self.row(
                "2101",
                "102",
                debit_account="",
                debit_amount="0",
                credit_account="小口現金",
                credit_amount="200",
                description="",
            ),
        ]
        with path.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(source_rows)
        return path

    @staticmethod
    def row(
        flag: str,
        voucher: str,
        *,
        debit_account: str = "現金",
        debit_amount: str = "100",
        credit_account: str = "普通預金",
        credit_amount: str = "100",
        description: str = "架空摘要",
    ) -> tuple[str, ...]:
        spec = yayoi_accounting_05_official_import_spec()
        values = {column.name: "" for column in spec.columns}
        values.update(
            {
                "識別フラグ": flag,
                "伝票No.": voucher,
                "取引日付": "R.08/10/15",
                "借方勘定科目": debit_account,
                "借方金額": debit_amount,
                "貸方勘定科目": credit_account,
                "貸方金額": credit_amount,
                "摘要": description,
            }
        )
        return tuple(values[column.name] for column in spec.columns)


if __name__ == "__main__":
    unittest.main()

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
    JDLOutputAdapter,
    JDLOutputValidator,
    ExplicitJdlEvidenceRoutePolicy,
    JdlEvidenceProfile,
    JdlTargetContext,
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
                ConversionRequest(
                    source,
                    output,
                    self.yayoi_profile,
                    self.jdl_profile,
                )
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
                ConversionRequest(source, output, self.yayoi_profile, self.jdl_profile)
            )
            output_exists = output.exists()

        self.assertEqual(len(parsed), 1)
        self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_MAPPING)
        self.assertEqual(result.unresolved_mapping_count, 1)
        self.assertFalse(output_exists)

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
                ConversionRequest(source, output, self.yayoi_profile, self.jdl_profile)
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
        self.assertEqual(
            production_adapter_registry().get_exact_output(target.identity).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )

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
        context = JdlTargetContext(
            product="JDL IBEX 出納帳",
            version="35.5",
            accounts=self.accounts,
            tax_processing_mode=JdlTaxProcessingMode.EXEMPT,
        )
        return ConversionService(
            input_adapter=YayoiInputAdapter(),
            structural_validator=YayoiStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(),)),
            output_adapter=JDLOutputAdapter(context),
            output_validator=JDLOutputValidator(context),
            journal_route_policy=route or self.route_policy(),
        )

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
                )
                for account in accounts
            },
            created_at=now,
            updated_at=now,
        )

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

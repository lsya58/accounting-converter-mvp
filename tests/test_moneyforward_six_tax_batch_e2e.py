from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import (
    MoneyForwardInputAdapter,
    MoneyForwardStructuralValidator,
)
from accounting_converter.adapters.output.jdl import (
    ExplicitJdlEvidenceRoutePolicy,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlOutputRuntimeFactory,
    JdlSubaccountIdentity,
    JdlTargetContextBuilder,
    JdlTargetContextValidator,
    SIX_TAX_BATCH_EVIDENCE_ID,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.application.conversion import (
    ConversionRequest,
    ConversionService,
    ConversionStatus,
)
from accounting_converter.application.mapping_engine import MappingEngine
from accounting_converter.application.moneyforward_jdl_loss import MoneyForwardToJdlLossRule
from accounting_converter.application.profile_preflight import mapping_rule_set_from_profile
from accounting_converter.application.validation_pipeline import ValidationPipeline
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import (
    MappingKey,
    MappingStatus,
    MappingType,
    MappingValue,
    SubaccountPolicy,
)
from accounting_converter.domain.profile import FormatProfile
from accounting_converter.domain.validation import BalanceRule
from accounting_converter.infrastructure.adapter_registry import AdapterAvailabilityStatus, production_adapter_registry
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)
from accounting_converter.tools.jdl_six_tax_batch import (
    SIX_TAX_CASE_IDENTITIES,
    compare_jdl_six_tax_batch,
    compare_jdl_six_tax_batch_artifact,
)


FIXTURE = Path(__file__).parent / "fixtures" / "moneyforward" / "mf_six_tax_cases.csv"


class MoneyForwardSixTaxBatchE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        schema = moneyforward_cloud_journal_export_observed_schema()
        self.source_profile = FormatProfile(
            "Money Forward", "Money Forward クラウド会計", "UNKNOWN",
            schema.identity.stable_key, "cp932",
        )
        self.target_identity = jdl_ibex_cashbook_official_journal_import_schema_definition().identity

    def test_formal_conversion_service_converts_all_six_cases_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "six.csv"
            result = self._convert(FIXTURE, output, self._profile(), self._context())
            rows = self._rows(output)

        self.assertEqual(result.status, ConversionStatus.SUCCESS)
        self.assertEqual((result.input_record_count, result.input_journal_count), (6, 6))
        self.assertEqual((result.output_record_count, result.output_journal_count), (6, 6))
        self.assertEqual((result.debit_total, result.credit_total), (Decimal("6360"), Decimal("6360")))
        self.assertEqual(len(rows), 7)
        self.assertEqual([row[0] for row in rows[1:]], ["1111"] * 6)
        self.assertEqual([row[23] for row in rows[1:]], list(SIX_TAX_CASE_IDENTITIES))
        self.assertEqual([(row[8], row[9], row[18], row[19]) for row in rows[1:]], [
            ("仕　入", "10%", "", ""),
            ("", "", "売一種", "10%"),
            ("仕　入", "軽減8%", "", ""),
            ("", "", "売一種", "軽減8%"),
            ("非仕入", "", "", ""),
            ("", "", "", ""),
        ])
        self.assertTrue(result.output_validation_result.success)
        self.assertIn(SIX_TAX_BATCH_EVIDENCE_ID, result.output_validation_result.evidence_profiles)
        self.assertIn("input journal count: 6", result.verification_report)
        self.assertIn("output journal count: 6", result.verification_report)
        self.assertIn("借方総額: 6360", result.verification_report)
        for value in SIX_TAX_CASE_IDENTITIES:
            self.assertNotIn(value, result.verification_report)

    def test_one_wrong_parent_subaccount_blocks_whole_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "blocked.csv"
            result = self._convert(
                FIXTURE, output, self._profile(wrong_parent=True), self._context()
            )
            self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_TARGET_CONTEXT)
            self.assertFalse(output.exists())
            self.assertEqual(result.output_record_count, 0)
            self.assertTrue(any(item.field == "subaccount_mapping" for item in result.validation_results))

    def test_parent_only_policy_requires_a_parent_without_observed_subaccounts(self) -> None:
        profile = self._profile()
        key = MappingKey(MappingType.SUBACCOUNT, "補助甲", "仕入乙")
        mappings = dict(profile.subaccount_context_mappings)
        mappings[key] = MappingValue(
            "補助甲",
            "",
            MappingStatus.USER_CONFIRMED,
            "仕入乙",
            {"subaccount_policy": SubaccountPolicy.PARENT_ONLY_CONFIRMED.value},
        )
        profile = replace(profile, subaccount_context_mappings=mappings)
        context_with_subaccount = self._context()
        blocked = JdlOutputRuntimeFactory().resolve(
            jdl_ibex_35_5_output_profile(), profile, context_with_subaccount
        )
        self.assertIsNone(blocked.output_adapter)

        context_without_parent_subaccount = replace(
            context_with_subaccount,
            subaccounts=tuple(
                item
                for item in context_with_subaccount.subaccounts
                if item.parent_account != "仕入乙"
            ),
        )
        allowed = JdlOutputRuntimeFactory().resolve(
            jdl_ibex_35_5_output_profile(), profile, context_without_parent_subaccount
        )
        self.assertIsNotNone(allowed.output_adapter)

    def test_existing_formal_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.csv"
            output.write_bytes(b"existing")
            result = self._convert(FIXTURE, output, self._profile(), self._context())
            self.assertNotEqual(result.status, ConversionStatus.SUCCESS)
            self.assertEqual(output.read_bytes(), b"existing")

    def test_out_of_scope_requires_explicit_profile_and_manifest_comparator_is_strict(self) -> None:
        routes = self._routes()
        routes["6"] = JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "blocked.csv"
            result = self._convert(FIXTURE, output, self._profile(), self._context(), routes)
            self.assertEqual(result.status, ConversionStatus.BLOCKED_BY_OUTPUT_PREFLIGHT)
            self.assertFalse(output.exists())

            candidate = root / "candidate.csv"
            success = self._convert(FIXTURE, candidate, self._profile(), self._context())
            self.assertEqual(success.status, ConversionStatus.SUCCESS)
            reexport = root / "reexport.csv"
            reexport.write_bytes(b"// synthetic\r\n\r\n" + candidate.read_bytes())
            comparison = compare_jdl_six_tax_batch(
                candidate, reexport, manifest_case_identities=SIX_TAX_CASE_IDENTITIES
            )
            self.assertTrue(comparison.passed)
            self.assertEqual(comparison.privacy_safe_result()["matched_count"], 6)
            invalid = compare_jdl_six_tax_batch(
                candidate, reexport, manifest_case_identities=SIX_TAX_CASE_IDENTITIES[:-1]
            )
            self.assertFalse(invalid.passed)

    def test_artifact_comparator_requires_exact_manifest_and_explicit_out_of_scope_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.csv"
            result = self._convert(FIXTURE, candidate, self._profile(), self._context())
            self.assertEqual(result.status, ConversionStatus.SUCCESS)
            profile = root / "profile.json"
            profile.write_text(
                ConversionProfileStore(root).to_json_text(self._profile()),
                encoding="utf-8",
            )
            reexport = root / "reexport.csv"
            normalized_rows = self._rows(candidate)
            profile_model = self._profile()
            for row in normalized_rows[1:]:
                row[1] = "0"
                for name_index, code_index, formal_index in ((4, 3, 5), (14, 13, 15)):
                    mapping = profile_model.account_mappings[row[name_index]]
                    row[code_index] = mapping.metadata["target_code"]
                    row[formal_index] = mapping.metadata["target_formal_name"]
                for parent_index, name_index, code_index in ((4, 7, 6), (14, 17, 16)):
                    if row[name_index]:
                        mapping = profile_model.subaccount_context_mappings[
                            MappingKey(MappingType.SUBACCOUNT, row[name_index], row[parent_index])
                        ]
                        row[code_index] = mapping.metadata["output_code"]
                row[12] = row[22] = row[26] = row[28] = "0"
            self._write_jdl_rows(reexport, [["// synthetic"], [], *normalized_rows])
            manifest = root / "manifest.json"
            manifest_data = {
                "batch_semantic_identity": "MF_SIX_TAX_CASES_BATCH_V0",
                "case_identities": list(SIX_TAX_CASE_IDENTITIES),
                "evidence_scope": [profile.value for profile in self._routes().values()],
                "expected_journal_count": 6,
                "expected_row_count": 6,
                "NOT_FOR_PRODUCTION": True,
                "production_allowed": False,
                "output_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "conversion_profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
            }
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

            comparison = compare_jdl_six_tax_batch_artifact(
                candidate, reexport, manifest, profile
            )
            self.assertTrue(comparison.passed)

            original_reexport = reexport.read_bytes()
            wrong_tax_rows = self._rows(reexport)
            wrong_tax_rows[-1][8] = "unexpected"
            self._write_jdl_rows(reexport, wrong_tax_rows)
            self.assertFalse(compare_jdl_six_tax_batch_artifact(
                candidate, reexport, manifest, profile
            ).passed)

            wrong_subaccount_rows = self._rows(io.BytesIO(original_reexport))
            wrong_subaccount_rows[3][7] = "wrong-parent"
            self._write_jdl_rows(reexport, wrong_subaccount_rows)
            self.assertEqual(compare_jdl_six_tax_batch_artifact(
                candidate, reexport, manifest, profile
            ).status, "PROFILE_MISMATCH")
            reexport.write_bytes(original_reexport)

            profile.write_text(profile.read_text(encoding="utf-8") + " ", encoding="utf-8")
            self.assertEqual(compare_jdl_six_tax_batch_artifact(
                candidate, reexport, manifest, profile
            ).status, "MANIFEST_MISMATCH")
            profile.write_text(
                ConversionProfileStore(root).to_json_text(self._profile()),
                encoding="utf-8",
            )

            manifest_data["case_identities"] = list(SIX_TAX_CASE_IDENTITIES[:-1])
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
            self.assertEqual(
                compare_jdl_six_tax_batch_artifact(
                    candidate, reexport, manifest, profile
                ).status,
                "MANIFEST_MISMATCH",
            )

    def test_comparator_rejects_missing_and_duplicate_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.csv"
            self.assertEqual(
                self._convert(FIXTURE, candidate, self._profile(), self._context()).status,
                ConversionStatus.SUCCESS,
            )
            rows = self._rows(candidate)
            missing = root / "missing.csv"
            duplicate = root / "duplicate.csv"
            extra = root / "extra.csv"
            self._write_jdl_rows(missing, rows[:-1])
            self._write_jdl_rows(duplicate, rows + [rows[1]])
            extra_row = list(rows[1])
            extra_row[23] = "SIX-TAX-EXTRA"
            self._write_jdl_rows(extra, rows + [extra_row])
            self.assertFalse(compare_jdl_six_tax_batch(
                candidate, missing, manifest_case_identities=SIX_TAX_CASE_IDENTITIES
            ).passed)
            duplicate_result = compare_jdl_six_tax_batch(
                candidate, duplicate, manifest_case_identities=SIX_TAX_CASE_IDENTITIES
            )
            self.assertFalse(duplicate_result.passed)
            self.assertEqual(duplicate_result.duplicate_count, 1)
            self.assertEqual(duplicate_result.ambiguous_count, 1)
            extra_result = compare_jdl_six_tax_batch(
                candidate, extra, manifest_case_identities=SIX_TAX_CASE_IDENTITIES
            )
            self.assertFalse(extra_result.passed)
            self.assertEqual(extra_result.extra_count, 1)

    def test_unified_context_rejects_conflicting_parent_scoped_subaccount(self) -> None:
        context = self._context()
        conflicting = replace(
            context,
            subaccounts=context.subaccounts + (replace(
                context.subaccounts[0], target_name="別補助", mapping_value="別補助"
            ),),
        )
        results = JdlTargetContextValidator().validate(conflicting)
        self.assertTrue(any(
            item.rule_id == "JDL-CONTEXT-SUBACCOUNT-DUPLICATE" for item in results
        ))

    def test_production_registry_remains_unavailable_for_moneyforward(self) -> None:
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        self.assertEqual(registry.get_exact_input(source).status, AdapterAvailabilityStatus.UNAVAILABLE)
        self.assertFalse(registry.has_conversion_pair(source, self.target_identity))

    def _convert(self, source, output, profile, context, routes=None):
        service = ConversionService(
            input_adapter=MoneyForwardInputAdapter(),
            structural_validator=MoneyForwardStructuralValidator(),
            mapping_engine=MappingEngine(mapping_rule_set_from_profile(profile)),
            business_validator=ValidationPipeline((BalanceRule(), MoneyForwardToJdlLossRule())),
            output_adapter=None,
            output_validator=None,
            journal_route_policy=ExplicitJdlEvidenceRoutePolicy(
                {f"moneyforward:{source.name}:{key}": value for key, value in (routes or self._routes()).items()},
                route_id="MF-SIX-TAX-SYNTHETIC-E2E-V0",
            ),
            runtime_output_factory=JdlOutputRuntimeFactory(),
        )
        return service.convert(ConversionRequest(
            source, output, self.source_profile, jdl_ibex_35_5_output_profile(),
            conversion_profile=profile, target_runtime_context=context,
        ))

    @staticmethod
    def _routes():
        return {
            "1": JdlEvidenceProfile.TAX_PURCHASE_10_SUBACCOUNT_INCLUDED_1111,
            "2": JdlEvidenceProfile.TAX_SALES_10_SUBACCOUNT_INCLUDED_1111,
            "3": JdlEvidenceProfile.TAX_PURCHASE_REDUCED_8_INCLUDED_1111,
            "4": JdlEvidenceProfile.TAX_SALES_REDUCED_8_SUBACCOUNT_INCLUDED_1111,
            "5": JdlEvidenceProfile.TAX_NON_TAXABLE_PURCHASE_SUBACCOUNT_INCLUDED_1111,
            "6": JdlEvidenceProfile.TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED_1111,
        }

    def _profile(self, wrong_parent=False):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        accounts = ("仕入甲", "仕入乙", "売上甲", "現金甲")
        sub_mappings = {
            MappingKey(MappingType.SUBACCOUNT, "補助甲", "仕入乙"): MappingValue(
                "補助甲", "補助乙" if wrong_parent else "補助甲",
                MappingStatus.USER_CONFIRMED, "仕入乙",
                {"target_code": "1", "output_code": "1", "output_name": "補助乙" if wrong_parent else "補助甲"},
            ),
            MappingKey(MappingType.SUBACCOUNT, "補助乙", "売上甲"): MappingValue(
                "補助乙", "補助乙", MappingStatus.USER_CONFIRMED, "売上甲",
                {"target_code": "1", "output_code": "1", "output_name": "補助乙"},
            ),
        }
        tax = {
            "課税仕入 10%": self._mapping("課税仕入 10%", "10%", "仕　入", "P10"),
            "課税売上 10%": self._mapping("課税売上 10%", "10%", "売一種", "S10"),
            "課税仕入 (軽)8%": self._mapping("課税仕入 (軽)8%", "軽減8%", "仕　入", "PR8"),
            "課税売上 (軽)8%": self._mapping("課税売上 (軽)8%", "軽減8%", "売一種", "SR8"),
            "非課税仕入": self._mapping("非課税仕入", "", "非仕入", "NTP"),
            "対象外": self._mapping("対象外", "", "", "EVID-JDL-MF-TAX-OUT-OF-SCOPE-SUBACCOUNT-ROUNDTRIP-001"),
        }
        return ConversionProfile(
            "mf-six-tax-synthetic", "Synthetic six tax cases", moneyforward_cloud_journal_export_observed_schema().identity,
            self.target_identity,
            account_mappings={name: MappingValue(name, name, MappingStatus.USER_CONFIRMED, metadata={"target_code": str(1000 + i), "target_formal_name": name}) for i, name in enumerate(accounts)},
            subaccount_context_mappings=sub_mappings, tax_mappings=tax,
            created_at=now, updated_at=now, notes="TEST ONLY; exact mappings; no production use.",
        )

    @staticmethod
    def _mapping(source, target, scope, evidence):
        return MappingValue(source, target, MappingStatus.USER_CONFIRMED, metadata={"jdl_tax_scope": scope, "jdl_evidence_id": evidence})

    def _context(self):
        accounts = ("仕入甲", "仕入乙", "売上甲", "現金甲")
        codes = {name: str(1000 + i) for i, name in enumerate(accounts)}
        result = JdlTargetContextBuilder().build(
            target_format_identity=self.target_identity, product="JDL IBEX 出納帳", version="35.5",
            account_master=tuple(JdlAccountIdentity(name, codes[name], name, name) for name in accounts),
            subaccounts=(
                JdlSubaccountIdentity("仕入乙", "補助甲", "1", "1", "補助甲", True, codes["仕入乙"], "補助甲"),
                JdlSubaccountIdentity("売上甲", "補助乙", "1", "1", "補助乙", True, codes["売上甲"], "補助乙"),
            ), departments=(), tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED,
            department_processing_enabled=False, standard_taxation_confirmed=True,
            individual_credit_method_confirmed=True, confirmation_state=JdlContextConfirmationState.CONFIRMED,
            provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
            no_fuzzy_matching=True, no_automatic_replacement=True,
        )
        self.assertTrue(result.success, result.validation_results)
        return result.context

    @staticmethod
    def _rows(path):
        raw = path.read() if hasattr(path, "read") else path.read_bytes()
        return list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))

    @staticmethod
    def _write_jdl_rows(path, rows):
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        path.write_bytes(buffer.getvalue().encode("cp932"))


if __name__ == "__main__":
    unittest.main()

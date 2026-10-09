from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)
from accounting_converter.tools.generate_jdl_probe import (
    JdlProbeError,
    JdlProbeGenerator,
    PROBE_DEFINITIONS,
    TAX_PROBE_CASES,
    main,
)


class JdlProbeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.private = self.root / "data" / "private"
        self.private.mkdir(parents=True)
        self.profile_path = self.private / "profile.json"
        self.context_path = self.private / "context.json"
        self._write_profile(self.profile_path)
        self._write_context(self.context_path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_list_contains_only_reviewed_cases(self) -> None:
        names = {item.name for item in PROBE_DEFINITIONS}
        self.assertEqual(
            names,
            {
                "simple_no_tax",
                "simple_two_journals",
                "simple_with_tax",
                "simple_with_subaccount",
                "compound_1d3c",
                "tax_sales_10",
                "tax_purchase_10",
                "tax_sales_reduced_8",
                "tax_purchase_reduced_8",
                "tax_non_taxable_purchase",
                "tax_out_of_scope",
            },
        )
        self.assertNotIn("compound_3d1c", names)
        self.assertEqual(main(["--list"]), 0)

    def test_simple_and_two_journal_candidates_validate(self) -> None:
        cases = (("simple_no_tax", 1, 1, "700"), ("simple_two_journals", 2, 2, "1600"))
        for name, records, journals, total in cases:
            with self.subTest(case=name):
                output = self.private / f"{name}.csv"
                result = self._generate(name, output)
                manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
                validation = result.conversion_result.output_validation_result
                self.assertIsNotNone(validation)
                self.assertTrue(validation.success, validation.validation_results)
                self.assertEqual(validation.record_count, records)
                self.assertEqual(validation.journal_count, journals)
                self.assertEqual(manifest["logical_journal_count"], journals)
                self.assertEqual(manifest["debit_total"], total)
                self.assertEqual(manifest["credit_total"], total)

    def test_compound_1d3c_generates_three_records_one_journal(self) -> None:
        result = self._generate("compound_1d3c", self.private / "compound.csv")
        self.assertEqual(result.conversion_result.output_record_count, 3)
        self.assertEqual(result.conversion_result.output_journal_count, 1)

    def test_subaccount_requires_and_uses_explicit_parent_context(self) -> None:
        self._write_profile(self.profile_path, include_subaccount=True)
        self._write_context(self.context_path, include_subaccount=True)
        result = self._generate("simple_with_subaccount", self.private / "sub.csv")
        self.assertEqual(result.conversion_result.output_journal_count, 1)
        rows = list(csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932"), newline="")))
        self.assertEqual(rows[1][16:18], ["0001", "テスト銀行"])

    def test_no_overwrite_and_private_path_enforced(self) -> None:
        output = self.private / "existing.csv"
        output.write_bytes(b"keep")
        with self.assertRaisesRegex(JdlProbeError, "上書きしません"):
            self._generate("simple_no_tax", output)
        self.assertEqual(output.read_bytes(), b"keep")
        with self.assertRaisesRegex(JdlProbeError, "private root"):
            self._generate("simple_no_tax", self.root / "outside.csv")

    def test_missing_account_evidence_and_tax_probe_block(self) -> None:
        self._write_profile(self.profile_path, account_names=("現金",))
        with self.assertRaises(JdlProbeError) as account_error:
            self._generate("simple_no_tax", self.private / "missing.csv")
        self.assertIn(account_error.exception.code, {"PROBE_CONVERSION_BLOCKED", "PROBE_INPUT_ERROR"})
        with self.assertRaises(JdlProbeError) as tax_error:
            self._generate("simple_with_tax", self.private / "tax.csv")
        self.assertEqual(
            tax_error.exception.code,
            "PROBE_BLOCKED_MISSING_JDL_TAX_EVIDENCE",
        )
        self.assertFalse((self.private / "tax.csv").exists())

    def test_all_tax_cases_block_without_guessed_jdl_values(self) -> None:
        for case_name in sorted(TAX_PROBE_CASES):
            with self.subTest(case=case_name):
                output = self.private / f"{case_name}.csv"
                with self.assertRaises(JdlProbeError) as caught:
                    self._generate(case_name, output)
                self.assertEqual(
                    caught.exception.code,
                    "PROBE_BLOCKED_MISSING_JDL_TAX_EVIDENCE",
                )
                self.assertFalse(output.exists())

    def test_tax_result_template_is_private_safe_and_no_overwrite(self) -> None:
        destination = self.private / "tax_sales_10_result.json"
        generator = JdlProbeGenerator(self.private)
        generator.write_tax_result_template(
            case_name="tax_sales_10", destination=destination
        )
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["result_status"], "UNTESTED")
        self.assertIsNone(payload["imported"])
        self.assertFalse(payload["mapping_promotion_allowed"])
        self.assertTrue(payload["NOT_FOR_PRODUCTION"])
        serialized = json.dumps(payload, ensure_ascii=False)
        for value in ("課税売上 10%", "現金", "普通預金"):
            self.assertNotIn(value, serialized)
        with self.assertRaises(JdlProbeError):
            generator.write_tax_result_template(
                case_name="tax_sales_10", destination=destination
            )

    def test_manifest_is_privacy_safe_and_temporary_source_is_removed(self) -> None:
        before = {path.name for path in self.private.iterdir()}
        result = self._generate("simple_no_tax", self.private / "safe.csv")
        text = result.manifest_path.read_text(encoding="utf-8")
        for raw in ("現金", "普通預金", "JDL-PROBE-A", "2026/10/20"):
            self.assertNotIn(raw, text)
        after = {path.name for path in self.private.iterdir()}
        self.assertEqual(after - before, {"safe.csv", "safe.manifest.json"})

    def test_registry_remains_unavailable_for_moneyforward(self) -> None:
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.assertEqual(registry.get_exact_input(source).status, AdapterAvailabilityStatus.UNAVAILABLE)
        self.assertFalse(registry.has_conversion_pair(source, target))

    def _generate(self, case: str, output: Path):
        return JdlProbeGenerator(self.private).generate(
            case_name=case,
            output_path=output,
            profile_path=self.profile_path,
            context_path=self.context_path,
        )

    def _write_profile(self, path: Path, account_names=("現金", "普通預金", "当座預金", "小口現金"), include_subaccount=False) -> None:
        codes = {"現金": "1001", "普通預金": "1002", "当座預金": "1003", "小口現金": "1004"}
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        profile = ConversionProfile(
            profile_id="mf-jdl-probe-test",
            profile_name="Synthetic probe test",
            source_format_identity=moneyforward_cloud_journal_export_observed_schema().identity,
            target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings={
                name: MappingValue(
                    source_value=name,
                    target_value=name,
                    status=MappingStatus.USER_CONFIRMED,
                    metadata={"target_code": codes[name], "target_formal_name": name},
                )
                for name in account_names
            },
            subaccount_context_mappings=(
                {
                    MappingKey(MappingType.SUBACCOUNT, "テスト銀行", "普通預金"): MappingValue(
                        source_value="テスト銀行", target_value="テスト銀行",
                        status=MappingStatus.USER_CONFIRMED,
                        parent_account="普通預金",
                        metadata={"target_code": "1", "output_code": "0001", "output_name": "テスト銀行"},
                    )
                }
                if include_subaccount else {}
            ),
            created_at=now,
            updated_at=now,
        )
        path.write_text(ConversionProfileStore(self.private / "unused").to_json_text(profile), encoding="utf-8")

    def _write_context(self, path: Path, include_subaccount=False) -> None:
        codes = {"現金": "1001", "普通預金": "1002", "当座預金": "1003", "小口現金": "1004"}
        payload = {
            "schema_version": "1", "product": "JDL IBEX 出納帳", "version": "35.5",
            "account_master": [
                {"mapping_value": name, "target_master_code": code, "target_name": name, "target_formal_name": name}
                for name, code in codes.items()
            ],
            "subaccounts": ([{
                "parent_account": "普通預金", "mapping_value": "テスト銀行",
                "target_master_code": "1", "output_code": "0001",
                "output_name": "テスト銀行", "output_representation_confirmed": True,
                "parent_account_code": "1002", "target_name": "テスト銀行",
            }] if include_subaccount else []),
            "departments": [], "tax_processing_mode": "EXEMPT",
            "department_processing_enabled": False, "standard_taxation_confirmed": False,
            "individual_credit_method_confirmed": False, "confirmation_state": "CONFIRMED",
            "provenance": "USER_CONFIRMED_RUNTIME_SNAPSHOT", "no_fuzzy_matching": True,
            "no_automatic_replacement": True,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _context(self):
        from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
        return JdlTargetContextLoader().load(self.context_path)


if __name__ == "__main__":
    unittest.main()

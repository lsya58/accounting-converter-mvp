from __future__ import annotations

import csv
import hashlib
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
from accounting_converter.tools.jdl_tax_evidence import (
    EVIDENCE_ID_JDL_PURCHASE_10_INCLUSIVE_HAND,
    EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP,
    EVIDENCE_ID_MF_JDL_SALES_10_SUBACCOUNT_ROUNDTRIP,
    EVIDENCE_ID_MF_JDL_PURCHASE_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
    EVIDENCE_ID_MF_JDL_SALES_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
    EVIDENCE_ID_MF_JDL_NON_TAXABLE_PURCHASE_SUBACCOUNT_ROUNDTRIP,
    EVIDENCE_ID_MF_JDL_OUT_OF_SCOPE_SUBACCOUNT_ROUNDTRIP,
    JdlTaxEvidenceError,
    HUMAN_TAX_CASES,
    analyze_scoped_tax_human_evidence,
    analyze_reduced_8_subaccount_human_evidence,
    analyze_purchase_10_inclusive_evidence,
    compare_sales_10_roundtrip,
    compare_sales_10_subaccount_roundtrip,
    compare_purchase_10_roundtrip,
    compare_purchase_reduced_8_roundtrip,
    compare_purchase_reduced_8_subaccount_roundtrip,
    compare_sales_reduced_8_subaccount_roundtrip,
    compare_non_taxable_purchase_subaccount_roundtrip,
    compare_out_of_scope_subaccount_roundtrip,
)
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
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
                "tax_sales_10_with_subaccount",
                "tax_purchase_reduced_8",
                "tax_purchase_reduced_8_with_subaccount",
                "tax_purchase_10",
                "tax_sales_reduced_8",
                "tax_sales_reduced_8_with_subaccount",
                "tax_purchase_reduced_8",
                "tax_purchase_reduced_8_with_subaccount",
                "tax_non_taxable_purchase",
                "tax_non_taxable_purchase_with_subaccount",
                "tax_out_of_scope",
                "tax_out_of_scope_with_subaccount",
            },
        )
        self.assertNotIn("compound_3d1c", names)
        purchase = next(
            item for item in PROBE_DEFINITIONS if item.name == "tax_purchase_10"
        )
        self.assertEqual(
            purchase.availability, "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL"
        )
        sales_sub = next(
            item
            for item in PROBE_DEFINITIONS
            if item.name == "tax_sales_10_with_subaccount"
        )
        self.assertEqual(
            sales_sub.availability, "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL"
        )
        reduced_purchase_sub = next(
            item
            for item in PROBE_DEFINITIONS
            if item.name == "tax_purchase_reduced_8_with_subaccount"
        )
        self.assertEqual(
            reduced_purchase_sub.availability,
            "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL",
        )
        reduced_sales_sub = next(
            item
            for item in PROBE_DEFINITIONS
            if item.name == "tax_sales_reduced_8_with_subaccount"
        )
        self.assertEqual(
            reduced_sales_sub.availability,
            "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL",
        )
        non_taxable_sub = next(
            item
            for item in PROBE_DEFINITIONS
            if item.name == "tax_non_taxable_purchase_with_subaccount"
        )
        self.assertEqual(
            non_taxable_sub.availability,
            "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL",
        )
        out_of_scope_sub = next(
            item
            for item in PROBE_DEFINITIONS
            if item.name == "tax_out_of_scope_with_subaccount"
        )
        self.assertEqual(
            out_of_scope_sub.availability,
            "VERIFIED_BY_REAL_IMPORT_EXPERIMENTAL",
        )
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

    def test_unsupported_tax_cases_block_without_guessed_jdl_values(self) -> None:
        for case_name in sorted(
            TAX_PROBE_CASES
            - {
                "tax_purchase_10",
                "tax_sales_10",
                "tax_sales_10_with_subaccount",
                "tax_purchase_reduced_8",
                "tax_purchase_reduced_8_with_subaccount",
                "tax_sales_reduced_8_with_subaccount",
                "tax_non_taxable_purchase_with_subaccount",
                "tax_non_taxable_purchase",
                "tax_out_of_scope",
                "tax_out_of_scope_with_subaccount",
            }
        ):
            with self.subTest(case=case_name):
                output = self.private / f"{case_name}.csv"
                with self.assertRaises(JdlProbeError) as caught:
                    self._generate(case_name, output)
                self.assertEqual(
                    caught.exception.code,
                    "PROBE_BLOCKED_MISSING_JDL_TAX_EVIDENCE",
                )
                self.assertFalse(output.exists())

    def test_tax_purchase_10_uses_explicit_mapping_and_output_adapter(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_purchase_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
        )

        result = self._generate(
            "tax_purchase_10", self.private / "tax_purchase_10.csv"
        )
        rows = list(
            csv.reader(
                io.StringIO(result.output_path.read_text(encoding="cp932"), newline="")
            )
        )
        header = rows[0]
        row = rows[1]

        self.assertEqual(result.conversion_result.status.value, "SUCCESS")
        self.assertTrue(result.conversion_result.output_validation_result.success)
        self.assertEqual(row[header.index("借方課区")], "仕　入")
        self.assertEqual(row[header.index("借方税区")], "10%")
        self.assertEqual(row[header.index("借方税入力方法")], "")
        self.assertEqual(row[header.index("借方消費税")], "")
        self.assertEqual(row[header.index("貸方税区")], "")

    def test_tax_purchase_10_does_not_generate_without_explicit_tax_mapping(self) -> None:
        self._write_profile(
            self.profile_path, account_names=("消耗品費", "現金")
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
        )

        with self.assertRaises(JdlProbeError) as caught:
            self._generate("tax_purchase_10", self.private / "blocked.csv")

        self.assertEqual(caught.exception.code, "PROBE_CONVERSION_BLOCKED")
        self.assertFalse((self.private / "blocked.csv").exists())

    def test_tax_purchase_reduced_8_without_subaccount_is_always_blocked(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_purchase_reduced_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
        )

        with self.assertRaises(JdlProbeError) as caught:
            JdlProbeGenerator(self.private).generate(
                case_name="tax_purchase_reduced_8",
                output_path=self.private / "tax-purchase-reduced.csv",
                profile_path=self.profile_path,
                context_path=self.context_path,
                journal_date="2026/11/01",
            )
        self.assertEqual(
            caught.exception.code, "PROBE_BLOCKED_TARGET_SUBACCOUNT_REQUIRED"
        )

    def test_tax_purchase_reduced_8_blocks_wrong_rate_and_subaccount_master(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_purchase_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
        )
        with self.assertRaises(JdlProbeError):
            self._generate(
                "tax_purchase_reduced_8", self.private / "wrong-rate.csv"
            )

        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_purchase_reduced_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
        )
        with self.assertRaises(JdlProbeError):
            self._generate(
                "tax_purchase_reduced_8", self.private / "blank-required-sub.csv"
            )

    def test_tax_purchase_reduced_8_allows_only_exact_parent_subaccount(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_purchase_reduced_tax=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        result = JdlProbeGenerator(self.private).generate(
            case_name="tax_purchase_reduced_8_with_subaccount",
            output_path=self.private / "correct-parent.csv",
            profile_path=self.profile_path,
            context_path=self.context_path,
            journal_date="2026/11/01",
        )
        rows = list(
            csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932")))
        )
        header, row = rows
        self.assertEqual(row[header.index("借方補助")], "1")
        self.assertEqual(row[header.index("借方補助名称")], "架空仕入補助")
        self.assertEqual(row[header.index("日付")], "20261101")

        wrong_profile = self.private / "wrong-parent-profile.json"
        self._write_profile(
            wrong_profile,
            account_names=("消耗品費", "現金", "普通預金"),
            include_purchase_reduced_tax=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空仕入補助",
        )
        with self.assertRaises(JdlProbeError):
            JdlProbeGenerator(self.private).generate(
                case_name="tax_purchase_reduced_8",
                output_path=self.private / "wrong-parent.csv",
                profile_path=wrong_profile,
                context_path=self.context_path,
            )

    def test_non_taxable_purchase_requires_exact_parent_subaccount(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_non_taxable_purchase=True,
        )
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        with self.assertRaises(JdlProbeError) as blank:
            self._generate(
                "tax_non_taxable_purchase",
                self.private / "non-taxable-blank.csv",
            )
        self.assertEqual(
            blank.exception.code, "PROBE_BLOCKED_TARGET_SUBACCOUNT_REQUIRED"
        )
        with self.assertRaises(JdlProbeError):
            self._generate(
                "tax_non_taxable_purchase_with_subaccount",
                self.private / "non-taxable-missing-map.csv",
            )

        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_non_taxable_purchase=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        result = JdlProbeGenerator(self.private).generate(
            case_name="tax_non_taxable_purchase_with_subaccount",
            output_path=self.private / "non-taxable-sub.csv",
            profile_path=self.profile_path,
            context_path=self.context_path,
            journal_date="2026/11/05",
        )
        rows = list(csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932"))))
        header, row = rows
        self.assertEqual(row[header.index("日付")], "20261105")
        self.assertEqual(row[header.index("借方補助")], "1")
        self.assertEqual(row[header.index("借方課区")], "非仕入")
        self.assertEqual(row[header.index("借方税区")], "")
        self.assertEqual(row[header.index("貸方課区")], "")
        self.assertTrue(result.conversion_result.output_validation_result.success)

        wrong_profile = self.private / "non-taxable-wrong-parent.json"
        self._write_profile(
            wrong_profile,
            account_names=("消耗品費", "現金", "普通預金"),
            include_non_taxable_purchase=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空仕入補助",
        )
        with self.assertRaises(JdlProbeError):
            JdlProbeGenerator(self.private).generate(
                case_name="tax_non_taxable_purchase_with_subaccount",
                output_path=self.private / "non-taxable-wrong-parent.csv",
                profile_path=wrong_profile,
                context_path=self.context_path,
            )

    def test_non_taxable_human_evidence_and_roundtrip_comparator_are_strict(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        human_row = self._tax_row("non-taxable human", reexport=True)
        human_row[positions["借方課区"]] = "非仕入"
        human_row[positions["借方税区"]] = ""
        human = self.private / "non-taxable-human.csv"
        self._write_official_rows(human, [human_row], preamble=True)

        observation = analyze_scoped_tax_human_evidence(
            human, "tax_non_taxable_purchase"
        )
        self.assertTrue(observation.tax_scope_present)
        self.assertFalse(observation.tax_category_present)

        candidate_row = list(human_row)
        candidate_row[positions["摘要"]] = "non-taxable probe"
        candidate_row[positions["借方補助"]] = "1"
        candidate_row[positions["借方補助名称"]] = "架空仕入補助"
        for name in (
            "借方科目",
            "借方科目正式名称",
            "貸方科目",
            "貸方科目正式名称",
            "借方消費税",
            "貸方消費税",
        ):
            candidate_row[positions[name]] = ""
        actual_row = list(human_row)
        actual_row[positions["摘要"]] = "non-taxable probe"
        actual_row[positions["借方補助"]] = "1"
        actual_row[positions["借方補助名称"]] = "架空仕入補助"
        candidate = self.private / "non-taxable-candidate.csv"
        reexport = self.private / "non-taxable-reexport.csv"
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [actual_row], preamble=True)
        comparison = compare_non_taxable_purchase_subaccount_roundtrip(
            human, candidate, reexport
        )
        self.assertTrue(comparison.passed)
        result = comparison.privacy_safe_result()
        self.assertEqual(
            result["evidence_id"],
            EVIDENCE_ID_MF_JDL_NON_TAXABLE_PURCHASE_SUBACCOUNT_ROUNDTRIP,
        )
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")
        self.assertFalse(result["mapping_promotion_allowed"])
        self.assertFalse(result["production_ready"])

        out_of_scope = list(human_row)
        out_of_scope[positions["借方課区"]] = ""
        out_path = self.private / "out-of-scope.csv"
        self._write_official_rows(out_path, [out_of_scope], preamble=True)
        with self.assertRaises(JdlTaxEvidenceError):
            analyze_scoped_tax_human_evidence(
                out_path, "tax_non_taxable_purchase"
            )

    def test_non_taxable_probe_blocks_other_tax_literals(self) -> None:
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        for label, target, scope in (
            ("taxable-10", "10%", "仕　入"),
            ("reduced-8", "軽減8%", "仕　入"),
            ("out-of-scope", "", ""),
        ):
            with self.subTest(label=label):
                profile = self.private / f"{label}.json"
                self._write_profile(
                    profile,
                    account_names=("消耗品費", "現金"),
                    include_non_taxable_purchase=True,
                    non_taxable_target=target,
                    non_taxable_scope=scope,
                    include_subaccount=True,
                    subaccount_parent="消耗品費",
                    subaccount_name="架空仕入補助",
                    subaccount_output_code="1",
                )
                with self.assertRaises(JdlProbeError):
                    JdlProbeGenerator(self.private).generate(
                        case_name="tax_non_taxable_purchase_with_subaccount",
                        output_path=self.private / f"{label}.csv",
                        profile_path=profile,
                        context_path=self.context_path,
                    )

    def test_out_of_scope_requires_explicit_profile_and_parent_subaccount(self) -> None:
        self._write_context(
            self.context_path,
            account_names=("消耗品費", "現金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_out_of_scope=True,
        )
        with self.assertRaises(JdlProbeError) as blank:
            self._generate(
                "tax_out_of_scope", self.private / "out-of-scope-blank.csv"
            )
        self.assertEqual(
            blank.exception.code, "PROBE_BLOCKED_TARGET_SUBACCOUNT_REQUIRED"
        )
        with self.assertRaises(JdlProbeError):
            self._generate(
                "tax_out_of_scope_with_subaccount",
                self.private / "out-of-scope-missing-map.csv",
            )

        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_out_of_scope=True,
            include_subaccount=True,
            subaccount_parent="消耗品費",
            subaccount_name="架空仕入補助",
            subaccount_output_code="1",
        )
        generated = JdlProbeGenerator(self.private).generate(
            case_name="tax_out_of_scope_with_subaccount",
            output_path=self.private / "out-of-scope-sub.csv",
            profile_path=self.profile_path,
            context_path=self.context_path,
            journal_date="2026/11/06",
        )
        rows = list(csv.reader(io.StringIO(generated.output_path.read_text(encoding="cp932"))))
        header, row = rows
        self.assertEqual(row[header.index("日付")], "20261106")
        self.assertEqual(row[header.index("借方補助")], "1")
        self.assertEqual(row[header.index("借方課区")], "")
        self.assertEqual(row[header.index("借方税区")], "")
        self.assertTrue(generated.conversion_result.output_validation_result.success)

        wrong_profile = self.private / "out-of-scope-wrong-parent.json"
        self._write_profile(
            wrong_profile,
            account_names=("消耗品費", "現金", "普通預金"),
            include_out_of_scope=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空仕入補助",
        )
        with self.assertRaises(JdlProbeError):
            JdlProbeGenerator(self.private).generate(
                case_name="tax_out_of_scope_with_subaccount",
                output_path=self.private / "out-of-scope-wrong-parent.csv",
                profile_path=wrong_profile,
                context_path=self.context_path,
            )

    def test_out_of_scope_roundtrip_requires_manifest_semantic_identity(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        human_row = self._tax_row("out-of-scope human", reexport=True)
        for name in (
            "借方課区", "借方税区", "借方税入力方法",
            "貸方課区", "貸方税区", "貸方税入力方法",
        ):
            human_row[positions[name]] = ""
        human = self.private / "out-of-scope-human.csv"
        self._write_official_rows(human, [human_row], preamble=True)
        observed = analyze_scoped_tax_human_evidence(human, "tax_out_of_scope")
        self.assertFalse(observed.tax_scope_present)
        self.assertFalse(observed.tax_category_present)

        candidate_row = list(human_row)
        candidate_row[positions["摘要"]] = "out-of-scope probe"
        candidate_row[positions["借方補助"]] = "1"
        candidate_row[positions["借方補助名称"]] = "架空仕入補助"
        for name in (
            "借方科目", "借方科目正式名称", "貸方科目",
            "貸方科目正式名称", "借方消費税", "貸方消費税",
        ):
            candidate_row[positions[name]] = ""
        actual_row = list(human_row)
        actual_row[positions["摘要"]] = "out-of-scope probe"
        actual_row[positions["借方補助"]] = "1"
        actual_row[positions["借方補助名称"]] = "架空仕入補助"
        candidate = self.private / "out-of-scope-candidate.csv"
        reexport = self.private / "out-of-scope-reexport.csv"
        manifest = self.private / "out-of-scope.manifest.json"
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [actual_row], preamble=True)

        manifest.write_text(json.dumps({
            "probe_case": "simple_no_tax",
            "evidence_scope": [],
            "NOT_FOR_PRODUCTION": True,
        }), encoding="utf-8")
        with self.assertRaises(JdlTaxEvidenceError):
            compare_out_of_scope_subaccount_roundtrip(
                human, candidate, manifest, self.profile_path, reexport
            )

        self._write_profile(
            self.profile_path,
            account_names=("消耗品費", "現金"),
            include_out_of_scope=True,
        )
        profile_hash = hashlib.sha256(self.profile_path.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({
            "probe_case": "tax_out_of_scope_with_subaccount",
            "evidence_scope": [
                "SUPPORTED_1111_TAX_OUT_OF_SCOPE_SUBACCOUNT_INCLUDED"
            ],
            "NOT_FOR_PRODUCTION": True,
            "conversion_profile_sha256": profile_hash,
        }), encoding="utf-8")
        comparison = compare_out_of_scope_subaccount_roundtrip(
            human, candidate, manifest, self.profile_path, reexport
        )
        self.assertTrue(comparison.passed)
        result = comparison.privacy_safe_result()
        self.assertEqual(
            result["evidence_id"],
            EVIDENCE_ID_MF_JDL_OUT_OF_SCOPE_SUBACCOUNT_ROUNDTRIP,
        )
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")
        self.assertFalse(result["mapping_promotion_allowed"])
        self.assertFalse(result["production_ready"])

    def test_reduced_8_subaccount_human_evidence_separates_description_policy(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        debit = self._tax_row("strict debit identity", reexport=True)
        debit[positions["借方税区"]] = "軽減8%"
        debit[positions["借方補助"]] = "1"
        debit[positions["借方補助名称"]] = "架空借方補助"
        credit = self._tax_row("credit input residue", reexport=True)
        for name in ("借方課区", "借方税区"):
            credit[positions[name]] = ""
        credit[positions["貸方課区"]] = "売一種"
        credit[positions["貸方税区"]] = "軽減8%"
        credit[positions["貸方補助"]] = "2"
        credit[positions["貸方補助名称"]] = "架空貸方補助"
        evidence = self.private / "reduced-sub-human.csv"
        self._write_official_rows(evidence, [debit, credit], preamble=True)

        observation = analyze_reduced_8_subaccount_human_evidence(evidence)
        manifest = observation.privacy_safe_manifest()

        self.assertTrue(manifest["debit_parent_subaccount_reduced_8_valid"])
        self.assertTrue(manifest["credit_parent_subaccount_reduced_8_valid"])
        self.assertTrue(manifest["debit_description_comparison_allowed"])
        self.assertFalse(manifest["credit_description_comparison_allowed"])
        self.assertNotIn("input residue", json.dumps(manifest, ensure_ascii=False))

        candidate = list(debit)
        candidate[positions["摘要"]] = "reduced sub probe"
        for name in (
            "借方科目",
            "借方科目正式名称",
            "貸方科目",
            "貸方科目正式名称",
            "借方消費税",
            "貸方消費税",
        ):
            candidate[positions[name]] = ""
        actual = list(debit)
        actual[positions["摘要"]] = "reduced sub probe"
        candidate_path = self.private / "reduced-sub-candidate.csv"
        reexport_path = self.private / "reduced-sub-reexport.csv"
        self._write_official_rows(candidate_path, [candidate])
        self._write_official_rows(reexport_path, [actual], preamble=True)
        comparison = compare_purchase_reduced_8_subaccount_roundtrip(
            evidence, candidate_path, reexport_path
        )
        self.assertTrue(comparison.passed)
        self.assertTrue(comparison.parent_scoped_subaccount_match)
        result = comparison.privacy_safe_result()
        self.assertEqual(
            result["evidence_id"],
            EVIDENCE_ID_MF_JDL_PURCHASE_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
        )
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")
        self.assertFalse(result["mapping_promotion_allowed"])
        self.assertFalse(result["production_ready"])

        sales_candidate = list(credit)
        sales_candidate[positions["摘要"]] = "new sales reduced probe"
        for name in (
            "借方科目",
            "借方科目正式名称",
            "貸方科目",
            "貸方科目正式名称",
            "借方消費税",
            "貸方消費税",
        ):
            sales_candidate[positions[name]] = ""
        sales_actual = list(credit)
        sales_actual[positions["摘要"]] = "new sales reduced probe"
        sales_candidate_path = self.private / "sales-reduced-sub-candidate.csv"
        sales_reexport_path = self.private / "sales-reduced-sub-reexport.csv"
        self._write_official_rows(sales_candidate_path, [sales_candidate])
        self._write_official_rows(sales_reexport_path, [sales_actual], preamble=True)
        sales_comparison = compare_sales_reduced_8_subaccount_roundtrip(
            evidence, sales_candidate_path, sales_reexport_path
        )
        self.assertTrue(sales_comparison.passed)
        self.assertTrue(sales_comparison.description_preserved)
        sales_result = sales_comparison.privacy_safe_result()
        self.assertEqual(
            sales_result["evidence_id"],
            EVIDENCE_ID_MF_JDL_SALES_REDUCED_8_SUBACCOUNT_ROUNDTRIP,
        )
        self.assertEqual(
            sales_result["evidence_level"], "VERIFIED_BY_REAL_IMPORT"
        )
        self.assertFalse(sales_result["mapping_promotion_allowed"])
        self.assertFalse(sales_result["production_ready"])

    def test_tax_sales_10_uses_credit_side_scoped_evidence(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高"),
            taxable_included=True,
        )

        result = self._generate("tax_sales_10", self.private / "tax_sales_10.csv")
        rows = list(csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932"), newline="")))
        header, row = rows

        self.assertEqual(result.conversion_result.status.value, "SUCCESS")
        self.assertEqual(row[header.index("貸方課区")], "売一種")
        self.assertEqual(row[header.index("貸方税区")], "10%")
        self.assertEqual(row[header.index("借方課区")], "")
        self.assertEqual(row[header.index("借方税区")], "")
        self.assertEqual(row[header.index("日付")], "20261030")

    def test_tax_sales_10_wrong_context_and_missing_mapping_are_blocked(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_tax=True,
        )
        self._write_context(
            self.context_path, account_names=("現金", "売上高")
        )
        with self.assertRaises(JdlProbeError):
            self._generate("tax_sales_10", self.private / "wrong-context.csv")

        self._write_profile(self.profile_path, account_names=("現金", "売上高"))
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高"),
            taxable_included=True,
        )
        with self.assertRaises(JdlProbeError):
            self._generate("tax_sales_10", self.private / "missing-map.csv")

    def test_sales_account_with_configured_subaccount_blocks_blank_candidate(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="売上高",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        with self.assertRaises(JdlProbeError) as caught:
            self._generate("tax_sales_10", self.private / "blank-sub.csv")
        self.assertEqual(caught.exception.code, "PROBE_CONVERSION_BLOCKED")

    def test_tax_sales_10_with_parent_scoped_subaccount_generates(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_tax=True,
            include_subaccount=True,
            subaccount_parent="売上高",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="売上高",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        result = self._generate(
            "tax_sales_10_with_subaccount",
            self.private / "tax-sales-sub.csv",
        )
        rows = list(csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932"), newline="")))
        header, row = rows
        self.assertEqual(row[header.index("貸方補助")], "1")
        self.assertEqual(row[header.index("貸方補助名称")], "架空売上補助")
        self.assertEqual(row[header.index("貸方課区")], "売一種")

    def test_tax_sales_10_with_wrong_parent_subaccount_is_blocked(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高", "普通預金"),
            include_sales_tax=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高", "普通預金"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        with self.assertRaises(JdlProbeError):
            self._generate("tax_sales_10_with_subaccount", self.private / "wrong-parent.csv")

    def test_tax_sales_reduced_8_requires_exact_parent_subaccount(self) -> None:
        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_reduced_tax=True,
        )
        self._write_context(
            self.context_path,
            account_names=("現金", "売上高"),
            taxable_included=True,
            include_subaccount=True,
            subaccount_parent="売上高",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        with self.assertRaises(JdlProbeError):
            self._generate(
                "tax_sales_reduced_8_with_subaccount",
                self.private / "missing-sub-map.csv",
            )

        self._write_profile(
            self.profile_path,
            account_names=("現金", "売上高"),
            include_sales_reduced_tax=True,
            include_subaccount=True,
            subaccount_parent="売上高",
            subaccount_name="架空売上補助",
            subaccount_output_code="1",
        )
        result = JdlProbeGenerator(self.private).generate(
            case_name="tax_sales_reduced_8_with_subaccount",
            output_path=self.private / "sales-reduced-sub.csv",
            profile_path=self.profile_path,
            context_path=self.context_path,
            journal_date="2026/11/04",
        )
        rows = list(csv.reader(io.StringIO(result.output_path.read_text(encoding="cp932"))))
        header, row = rows
        self.assertEqual(row[header.index("日付")], "20261104")
        self.assertEqual(row[header.index("貸方補助")], "1")
        self.assertEqual(row[header.index("貸方補助名称")], "架空売上補助")
        self.assertEqual(row[header.index("貸方課区")], "売一種")
        self.assertEqual(row[header.index("貸方税区")], "軽減8%")
        self.assertEqual(row[header.index("借方税区")], "")

        wrong_profile = self.private / "sales-reduced-wrong-parent.json"
        self._write_profile(
            wrong_profile,
            account_names=("現金", "売上高", "普通預金"),
            include_sales_reduced_tax=True,
            include_subaccount=True,
            subaccount_parent="普通預金",
            subaccount_name="架空売上補助",
        )
        with self.assertRaises(JdlProbeError):
            JdlProbeGenerator(self.private).generate(
                case_name="tax_sales_reduced_8_with_subaccount",
                output_path=self.private / "sales-reduced-wrong-parent.csv",
                profile_path=wrong_profile,
                context_path=self.context_path,
            )

    def test_tax_sales_10_roundtrip_comparison_requires_unique_match(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        human_row = self._tax_row("sales probe", reexport=True)
        human_row[positions["借方課区"]] = ""
        human_row[positions["借方税区"]] = ""
        human_row[positions["貸方課区"]] = "売一種"
        human_row[positions["貸方税区"]] = "10%"
        candidate_row = list(human_row)
        for name in ("借方科目", "借方科目正式名称", "貸方科目", "貸方科目正式名称", "借方消費税", "貸方消費税"):
            candidate_row[positions[name]] = ""
        human = self.private / "sales-human.csv"
        candidate = self.private / "sales-candidate.csv"
        reexport = self.private / "sales-reexport.csv"
        self._write_official_rows(human, [human_row], preamble=True)
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [human_row], preamble=True)

        comparison = compare_sales_10_roundtrip(human, candidate, reexport)

        self.assertTrue(comparison.passed)
        self.assertEqual(comparison.probe_case, "tax_sales_10")

    def test_tax_sales_10_subaccount_roundtrip_is_strict_and_scoped(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        human_row = self._tax_row("sales sub human", reexport=True)
        for name in ("借方課区", "借方税区"):
            human_row[positions[name]] = ""
        human_row[positions["貸方課区"]] = "売一種"
        human_row[positions["貸方税区"]] = "10%"
        human_row[positions["貸方補助"]] = "1"
        human_row[positions["貸方補助名称"]] = "架空売上補助"
        candidate_row = list(human_row)
        candidate_row[positions["摘要"]] = "sales sub probe"
        for name in (
            "借方科目",
            "借方科目正式名称",
            "貸方科目",
            "貸方科目正式名称",
            "借方消費税",
            "貸方消費税",
        ):
            candidate_row[positions[name]] = ""
        actual_row = list(human_row)
        actual_row[positions["摘要"]] = "sales sub probe"
        human = self.private / "sales-sub-human.csv"
        candidate = self.private / "sales-sub-candidate.csv"
        reexport = self.private / "sales-sub-reexport.csv"
        self._write_official_rows(human, [human_row], preamble=True)
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [actual_row], preamble=True)

        comparison = compare_sales_10_subaccount_roundtrip(
            human, candidate, reexport
        )
        result = comparison.privacy_safe_result()

        self.assertTrue(comparison.passed)
        self.assertTrue(comparison.parent_scoped_subaccount_match)
        self.assertTrue(comparison.date_preserved)
        self.assertTrue(comparison.identifier_flag_preserved)
        self.assertEqual(
            result["evidence_id"],
            EVIDENCE_ID_MF_JDL_SALES_10_SUBACCOUNT_ROUNDTRIP,
        )
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")
        self.assertFalse(result["mapping_promotion_allowed"])
        self.assertFalse(result["production_ready"])

        actual_row[positions["貸方補助名称"]] = "別の架空補助"
        self._write_official_rows(
            self.private / "sales-sub-wrong-reexport.csv", [actual_row], preamble=True
        )
        mismatch = compare_sales_10_subaccount_roundtrip(
            human, candidate, self.private / "sales-sub-wrong-reexport.csv"
        )
        self.assertFalse(mismatch.passed)

    def test_purchase_reduced_8_roundtrip_comparator_is_case_specific(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        human_row = self._tax_row("reduced human", reexport=True)
        human_row[positions["借方税区"]] = "軽減8%"
        candidate_row = list(human_row)
        candidate_row[positions["摘要"]] = "reduced probe"
        for name in (
            "借方科目",
            "借方科目正式名称",
            "貸方科目",
            "貸方科目正式名称",
            "借方消費税",
            "貸方消費税",
        ):
            candidate_row[positions[name]] = ""
        actual_row = list(human_row)
        actual_row[positions["摘要"]] = "reduced probe"
        human = self.private / "reduced-human.csv"
        candidate = self.private / "reduced-candidate.csv"
        reexport = self.private / "reduced-reexport.csv"
        self._write_official_rows(human, [human_row], preamble=True)
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [actual_row], preamble=True)

        comparison = compare_purchase_reduced_8_roundtrip(
            human, candidate, reexport
        )

        self.assertTrue(comparison.passed)
        self.assertEqual(comparison.probe_case, "tax_purchase_reduced_8")
        candidate_row[positions["借方税区"]] = "10%"
        self._write_official_rows(
            self.private / "reduced-wrong-rate.csv", [candidate_row]
        )
        with self.assertRaises(JdlTaxEvidenceError):
            compare_purchase_reduced_8_roundtrip(
                human, self.private / "reduced-wrong-rate.csv", reexport
            )

    def test_private_tax_evidence_parser_and_manifest_are_privacy_safe(self) -> None:
        evidence = self.private / "evidence.csv"
        self._write_tax_evidence(evidence)

        observation = analyze_purchase_10_inclusive_evidence(evidence)
        manifest = observation.privacy_safe_manifest()
        serialized = json.dumps(manifest, ensure_ascii=False)

        self.assertEqual(
            manifest["evidence_id"], EVIDENCE_ID_JDL_PURCHASE_10_INCLUSIVE_HAND
        )
        self.assertEqual(manifest["data_row_count"], 1)
        self.assertTrue(manifest["debit_tax_scope_present"])
        self.assertTrue(manifest["debit_tax_category_present"])
        self.assertFalse(manifest["mapping_promotion_allowed"])
        for private_value in ("消耗品費", "現金", "架空証拠摘要", "1100"):
            self.assertNotIn(private_value, serialized)

    def test_private_tax_evidence_parser_rejects_wrong_shape(self) -> None:
        evidence = self.private / "bad.csv"
        evidence.write_bytes(b"bad\r\n")
        with self.assertRaises(JdlTaxEvidenceError):
            analyze_purchase_10_inclusive_evidence(evidence)

    def test_purchase_10_roundtrip_comparison_is_scoped_and_privacy_safe(self) -> None:
        human = self.private / "human.csv"
        candidate = self.private / "candidate.csv"
        reexport = self.private / "reexport.csv"
        human_row = self._tax_row(description="human description", reexport=True)
        candidate_row = self._tax_row(description="candidate description", reexport=False)
        actual_row = self._tax_row(description="candidate description", reexport=True)
        self._write_official_rows(human, [human_row], preamble=True)
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(
            reexport, [human_row, actual_row], preamble=True
        )

        comparison = compare_purchase_10_roundtrip(human, candidate, reexport)
        result = comparison.privacy_safe_result()
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertTrue(comparison.passed)
        self.assertEqual(comparison.candidate_match_count, 1)
        self.assertEqual(
            result["evidence_id"], EVIDENCE_ID_MF_JDL_PURCHASE_10_ROUNDTRIP
        )
        self.assertEqual(result["evidence_level"], "VERIFIED_BY_REAL_IMPORT")
        self.assertFalse(result["mapping_promotion_allowed"])
        self.assertIn("account_master_identity", result["jdl_normalized_field_categories"])
        for private_value in (
            "human description",
            "candidate description",
            "消耗品費",
            "現金",
            "1100",
        ):
            self.assertNotIn(private_value, serialized)

    def test_purchase_10_roundtrip_does_not_guess_ambiguous_match(self) -> None:
        human = self.private / "human.csv"
        candidate = self.private / "candidate.csv"
        reexport = self.private / "reexport.csv"
        human_row = self._tax_row(description="human description", reexport=True)
        candidate_row = self._tax_row(description="candidate description", reexport=False)
        actual_row = self._tax_row(description="candidate description", reexport=True)
        self._write_official_rows(human, [human_row], preamble=True)
        self._write_official_rows(candidate, [candidate_row])
        self._write_official_rows(reexport, [actual_row, actual_row], preamble=True)

        comparison = compare_purchase_10_roundtrip(human, candidate, reexport)

        self.assertFalse(comparison.passed)
        self.assertEqual(comparison.candidate_match_count, 2)

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

    def _write_profile(self, path: Path, account_names=("現金", "普通預金", "当座預金", "小口現金"), include_subaccount=False, include_purchase_tax=False, include_purchase_reduced_tax=False, include_sales_tax=False, include_sales_reduced_tax=False, include_non_taxable_purchase=False, include_out_of_scope=False, non_taxable_target="", non_taxable_scope="非仕入", subaccount_parent="普通預金", subaccount_name="テスト銀行", subaccount_output_code="0001") -> None:
        codes = {"現金": "1001", "普通預金": "1002", "当座預金": "1003", "小口現金": "1004", "消耗品費": "8001", "売上高": "4001"}
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
                    MappingKey(MappingType.SUBACCOUNT, subaccount_name, subaccount_parent): MappingValue(
                        source_value=subaccount_name, target_value=subaccount_name,
                        status=MappingStatus.USER_CONFIRMED,
                        parent_account=subaccount_parent,
                        metadata={"target_code": "1", "output_code": subaccount_output_code, "output_name": subaccount_name},
                    )
                }
                if include_subaccount else {}
            ),
            tax_mappings={
                **({
                    "課税仕入 10%": MappingValue(
                        source_value="課税仕入 10%",
                        target_value="10%",
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={
                            "jdl_tax_scope": "仕　入",
                            "jdl_evidence_id": EVIDENCE_ID_JDL_PURCHASE_10_INCLUSIVE_HAND,
                        },
                    )
                } if include_purchase_tax else {}),
                **({
                    "課税仕入 (軽)8%": MappingValue(
                        source_value="課税仕入 (軽)8%",
                        target_value="軽減8%",
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={
                            "jdl_tax_scope": "仕　入",
                            "jdl_evidence_id": "EVID-JDL-TAX-PURCHASE-REDUCED-8-INCLUSIVE-HAND-001",
                        },
                    )
                } if include_purchase_reduced_tax else {}),
                **({
                    "課税売上 10%": MappingValue(
                        source_value="課税売上 10%", target_value="10%",
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={"jdl_tax_scope": "売一種", "jdl_evidence_id": "EVID-JDL-TAX-SALES-10-INCLUSIVE-HAND-001"},
                    )
                } if include_sales_tax else {}),
                **({
                    "課税売上 (軽)8%": MappingValue(
                        source_value="課税売上 (軽)8%",
                        target_value="軽減8%",
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={
                            "jdl_tax_scope": "売一種",
                            "jdl_evidence_id": "EVID-JDL-SUBACCOUNT-TAX-REDUCED-8-HAND-001",
                        },
                    )
                } if include_sales_reduced_tax else {}),
                **({
                    "非課税仕入": MappingValue(
                        source_value="非課税仕入",
                        target_value=non_taxable_target,
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={
                            "jdl_tax_scope": non_taxable_scope,
                            "jdl_evidence_id": "EVID-JDL-TAX-NONTAXABLE-PURCHASE-HAND-001",
                        },
                    )
                } if include_non_taxable_purchase else {}),
                **({
                    "対象外": MappingValue(
                        source_value="対象外",
                        target_value="",
                        status=MappingStatus.USER_CONFIRMED,
                        metadata={
                            "jdl_tax_scope": "",
                            "jdl_evidence_id": "EVID-JDL-TAX-OUT-OF-SCOPE-HAND-001",
                        },
                    )
                } if include_out_of_scope else {}),
            },
            created_at=now,
            updated_at=now,
        )
        path.write_text(ConversionProfileStore(self.private / "unused").to_json_text(profile), encoding="utf-8")

    def _write_context(self, path: Path, include_subaccount=False, account_names=("現金", "普通預金", "当座預金", "小口現金"), taxable_included=False, subaccount_parent="普通預金", subaccount_name="テスト銀行", subaccount_output_code="0001") -> None:
        codes = {"現金": "1001", "普通預金": "1002", "当座預金": "1003", "小口現金": "1004", "消耗品費": "8001", "売上高": "4001"}
        payload = {
            "schema_version": "1", "product": "JDL IBEX 出納帳", "version": "35.5",
            "account_master": [
                {"mapping_value": name, "target_master_code": code, "target_name": name, "target_formal_name": name}
                for name, code in codes.items() if name in account_names
            ],
            "subaccounts": ([{
                "parent_account": subaccount_parent, "mapping_value": subaccount_name,
                "target_master_code": "1", "output_code": subaccount_output_code,
                "output_name": subaccount_name, "output_representation_confirmed": True,
                "parent_account_code": codes[subaccount_parent], "target_name": subaccount_name,
            }] if include_subaccount else []),
            "departments": [], "tax_processing_mode": "TAXABLE_TAX_INCLUDED" if taxable_included else "EXEMPT",
            "department_processing_enabled": False, "standard_taxation_confirmed": taxable_included,
            "individual_credit_method_confirmed": taxable_included, "confirmation_state": "CONFIRMED",
            "provenance": "USER_CONFIRMED_RUNTIME_SNAPSHOT", "no_fuzzy_matching": True,
            "no_automatic_replacement": True,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_scoped_human_tax_evidence_cases_are_observed_not_promoted(self) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        positions = {name: index for index, name in enumerate(header)}
        for case_name, (side, scope, category, evidence_id) in HUMAN_TAX_CASES.items():
            with self.subTest(case_name=case_name):
                row = self._tax_row("架空証拠摘要", reexport=True)
                for prefix in ("借方", "貸方"):
                    row[positions[f"{prefix}課区"]] = ""
                    row[positions[f"{prefix}税区"]] = ""
                prefix = "借方" if side == "DEBIT" else "貸方"
                row[positions[f"{prefix}課区"]] = scope
                row[positions[f"{prefix}税区"]] = category
                path = self.private / f"{case_name}.csv"
                self._write_official_rows(path, [row], preamble=True)

                observed = analyze_scoped_tax_human_evidence(path, case_name)

                self.assertEqual(observed.evidence_id, evidence_id)
                self.assertEqual(
                    observed.privacy_safe_manifest()["evidence_level"],
                    "HUMAN_OBSERVED",
                )
                self.assertFalse(
                    observed.privacy_safe_manifest()["mapping_promotion_allowed"]
                )

    def test_scoped_human_tax_evidence_does_not_guess_other_side(self) -> None:
        row = self._tax_row("架空証拠摘要", reexport=True)
        path = self.private / "wrong-side.csv"
        self._write_official_rows(path, [row], preamble=True)
        with self.assertRaises(JdlTaxEvidenceError):
            analyze_scoped_tax_human_evidence(path, "tax_sales_10")

    @staticmethod
    def _write_tax_evidence(path: Path) -> None:
        JdlProbeWorkflowTests._write_official_rows(
            path,
            [JdlProbeWorkflowTests._tax_row("架空証拠摘要", reexport=True)],
            preamble=True,
        )

    @staticmethod
    def _tax_row(description: str, *, reexport: bool) -> list[str]:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        values = {name: "" for name in header}
        values.update({
            "//識別フラグ": "1111", "日付": "20261021",
            "借方科目名称": "消耗品費", "借方課区": "仕　入",
            "借方税区": "10%", "借方金額": "1100",
            "貸方科目名称": "現金", "貸方金額": "1100", "摘要": description,
        })
        if reexport:
            values.update({
                "借方科目": "8001", "借方科目正式名称": "消耗品費",
                "借方消費税": "0", "貸方科目": "1001",
                "貸方科目正式名称": "現金", "貸方消費税": "0",
                "借方部門コード": "0", "貸方部門コード": "0",
            })
        return [values[name] for name in header]

    @staticmethod
    def _write_official_rows(
        path: Path, rows: list[list[str]], *, preamble: bool = False
    ) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        if preamble:
            writer.writerow(("// synthetic preamble",))
        writer.writerow(header)
        writer.writerows(rows)
        path.write_bytes(output.getvalue().encode("cp932"))

    def _context(self):
        from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
        return JdlTargetContextLoader().load(self.context_path)


if __name__ == "__main__":
    unittest.main()

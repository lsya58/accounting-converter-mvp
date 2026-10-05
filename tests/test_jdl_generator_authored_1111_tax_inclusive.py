from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.domain.format_metadata import EvidenceLevel
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)
from experiments.jdl_import.generator_authored_1111 import OFFICIAL_HEADER
from experiments.jdl_import.generator_authored_1111_tax_inclusive import (
    EXPERIMENT_STATUS,
    JdlGeneratorAuthored1111TaxInclusiveConfig,
    JdlGeneratorAuthored1111TaxInclusiveError,
    ObservedTaxEvidence,
    TargetAccountEvidence,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_1111_TAX_INCLUSIVE,
    EVIDENCE_ID_TAX_INCLUSIVE_HAND_1111,
    RuntimeReexportFieldStatus,
    compare_generator_1111_tax_inclusive_runtime,
    generator_authored_1111_tax_inclusive_real_import_evidence,
    tax_inclusive_hand_entry_1111_observed_evidence,
)


class JdlGeneratorAuthored1111TaxInclusiveTests(unittest.TestCase):
    def test_hand_entry_tax_evidence_remains_observed(self) -> None:
        evidence = tax_inclusive_hand_entry_1111_observed_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_TAX_INCLUSIVE_HAND_1111)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.OBSERVED)
        self.assertIn(
            "generator-authored tax-inclusive import from this observation alone",
            evidence.not_verified,
        )
        self.assertFalse(evidence.production_output_enabled)

    def test_real_import_evidence_is_scoped_and_separate_from_hand_entry(self) -> None:
        evidence = generator_authored_1111_tax_inclusive_real_import_evidence()
        hand_entry = tax_inclusive_hand_entry_1111_observed_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_1111_TAX_INCLUSIVE)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertEqual(hand_entry.evidence_level, EvidenceLevel.OBSERVED)
        self.assertNotEqual(evidence.evidence_id, hand_entry.evidence_id)
        self.assertIn(
            "exact debit tax scope including U+3000 preserved in raw re-export",
            evidence.verified_scope,
        )
        self.assertIn("tax-exclusive accounting", evidence.not_verified)
        self.assertFalse(evidence.production_output_enabled)

    def test_runtime_comparison_preserves_tax_and_does_not_promote_zero(self) -> None:
        config = self.config()
        candidate_row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        reexport_row = list(candidate_row)
        blank_to_nonblank = (
            "伝番",
            "借方科目",
            "借方科目正式名称",
            "借方消費税",
            "貸方科目",
            "貸方科目正式名称",
            "貸方消費税",
            "借方部門コード",
            "貸方部門コード",
        )
        for index, field in enumerate(blank_to_nonblank, start=1):
            reexport_row[OFFICIAL_HEADER.index(field)] = str(index)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = self.write_csv(root / "candidate.csv", candidate_row)
            reexport = self.write_csv(
                root / "reexport.csv",
                reexport_row,
                include_preamble=True,
            )
            comparison = compare_generator_1111_tax_inclusive_runtime(
                candidate,
                reexport,
            )
            serialized = json.dumps(
                comparison.to_privacy_safe_dict(), ensure_ascii=False
            )

        statuses = {
            item.field_name: item.status for item in comparison.candidate_fields
        }
        for field in ("借方課区", "借方税区", "借方税入力方法", "借方取引科目"):
            self.assertIs(statuses[field], RuntimeReexportFieldStatus.INPUT_PRESERVED)
        for field in ("借方消費税", "貸方消費税", "借方部門コード", "貸方部門コード"):
            self.assertIs(
                statuses[field],
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK,
            )
        self.assertEqual(
            sum(
                status is RuntimeReexportFieldStatus.INPUT_PRESERVED
                for status in statuses.values()
            ),
            21,
        )
        self.assertIn("not generator defaults", serialized)
        for private_value in ("仕\u3000入", "10%", "架空税込摘要"):
            self.assertNotIn(private_value, serialized)

    def test_generates_explicit_tax_inclusive_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/tax_inclusive",
            )
            raw = result.csv_path.read_bytes()
            rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertFalse(raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")))
        self.assertEqual(raw.count(b"\r\n"), 2)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), 30)
        row = rows[1]
        self.assertEqual(row[OFFICIAL_HEADER.index("借方課区")], "仕\u3000入")
        self.assertEqual(row[OFFICIAL_HEADER.index("借方税区")], "10%")
        for field in (
            "借方税入力方法",
            "借方消費税",
            "借方取引科目",
            "貸方課区",
            "貸方税区",
            "貸方税入力方法",
            "貸方消費税",
            "貸方取引科目",
            "借方部門コード",
            "借方部門名称",
            "貸方部門コード",
            "貸方部門名称",
        ):
            self.assertEqual(row[OFFICIAL_HEADER.index(field)], "")
        self.assertTrue(report["success"])
        self.assertTrue(report["full_width_space_preserved"])
        self.assertFalse(report["reexport_zero_used_as_generator_default"])
        self.assertEqual(manifest["actual_result"], "UNTESTED")
        self.assertEqual(manifest["status"], EXPERIMENT_STATUS)
        self.assertFalse(manifest["production_ready"])

    def test_full_width_space_is_significant(self) -> None:
        config = self.config()
        config.jdl_columns["借方課区"] = "仕入"

        self.assert_blocked(config, "tax abbreviations must exactly preserve")

    def test_reexport_zero_is_not_a_generation_default(self) -> None:
        for field in ("借方消費税", "貸方消費税", "借方部門コード", "貸方部門コード"):
            with self.subTest(field=field):
                config = self.config()
                config.jdl_columns[field] = "0"
                message = (
                    "department fields must remain blank"
                    if "部門" in field
                    else "tax fields must remain blank"
                )
                self.assert_blocked(config, message)

    def test_unknown_tax_abbreviation_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["借方税区"] = "8%"

        self.assert_blocked(config, "tax abbreviations must exactly preserve")

    def test_missing_company_setting_confirmation_is_blocked(self) -> None:
        config = self.config()
        config.tax_validation["accounting_method_confirmed_tax_included"] = False

        self.assert_blocked(config, "validation incomplete")

    def test_observed_source_tax_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            rows = list(csv.reader(source.read_text(encoding="cp932").splitlines()))
            rows[-1][OFFICIAL_HEADER.index("借方課区")] = "異なる"
            with source.open("w", encoding="cp932", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\r\n")
                writer.writerows(rows)

            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111TaxInclusiveError,
                "observed source does not confirm",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/test",
                )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            output = root / "data/private/experiments/jdl_import/test"
            first = generate_candidate(config, source, output)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111TaxInclusiveError,
                "already exists",
            ):
                generate_candidate(config, source, output)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def test_report_is_privacy_safe_and_exact_registry_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_observed_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/test",
            )
            serialized = (
                result.report_path.read_text(encoding="utf-8")
                + result.manifest_path.read_text(encoding="utf-8")
            )

        for private_value in (
            "架空旅費",
            "架空現金",
            "仕\u3000入",
            "10%",
            "架空税込摘要",
            "20261007",
            "1700",
        ):
            self.assertNotIn(private_value, serialized)
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def assert_blocked(
        self,
        config: JdlGeneratorAuthored1111TaxInclusiveConfig,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_observed_source(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111TaxInclusiveError,
                message,
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/test",
                )

    def config(self) -> JdlGeneratorAuthored1111TaxInclusiveConfig:
        columns = {name: "" for name in OFFICIAL_HEADER}
        columns.update(
            {
                "//識別フラグ": "1111",
                "日付": "20261007",
                "借方科目名称": "架空旅費",
                "借方課区": "仕\u3000入",
                "借方税区": "10%",
                "借方金額": "1700",
                "貸方科目名称": "架空現金",
                "貸方金額": "1700",
                "摘要": "架空税込摘要",
            }
        )
        decisions = {
            name: "EXPLICIT_EXPERIMENT_CONDITION_BLANK" for name in OFFICIAL_HEADER
        }
        decisions.update(
            {
                "//識別フラグ": "EXPLICIT_EXPERIMENT_INPUT",
                "伝番": "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK",
                "日付": "EXPLICIT_EXPERIMENT_INPUT",
                "借方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "借方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
                "借方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "借方課区": "OBSERVED_RUNTIME_EXACT_TAX_VALUE",
                "借方税区": "OBSERVED_RUNTIME_EXACT_TAX_VALUE",
                "借方税入力方法": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
                "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "借方消費税": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
                "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
                "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方課区": "OBSERVED_RUNTIME_CREDIT_SIDE_BLANK",
                "貸方税区": "OBSERVED_RUNTIME_CREDIT_SIDE_BLANK",
                "貸方税入力方法": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
                "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "貸方消費税": "OFFICIAL_DOCUMENTED_TAX_INCLUDED_UNNECESSARY_BLANK",
                "摘要": "EXPLICIT_EXPERIMENT_INPUT",
                "借方取引科目": "OFFICIAL_DOCUMENTED_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
                "貸方取引科目": "OFFICIAL_DOCUMENTED_NON_CONSUMPTION_TAX_JOURNAL_BLANK",
                "借方部門コード": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
                "借方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
                "貸方部門コード": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
                "貸方部門名称": "EXPLICIT_DEPARTMENT_DISABLED_BLANK",
            }
        )
        return JdlGeneratorAuthored1111TaxInclusiveConfig(
            jdl_columns=columns,
            field_decisions=decisions,
            journal_date_iso="2026-10-07",
            target_master_validation={
                "debit_account_name_exists_in_target_master": True,
                "credit_account_name_exists_in_target_master": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            tax_validation={key: True for key in self.tax_validation_keys()},
            target_account_evidence=TargetAccountEvidence(
                debit_code="8001",
                debit_name="架空旅費",
                debit_formal_name="架空旅費正式",
                credit_code="1001",
                credit_name="架空現金",
                credit_formal_name="架空現金正式",
            ),
            observed_tax_evidence=ObservedTaxEvidence(
                debit_tax_scope="仕\u3000入",
                debit_tax_category="10%",
                debit_tax_amount_reexport="0",
                credit_tax_amount_reexport="0",
                department_code_reexport="0",
            ),
            company_tax_processing=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED.value,
        )

    def tax_validation_keys(self) -> tuple[str, ...]:
        return (
            "company_tax_processing_confirmed_taxable",
            "taxation_method_confirmed_standard",
            "input_tax_credit_method_confirmed_individual",
            "accounting_method_confirmed_tax_included",
            "sales_rounding_confirmed_down",
            "purchase_rounding_confirmed_down",
            "separate_consumption_tax_disabled",
            "department_processing_disabled",
            "debit_tax_scope_exact_raw_match",
            "debit_tax_category_exact_raw_match",
            "tax_input_method_intentionally_blank_per_manual",
            "tax_amount_intentionally_blank_per_manual",
            "transaction_accounts_intentionally_blank_for_non_consumption_tax_journal",
            "credit_tax_classification_intentionally_blank_from_observed_case",
            "department_fields_intentionally_blank",
            "no_implicit_zero_or_normalization",
        )

    def write_observed_source(
        self,
        root: Path,
        config: JdlGeneratorAuthored1111TaxInclusiveConfig,
    ) -> Path:
        path = root / "data/private/observed_tax.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = ["" for _ in OFFICIAL_HEADER]
        values = {
            "//識別フラグ": "1111",
            "伝番": "1",
            "日付": "20261006",
            "借方科目": config.target_account_evidence.debit_code,
            "借方科目名称": config.target_account_evidence.debit_name,
            "借方科目正式名称": config.target_account_evidence.debit_formal_name,
            "借方課区": config.observed_tax_evidence.debit_tax_scope,
            "借方税区": config.observed_tax_evidence.debit_tax_category,
            "借方金額": "1700",
            "借方消費税": "0",
            "貸方科目": config.target_account_evidence.credit_code,
            "貸方科目名称": config.target_account_evidence.credit_name,
            "貸方科目正式名称": config.target_account_evidence.credit_formal_name,
            "貸方金額": "1700",
            "貸方消費税": "0",
            "摘要": "観測税込摘要",
            "借方部門コード": "0",
            "貸方部門コード": "0",
        }
        for name, value in values.items():
            row[OFFICIAL_HEADER.index(name)] = value
        with path.open("w", encoding="cp932", newline="") as handle:
            handle.write("// synthetic metadata\r\n")
            handle.write("// synthetic period\r\n")
            handle.write("\r\n")
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path

    def write_csv(
        self,
        path: Path,
        row: list[str],
        *,
        include_preamble: bool = False,
    ) -> Path:
        with path.open("w", encoding="cp932", newline="") as handle:
            if include_preamble:
                handle.write("// synthetic metadata\r\n")
                handle.write("// synthetic period\r\n")
                handle.write("\r\n")
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path


if __name__ == "__main__":
    unittest.main()

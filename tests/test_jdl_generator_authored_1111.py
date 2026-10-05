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
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)
from experiments.jdl_import.generator_authored_1111 import (
    DEFAULT_OUTPUT_NAME,
    DEPARTMENT_FIELDS,
    OFFICIAL_HEADER,
    SUBACCOUNT_FIELDS,
    TAX_FIELDS,
    JdlGeneratorAuthored1111Config,
    JdlGeneratorAuthored1111Error,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    RuntimeReexportFieldStatus,
    compare_generator_1111_runtime,
    generator_authored_1111_real_import_evidence,
)


class JdlGeneratorAuthored1111Tests(unittest.TestCase):
    def test_generates_explicit_cp932_crlf_1111_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_comparison_source(root, self.config())
            result = generate_candidate(
                self.config(),
                source,
                root / "data/private/experiments/jdl_import/generator_authored_1111",
            )

            raw = result.csv_path.read_bytes()
            rows = list(csv.reader(result.csv_path.read_text(encoding="cp932").splitlines()))

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 2)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]), 30)
        self.assertEqual(rows[1][0], "1111")
        self.assertEqual(result.report.explicit_column_count, 30)
        self.assertEqual(result.report.explicit_decision_count, 30)
        self.assertFalse(result.report.source_row_byte_identical)
        self.assertTrue(result.report.target_master_validation_passed)
        self.assertTrue(result.report.exempt_tax_validation_passed)

    def test_every_official_column_and_decision_must_be_explicit(self) -> None:
        config = self.config()
        del config.jdl_columns["貸方部門名称"]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_comparison_source(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111Error,
                "explicitly cover all official columns",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_source_identical_data_row_is_blocked_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_comparison_source(root, config, identical=True)
            output_dir = root / "data/private/experiments/test"

            with self.assertRaisesRegex(
                JdlGeneratorAuthored1111Error,
                "must not be byte-identical",
            ):
                generate_candidate(config, source, output_dir)

            self.assertFalse((output_dir / DEFAULT_OUTPUT_NAME).exists())

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_comparison_source(root, config)
            output_dir = root / "data/private/experiments/test"
            first = generate_candidate(config, source, output_dir)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(JdlGeneratorAuthored1111Error, "already exists"):
                generate_candidate(config, source, output_dir)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def test_subaccount_department_and_tax_values_are_blocked(self) -> None:
        cases = (
            (SUBACCOUNT_FIELDS[0], "0001", "subaccount"),
            (DEPARTMENT_FIELDS[0], "0001", "department"),
            (TAX_FIELDS[0], "課税", "exempt tax"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                config = self.config()
                config.jdl_columns[field] = value
                with self.assertRaisesRegex(JdlGeneratorAuthored1111Error, message):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        root = Path(tmpdir)
                        source = self.write_comparison_source(root, self.config())
                        generate_candidate(
                            config,
                            source,
                            root / "data/private/experiments/test",
                        )

    def test_unconfirmed_target_master_is_blocked(self) -> None:
        config = self.config()
        config.target_master_validation[
            "credit_account_name_exists_in_target_master"
        ] = False

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_comparison_source(root, self.config())
            with self.assertRaisesRegex(JdlGeneratorAuthored1111Error, "target master"):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_report_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_comparison_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/test",
            )
            serialized = result.report_path.read_text(encoding="utf-8")
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        for private_value in (
            "現金",
            "普通預金",
            "生成テスト摘要",
            "20261002",
            "comparison_source",
        ):
            self.assertNotIn(private_value, serialized)
        self.assertFalse(manifest["verification"]["source_jdl_row_used_for_construction"])
        self.assertEqual(manifest["actual_result"], "UNTESTED")

    def test_runtime_evidence_is_scoped_and_normalization_is_not_a_default(self) -> None:
        evidence = generator_authored_1111_real_import_evidence()
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn("identifier flag 1000", evidence.not_verified)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_comparison_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/test",
            )
            candidate_rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )
            runtime_row = list(candidate_rows[1])
            normalized_fields = (
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
            for index, field in enumerate(normalized_fields, start=1):
                self.assertEqual(candidate_rows[1][OFFICIAL_HEADER.index(field)], "")
                runtime_row[OFFICIAL_HEADER.index(field)] = str(index)
            reference_row = list(runtime_row)
            reference_row[OFFICIAL_HEADER.index("伝番")] = "999"
            reexport = self.write_export(root / "data/private/reexport.csv", runtime_row)
            reference = self.write_export(root / "data/private/reference.csv", reference_row)

            comparison = compare_generator_1111_runtime(
                result.csv_path,
                reexport,
                reference,
            )
            payload = json.dumps(
                comparison.to_privacy_safe_dict(), ensure_ascii=False
            )

        statuses = {
            item.field_name: item.status for item in comparison.candidate_fields
        }
        self.assertEqual(
            sum(
                status is RuntimeReexportFieldStatus.INPUT_PRESERVED
                for status in statuses.values()
            ),
            21,
        )
        for field in normalized_fields:
            self.assertIs(
                statuses[field],
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK,
            )
        self.assertEqual(comparison.reference_preserved_count, 29)
        self.assertEqual(comparison.reference_difference_fields, ("伝番",))
        for private_value in ("現金", "普通預金", "生成テスト摘要", "20261002"):
            self.assertNotIn(private_value, payload)

    def test_final_registry_is_available_without_promoting_experiment_scope(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def write_export(self, path: Path, row: list[str]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="cp932", newline="") as handle:
            handle.write("// synthetic metadata\r\n")
            handle.write("// synthetic period\r\n")
            handle.write("\r\n")
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path

    def config(self) -> JdlGeneratorAuthored1111Config:
        columns = {name: "" for name in OFFICIAL_HEADER}
        columns.update(
            {
                "//識別フラグ": "1111",
                "日付": "20261002",
                "借方科目名称": "現金",
                "借方金額": "1000",
                "貸方科目名称": "普通預金",
                "貸方金額": "1000",
                "摘要": "生成テスト摘要",
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
                "借方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "貸方科目": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方科目名称": "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME",
                "貸方科目正式名称": "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK",
                "貸方金額": "EXPLICIT_EXPERIMENT_INPUT",
                "摘要": "EXPLICIT_EXPERIMENT_INPUT",
            }
        )
        for name in TAX_FIELDS:
            decisions[name] = "OFFICIAL_DOCUMENTED_EXEMPT_BLANK"
        return JdlGeneratorAuthored1111Config(
            jdl_columns=columns,
            field_decisions=decisions,
            journal_date_iso="2026-10-02",
            target_master_validation={
                "debit_account_name_exists_in_target_master": True,
                "credit_account_name_exists_in_target_master": True,
                "account_identifiers_visually_confirmed_after_roundtrip": True,
                "debit_subaccount_intentionally_blank": True,
                "credit_subaccount_intentionally_blank": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            tax_validation={
                "company_tax_processing_confirmed_exempt": True,
                "tax_fields_intentionally_blank": True,
            },
        )

    def write_comparison_source(
        self,
        root: Path,
        config: JdlGeneratorAuthored1111Config,
        identical: bool = False,
    ) -> Path:
        path = root / "data/private/synthetic_jdl_source.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        if not identical:
            row[OFFICIAL_HEADER.index("借方科目")] = "1001"
        with path.open("w", encoding="cp932", newline="") as handle:
            handle.write("// synthetic metadata\r\n")
            handle.write("// synthetic period\r\n")
            handle.write("\r\n")
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path


if __name__ == "__main__":
    unittest.main()

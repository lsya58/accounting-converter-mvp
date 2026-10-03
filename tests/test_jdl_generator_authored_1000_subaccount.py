from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.domain.format_metadata import EvidenceLevel
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from experiments.jdl_import.exp01_candidate import (
    OFFICIAL_HEADER,
    JdlExp01CandidateError,
)
from experiments.jdl_import.generator_authored_1000_subaccount import (
    EXPERIMENT_STATUS,
    JdlGeneratorAuthored1000SubaccountConfig,
    JdlGeneratorAuthored1000SubaccountError,
    TargetSubaccountEvidence,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_1000_SUBACCOUNT,
    RuntimeReexportFieldStatus,
    compare_generator_1000_subaccount_runtime,
    generator_authored_1000_subaccount_real_import_evidence,
)


class JdlGeneratorAuthored1000SubaccountTests(unittest.TestCase):
    def test_real_import_evidence_is_scoped_without_leading_zero_rule(self) -> None:
        evidence = generator_authored_1000_subaccount_real_import_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_1000_SUBACCOUNT)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertIn(
            "candidate numeric subaccount representation 0001",
            evidence.verified_scope,
        )
        self.assertIn(
            "target master actual subaccount code 1",
            evidence.verified_scope,
        )
        self.assertIn(
            "general leading-zero equivalence for numeric subaccount identifiers",
            evidence.not_verified,
        )
        self.assertIn(
            "raw post-import re-export subaccount representation 1",
            evidence.verified_scope,
        )
        self.assertFalse(evidence.production_output_enabled)

    def test_candidate_to_reexport_code_difference_is_raw_scoped(self) -> None:
        config = self.config()
        candidate_row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        reexport_row = list(candidate_row)
        reexport_row[OFFICIAL_HEADER.index("貸方補助")] = "7"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = self.write_rows(root / "candidate.csv", candidate_row)
            reexport = self.write_rows(
                root / "reexport.csv",
                reexport_row,
                include_preamble=True,
            )
            comparison = compare_generator_1000_subaccount_runtime(
                candidate,
                reexport,
            )
            serialized = json.dumps(
                comparison.to_privacy_safe_dict(),
                ensure_ascii=False,
            )

        statuses = {
            item.field_name: item.status for item in comparison.candidate_fields
        }
        self.assertIs(
            statuses["貸方補助"],
            RuntimeReexportFieldStatus.DIFFERENT,
        )
        self.assertEqual(comparison.reexport_structure["preamble_row_count"], 3)
        self.assertEqual(comparison.reexport_structure["data_column_count"], 30)
        self.assertNotIn("0007", serialized)
        self.assertNotIn("架空補助", serialized)

    def test_generates_credit_subaccount_candidate_with_parent_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/subaccount",
            )
            raw = result.csv_path.read_bytes()
            rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 2)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual(len(rows[1]), 30)
        self.assertEqual(rows[1][OFFICIAL_HEADER.index("借方補助")], "")
        self.assertEqual(rows[1][OFFICIAL_HEADER.index("借方補助名称")], "")
        self.assertEqual(
            rows[1][OFFICIAL_HEADER.index("貸方補助")],
            config.target_subaccount_evidence.subaccount_code,
        )
        self.assertEqual(
            rows[1][OFFICIAL_HEADER.index("貸方補助名称")],
            config.target_subaccount_evidence.subaccount_name,
        )
        self.assertEqual(report["status"], EXPERIMENT_STATUS)
        self.assertTrue(report["parent_context_validation"]["parent_account_confirmed"])
        self.assertEqual(manifest["actual_result"], "UNTESTED")
        self.assertEqual(
            manifest["changed_from_successful_1000_fields"],
            ["貸方補助", "貸方補助名称"],
        )
        self.assertEqual(manifest["validation"]["status"], EXPERIMENT_STATUS)
        self.assertEqual(manifest["validation"]["implicit_default_count"], 0)
        self.assertFalse(manifest["source_jdl_row_used_for_construction"])
        self.assertFalse(manifest["production_ready"])

    def test_wrong_parent_account_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["貸方科目名称"] = "different parent"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_base_candidate(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1000SubaccountError,
                "does not match target subaccount parent",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_unconfirmed_parent_context_is_blocked(self) -> None:
        config = self.config()
        evidence = replace(
            config.target_subaccount_evidence,
            confirmed_under_parent=False,
        )
        config = replace(config, target_subaccount_evidence=evidence)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_base_candidate(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1000SubaccountError,
                "parent context must be explicitly confirmed",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_candidate_and_target_subaccount_codes_are_not_normalized(self) -> None:
        config = self.config()
        evidence = replace(config.target_subaccount_evidence, subaccount_code="7")
        config = replace(config, target_subaccount_evidence=evidence)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_base_candidate(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1000SubaccountError,
                "do not match target master evidence",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_any_change_beyond_credit_subaccount_is_blocked(self) -> None:
        config = self.config()
        config.jdl_columns["摘要"] = "changed description"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_base_candidate(root, self.config())
            with self.assertRaisesRegex(
                JdlGeneratorAuthored1000SubaccountError,
                "only credit subaccount",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/test",
                )

    def test_report_and_manifest_do_not_leak_accounting_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/test",
            )
            serialized = (
                result.report_path.read_text(encoding="utf-8")
                + result.manifest_path.read_text(encoding="utf-8")
            )

        for value in (
            "架空預金",
            "架空補助",
            "架空現金",
            "架空摘要",
            "20261003",
            "1300",
        ):
            self.assertNotIn(value, serialized)

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_base_candidate(root, config)
            output = root / "data/private/experiments/test"
            first = generate_candidate(config, source, output)
            before = first.csv_path.read_bytes()

            with self.assertRaisesRegex(JdlExp01CandidateError, "already exists"):
                generate_candidate(config, source, output)

            self.assertEqual(first.csv_path.read_bytes(), before)

    def config(self) -> JdlGeneratorAuthored1000SubaccountConfig:
        columns = {name: "" for name in OFFICIAL_HEADER}
        columns.update(
            {
                "//識別フラグ": "1000",
                "日付": "20261003",
                "借方科目名称": "架空現金",
                "借方金額": "1300",
                "貸方科目名称": "架空預金",
                "貸方補助": "0007",
                "貸方補助名称": "架空補助",
                "貸方金額": "1300",
                "摘要": "架空摘要",
            }
        )
        return JdlGeneratorAuthored1000SubaccountConfig(
            jdl_columns=columns,
            journal_date_iso="2026-10-03",
            target_master_validation={
                "debit_account_exists_in_target_master": True,
                "credit_account_exists_in_target_master": True,
                "debit_subaccount_blank_or_exists_under_parent": True,
                "credit_subaccount_blank_or_exists_under_parent": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            tax_validation={
                "company_tax_processing_confirmed": True,
                "tax_category_abbreviations_confirmed_when_used": False,
                "tax_scope_tax_category_combination_confirmed_when_used": False,
                "transaction_account_confirmed_when_used": False,
            },
            target_subaccount_evidence=TargetSubaccountEvidence(
                parent_account_code="1999",
                parent_account_name="架空預金",
                subaccount_code="0007",
                subaccount_name="架空補助",
                confirmed_under_parent=True,
                no_fuzzy_matching=True,
                no_automatic_replacement=True,
            ),
            company_tax_processing=JdlTaxProcessingMode.EXEMPT.value,
        )

    def write_base_candidate(
        self,
        root: Path,
        config: JdlGeneratorAuthored1000SubaccountConfig,
    ) -> Path:
        path = root / "data/private/base_candidate.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = [config.jdl_columns[name] for name in OFFICIAL_HEADER]
        row[OFFICIAL_HEADER.index("貸方補助")] = ""
        row[OFFICIAL_HEADER.index("貸方補助名称")] = ""
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(OFFICIAL_HEADER)
            writer.writerow(row)
        return path

    def write_rows(
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

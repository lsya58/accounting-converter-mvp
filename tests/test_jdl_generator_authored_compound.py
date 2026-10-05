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
    DEPARTMENT_FIELDS,
    OFFICIAL_HEADER,
    SUBACCOUNT_FIELDS,
    TAX_FIELDS,
)
from experiments.jdl_import.generator_authored_compound import (
    DEFAULT_OUTPUT_NAME,
    EXPERIMENT_STATUS,
    JdlGeneratorAuthoredCompoundConfig,
    JdlGeneratorAuthoredCompoundError,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_COMPOUND_HAND_1110_1100_1101,
    EVIDENCE_ID_GENERATOR_COMPOUND_1110_1100_1101,
    RuntimeReexportFieldStatus,
    compare_generator_compound_runtime,
    compound_hand_entry_1110_1100_1101_observed_evidence,
    generator_authored_compound_real_import_evidence,
)


class JdlGeneratorAuthoredCompoundTests(unittest.TestCase):
    def test_hand_entry_evidence_remains_observed(self) -> None:
        evidence = compound_hand_entry_1110_1100_1101_observed_evidence()

        self.assertEqual(
            evidence.evidence_id,
            EVIDENCE_ID_COMPOUND_HAND_1110_1100_1101,
        )
        self.assertEqual(evidence.evidence_level, EvidenceLevel.OBSERVED)
        self.assertIn("exact 1110/1100/1101 sequence", evidence.verified_scope)
        self.assertIn("generator-authored compound import", evidence.not_verified)
        self.assertFalse(evidence.production_output_enabled)

    def test_generator_import_evidence_is_verified_but_strictly_scoped(self) -> None:
        evidence = generator_authored_compound_real_import_evidence()
        hand = compound_hand_entry_1110_1100_1101_observed_evidence()

        self.assertEqual(
            evidence.evidence_id,
            EVIDENCE_ID_GENERATOR_COMPOUND_1110_1100_1101,
        )
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertEqual(hand.evidence_level, EvidenceLevel.OBSERVED)
        self.assertIn(
            "runtime recognized three records and grouped them into one voucher",
            evidence.verified_scope,
        )
        self.assertIn("multiple compound vouchers in one file", evidence.not_verified)
        self.assertIn(
            "blank-voucher behavior outside this exact single-group artifact",
            evidence.not_verified,
        )
        self.assertFalse(evidence.production_output_enabled)

    def test_runtime_comparison_preserves_rows_and_does_not_promote_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/compound",
            )
            reexport = self.write_reexport(root, config)
            comparison = compare_generator_compound_runtime(result.csv_path, reexport)
            serialized = json.dumps(
                comparison.to_privacy_safe_dict(), ensure_ascii=False
            )

        self.assertEqual(
            dict(comparison.status_counts),
            {
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK.value: 23,
                RuntimeReexportFieldStatus.INPUT_PRESERVED.value: 67,
            },
        )
        self.assertTrue(comparison.sequence_preserved)
        self.assertTrue(comparison.row_order_preserved)
        self.assertTrue(comparison.date_preserved)
        self.assertTrue(comparison.amounts_and_positions_preserved)
        self.assertTrue(comparison.descriptions_and_positions_preserved)
        self.assertTrue(comparison.candidate_vouchers_blank)
        self.assertTrue(comparison.reexport_vouchers_zero)
        self.assertIn("not a generator default", serialized)
        for private_value in ("借方甲", "貸方甲", "架空複合摘要", "20990102"):
            self.assertNotIn(private_value, serialized)

    def test_runtime_comparison_blocks_reordered_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/compound",
            )
            reexport = self.write_reexport(root, config, flags=("1110", "1101", "1100"))
            with self.assertRaisesRegex(ValueError, "preserve 1110/1100/1101"):
                compare_generator_compound_runtime(result.csv_path, reexport)

    def test_generates_explicit_three_record_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/compound",
            )
            raw = result.csv_path.read_bytes()
            rows = list(csv.reader(result.csv_path.read_text(encoding="cp932").splitlines()))

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 4)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual([row[0] for row in rows[1:]], ["1110", "1100", "1101"])
        self.assertTrue(all(len(row) == 30 for row in rows[1:]))
        self.assertEqual([row[1] for row in rows[1:]], ["", "", ""])
        self.assertEqual([row[11] for row in rows[2:]], ["0", "0"])
        self.assertTrue(result.report["balanced"])
        self.assertEqual(result.report["voucher_grouping_status"], "RUNTIME_VERIFICATION_PENDING")
        self.assertEqual(result.report["source_row_copy_count"], 0)

    def test_sequence_must_be_exact(self) -> None:
        config = self.config()
        config.rows[1]["//識別フラグ"] = "1101"
        self.assert_generation_blocked(config, "flag sequence")

    def test_missing_final_record_is_blocked(self) -> None:
        config = self.config()
        config = JdlGeneratorAuthoredCompoundConfig(
            rows=config.rows[:2],
            field_decisions=config.field_decisions[:2],
            journal_date_iso=config.journal_date_iso,
            target_master_validation=config.target_master_validation,
            experiment_validation=config.experiment_validation,
            source_observation=config.source_observation,
        )
        self.assert_generation_blocked(config, "exactly three")

    def test_date_mismatch_is_blocked(self) -> None:
        config = self.config()
        config.rows[1]["日付"] = "20990103"
        self.assert_generation_blocked(config, "JDL date must match")

    def test_unbalanced_group_is_blocked(self) -> None:
        config = self.config()
        config.rows[2]["貸方金額"] = "19"
        self.assert_generation_blocked(config, "must balance")

    def test_voucher_guess_is_blocked(self) -> None:
        config = self.config()
        for row in config.rows:
            row["伝番"] = "7"
        self.assert_generation_blocked(config, "voucher must be explicitly blank")

    def test_voucher_mismatch_is_blocked(self) -> None:
        config = self.config()
        config.rows[1]["伝番"] = "7"
        self.assert_generation_blocked(config, "voucher must be explicitly blank")

    def test_missing_side_zero_requires_explicit_evidence(self) -> None:
        config = self.config()
        config.field_decisions[1]["借方金額"] = "EXPLICIT_EXPERIMENT_INPUT"
        self.assert_generation_blocked(config, "missing-side zero")

    def test_optional_reexport_zero_is_not_promoted(self) -> None:
        config = self.config()
        for row in config.rows:
            for field in TAX_FIELDS + DEPARTMENT_FIELDS:
                self.assertEqual(row[field], "")
        config.rows[0]["借方部門コード"] = "0"
        self.assert_generation_blocked(config, "department fields must be blank")

    def test_source_shape_difference_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            config.source_observation["voucher_numbers"] = ["8", "8", "8"]
            with self.assertRaisesRegex(
                JdlGeneratorAuthoredCompoundError,
                "differs from explicit evidence",
            ):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/compound",
                )

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            output_dir = root / "data/private/experiments/jdl_import/compound"
            result = generate_candidate(config, source, output_dir)
            before = result.csv_path.read_bytes()
            with self.assertRaisesRegex(JdlGeneratorAuthoredCompoundError, "already exists"):
                generate_candidate(config, source, output_dir)
            self.assertEqual(result.csv_path.read_bytes(), before)

    def test_report_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self.config()
            source = self.write_source(root, config)
            result = generate_candidate(
                config,
                source,
                root / "data/private/experiments/jdl_import/compound",
            )
            serialized = json.dumps(result.report, ensure_ascii=False)
        for private_value in ("借方甲", "貸方甲", "貸方乙", "架空複合摘要", "20990102"):
            self.assertNotIn(private_value, serialized)

    def test_production_jdl_output_is_available_for_exact_identity(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def assert_generation_blocked(
        self,
        config: JdlGeneratorAuthoredCompoundConfig,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.write_source(root, self.config())
            with self.assertRaisesRegex(JdlGeneratorAuthoredCompoundError, message):
                generate_candidate(
                    config,
                    source,
                    root / "data/private/experiments/jdl_import/compound",
                )

    @staticmethod
    def config() -> JdlGeneratorAuthoredCompoundConfig:
        flags = ("1110", "1100", "1101")
        credit_names = ("貸方甲", "貸方乙", "貸方丙")
        credits = ("50", "30", "20")
        rows: list[dict[str, str]] = []
        decisions: list[dict[str, str]] = []
        for index, flag in enumerate(flags):
            row = {name: "" for name in OFFICIAL_HEADER}
            row.update(
                {
                    "//識別フラグ": flag,
                    "日付": "20990102",
                    "借方科目名称": "借方甲" if index == 0 else "",
                    "借方金額": "100" if index == 0 else "0",
                    "貸方科目名称": credit_names[index],
                    "貸方金額": credits[index],
                    "摘要": "架空複合摘要" if index == 0 else "",
                }
            )
            decision = {name: "EXPLICIT_EXPERIMENT_INPUT" for name in OFFICIAL_HEADER}
            decision["伝番"] = "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK"
            for field in (
                "借方科目",
                "借方科目正式名称",
                "貸方科目",
                "貸方科目正式名称",
            ):
                decision[field] = "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK"
            decision["借方科目名称"] = (
                "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME"
                if index == 0
                else "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK"
            )
            decision["貸方科目名称"] = "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME"
            for field in SUBACCOUNT_FIELDS + DEPARTMENT_FIELDS:
                decision[field] = "EXPLICIT_EXPERIMENT_CONDITION_BLANK"
            for field in TAX_FIELDS:
                decision[field] = "OFFICIAL_DOCUMENTED_EXEMPT_BLANK"
            if index > 0:
                decision["借方金額"] = "OFFICIAL_REQUIRED_AMOUNT_AND_OBSERVED_MISSING_SIDE_ZERO"
                decision["摘要"] = "EXPLICIT_EXPERIMENT_CONDITION_BLANK"
            rows.append(row)
            decisions.append(decision)
        return JdlGeneratorAuthoredCompoundConfig(
            rows=tuple(rows),
            field_decisions=tuple(decisions),
            journal_date_iso="2099-01-02",
            target_master_validation={
                "all_account_names_exist_in_target_master": True,
                "account_identifiers_exactly_confirmed": True,
                "no_fuzzy_matching_or_auto_replacement": True,
            },
            experiment_validation={
                "company_tax_processing_confirmed_exempt": True,
                "subaccounts_intentionally_absent": True,
                "department_processing_confirmed_disabled": True,
                "tax_fields_intentionally_blank": True,
                "transaction_accounts_intentionally_blank": True,
                "voucher_field_intentionally_blank_from_official_optional_rule": True,
                "missing_side_zero_amount_grounded_by_manual_and_observed_export": True,
                "reexport_zero_not_promoted_to_optional_fields": True,
                "source_jdl_rows_not_used_for_construction": True,
            },
            source_observation={
                "flags": list(flags),
                "voucher_numbers": ["9", "9", "9"],
                "dates": ["20990101", "20990101", "20990101"],
                "debit_amounts": ["100", "0", "0"],
                "credit_amounts": ["50", "30", "20"],
                "debit_account_names": ["観測借方", "", ""],
                "credit_account_names": ["観測貸方A", "観測貸方B", "観測貸方C"],
                "description_presence": [True, False, False],
            },
            status=EXPERIMENT_STATUS,
        )

    @staticmethod
    def write_source(
        root: Path,
        config: JdlGeneratorAuthoredCompoundConfig,
    ) -> Path:
        path = root / "data/private/source.csv"
        path.parent.mkdir(parents=True)
        observed = config.source_observation
        rows = []
        for index in range(3):
            row = [""] * 30
            row[0] = observed["flags"][index]
            row[1] = observed["voucher_numbers"][index]
            row[2] = observed["dates"][index]
            row[4] = observed["debit_account_names"][index]
            row[11] = observed["debit_amounts"][index]
            row[14] = observed["credit_account_names"][index]
            row[21] = observed["credit_amounts"][index]
            row[23] = "観測摘要" if observed["description_presence"][index] else ""
            rows.append(row)
        with path.open("w", encoding="cp932", newline="") as handle:
            handle.write("// synthetic company\r\n// synthetic period\r\n\r\n")
            csv.writer(handle, lineterminator="\r\n").writerows((OFFICIAL_HEADER, *rows))
        return path

    @staticmethod
    def write_reexport(
        root: Path,
        config: JdlGeneratorAuthoredCompoundConfig,
        *,
        flags: tuple[str, str, str] = ("1110", "1100", "1101"),
    ) -> Path:
        path = root / "data/private/reexport.csv"
        rows = [[row[name] for name in OFFICIAL_HEADER] for row in config.rows]
        code_fields = (
            ("借方科目", "借方科目正式名称", "貸方科目", "貸方科目正式名称"),
            ("貸方科目", "貸方科目正式名称"),
            ("貸方科目", "貸方科目正式名称"),
        )
        for index, row in enumerate(rows):
            row[0] = flags[index]
            row[1] = "0"
            for field in code_fields[index]:
                row[OFFICIAL_HEADER.index(field)] = str(index + 1)
            for field in (
                "借方消費税",
                "貸方消費税",
                "借方部門コード",
                "貸方部門コード",
            ):
                row[OFFICIAL_HEADER.index(field)] = "0"
        with path.open("w", encoding="cp932", newline="") as handle:
            handle.write("// synthetic company\r\n// synthetic period\r\n\r\n")
            csv.writer(handle, lineterminator="\r\n").writerows((OFFICIAL_HEADER, *rows))
        return path


if __name__ == "__main__":
    unittest.main()

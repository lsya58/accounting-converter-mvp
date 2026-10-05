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
    JdlGeneratorAuthored1111Config,
)
from experiments.jdl_import.generator_authored_compound import (
    JdlGeneratorAuthoredCompoundConfig,
)
from experiments.jdl_import.generator_authored_multi_group import (
    DEFAULT_OUTPUT_NAME,
    EXPERIMENT_STATUS,
    JdlGeneratorAuthoredMultiGroupConfig,
    JdlGeneratorAuthoredMultiGroupError,
    generate_candidate,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_CONTEXT_AWARE_RUNTIME_E2E,
    EVIDENCE_ID_CONVERSION_SERVICE_E2E,
    EVIDENCE_ID_GENERATOR_MULTIGROUP_SIMPLE_COMPOUND,
    EVIDENCE_ID_MIXED_BATCH_RUNTIME,
    EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME,
    EVIDENCE_ID_WINDOWS_GUI_E2E,
    RuntimeReexportFieldStatus,
    compare_context_aware_runtime_e2e,
    compare_generator_multi_group_runtime,
    compare_simple_plus_simple_runtime,
    conversion_service_e2e_real_import_evidence,
    generator_authored_multi_group_real_import_evidence,
    mixed_batch_runtime_real_import_evidence,
    simple_plus_simple_runtime_real_import_evidence,
    windows_gui_e2e_real_import_evidence,
)


class JdlGeneratorAuthoredMultiGroupTests(unittest.TestCase):
    def test_generates_exact_four_record_boundary_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = generate_candidate(
                self.config(),
                root / "data/private/experiments/jdl_import/multi_group",
            )
            raw = result.csv_path.read_bytes()
            rows = list(
                csv.reader(result.csv_path.read_text(encoding="cp932").splitlines())
            )

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\r\n"), 5)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(tuple(rows[0]), OFFICIAL_HEADER)
        self.assertEqual([row[0] for row in rows[1:]], ["1111", "1110", "1100", "1101"])
        self.assertTrue(all(len(row) == 30 for row in rows[1:]))
        self.assertEqual({row[2] for row in rows[1:]}, {"20990103"})
        self.assertTrue(all(not row[1] for row in rows[1:]))
        self.assertEqual(result.report["expected_group_count"], 2)
        self.assertEqual(result.report["structural_group_candidate_count"], 2)
        self.assertEqual(
            result.report["structural_group_candidate_statuses"],
            ["OBSERVED_SINGLE_RECORD", "UNRESOLVED"],
        )
        self.assertEqual(
            result.report["multi_group_boundary_status"],
            "RUNTIME_VERIFICATION_PENDING",
        )
        self.assertFalse(result.report["blank_voucher_multi_group_safety_proven"])

    def test_simple_and_compound_balances_are_independent(self) -> None:
        config = self.config()
        config.simple.jdl_columns["貸方金額"] = "69"
        self.assert_blocked(config, "debit and credit amounts must balance")

        config = self.config()
        config.compound.rows[2]["貸方金額"] = "19"
        self.assert_blocked(config, "group debit and credit totals must balance")

    def test_exact_flag_order_is_required(self) -> None:
        config = self.config()
        config.compound.rows[0]["//識別フラグ"] = "1100"
        self.assert_blocked(config, "flag sequence")

    def test_all_voucher_fields_must_remain_blank(self) -> None:
        config = self.config()
        config.simple.jdl_columns["伝番"] = "1"
        self.assert_blocked(config, "voucher fields must remain explicitly blank")

        config = self.config()
        config.compound.rows[1]["伝番"] = "1"
        self.assert_blocked(config, "voucher must be explicitly blank")

    def test_malformed_compound_end_is_blocked(self) -> None:
        config = self.config()
        config.compound.rows[2]["//識別フラグ"] = "1100"
        self.assert_blocked(config, "flag sequence")

    def test_tax_department_and_subaccount_remain_blank(self) -> None:
        config = self.config()
        rows = (config.simple.jdl_columns, *config.compound.rows)
        for row in rows:
            for field in SUBACCOUNT_FIELDS + TAX_FIELDS + DEPARTMENT_FIELDS:
                self.assertEqual(row[field], "")

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "data/private/experiments/jdl_import/multi_group"
            first = generate_candidate(self.config(), output_dir)
            before = first.csv_path.read_bytes()
            with self.assertRaisesRegex(
                JdlGeneratorAuthoredMultiGroupError, "already exists"
            ):
                generate_candidate(self.config(), output_dir)
            self.assertEqual(first.csv_path.read_bytes(), before)

    def test_report_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = generate_candidate(
                self.config(),
                root / "data/private/experiments/jdl_import/multi_group",
            )
            serialized = json.dumps(result.report, ensure_ascii=False)
        for private_value in (
            "借方甲",
            "貸方甲",
            "単純摘要",
            "複合摘要",
            "20990103",
        ):
            self.assertNotIn(private_value, serialized)

    def test_production_registry_is_available_only_for_official_exact_identity(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()
        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def test_runtime_evidence_is_verified_but_strictly_scoped(self) -> None:
        evidence = generator_authored_multi_group_real_import_evidence()
        self.assertEqual(
            evidence.evidence_id,
            EVIDENCE_ID_GENERATOR_MULTIGROUP_SIMPLE_COMPOUND,
        )
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn(
            "one CSV containing 1111 then 1110/1100/1101",
            evidence.verified_scope,
        )
        self.assertIn(
            "simple plus simple or compound plus compound boundaries",
            evidence.not_verified,
        )
        self.assertIn("production JDLOutputAdapter", evidence.not_verified)

    def test_conversion_service_release_gate_evidence_is_scoped(self) -> None:
        evidence = conversion_service_e2e_real_import_evidence()
        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_CONVERSION_SERVICE_E2E)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn(
            "formal ConversionService path with confirmed ConversionProfile mappings",
            evidence.verified_scope,
        )
        self.assertIn(
            "YayoiInputAdapter through JDLOutputAdapter formal end-to-end",
            evidence.not_verified,
        )
        self.assertIn(
            "registry factory wiring for explicit target master and tax context",
            evidence.not_verified,
        )

    def test_runtime_comparison_keeps_three_voucher_evidence_layers_separate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = generate_candidate(
                self.config(),
                root / "data/private/experiments/jdl_import/multi_group",
            )
            reexport = root / "runtime_reexport.csv"
            self._write_synthetic_reexport(generated.csv_path, reexport)
            comparison = compare_generator_multi_group_runtime(
                generated.csv_path,
                reexport,
                runtime_ui_vouchers_blank=True,
                runtime_logical_voucher_count=2,
            )

        self.assertTrue(comparison.candidate_vouchers_blank)
        self.assertTrue(comparison.runtime_ui_vouchers_blank)
        self.assertTrue(comparison.reexport_vouchers_zero)
        self.assertEqual(comparison.runtime_logical_voucher_count, 2)
        self.assertTrue(comparison.simple_balanced)
        self.assertTrue(comparison.compound_balanced)
        self.assertTrue(comparison.flag_order_preserved)
        self.assertTrue(comparison.row_order_preserved)
        self.assertTrue(comparison.date_preserved)
        self.assertTrue(comparison.account_placement_preserved)
        self.assertTrue(comparison.amounts_and_positions_preserved)
        self.assertTrue(comparison.descriptions_and_positions_preserved)
        self.assertEqual(
            dict(comparison.status_counts),
            {
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK.value: 32,
                RuntimeReexportFieldStatus.INPUT_PRESERVED.value: 88,
            },
        )

    def test_runtime_report_is_privacy_safe_and_zero_is_not_a_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = generate_candidate(
                self.config(),
                root / "data/private/experiments/jdl_import/multi_group",
            )
            reexport = root / "runtime_reexport.csv"
            self._write_synthetic_reexport(generated.csv_path, reexport)
            payload = compare_generator_multi_group_runtime(
                generated.csv_path,
                reexport,
                runtime_ui_vouchers_blank=True,
                runtime_logical_voucher_count=2,
            ).to_privacy_safe_dict()

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertIn("not a generator default", payload["interpretation"])
        self.assertEqual(
            payload["voucher_evidence"],
            {
                "candidate_raw_fields_blank": True,
                "runtime_ui_fields_blank_operator_observed": True,
                "reexport_raw_fields_zero": True,
            },
        )
        for private_value in ("借方甲", "貸方甲", "単純摘要", "複合摘要", "20990103"):
            self.assertNotIn(private_value, serialized)

    def test_context_aware_comparison_uses_distinct_evidence_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = generate_candidate(
                self.config(),
                root / "data/private/experiments/jdl_import/multi_group",
            )
            reexport = root / "runtime_reexport.csv"
            self._write_synthetic_reexport(generated.csv_path, reexport)
            comparison = compare_context_aware_runtime_e2e(
                generated.csv_path,
                reexport,
            )

        self.assertEqual(
            comparison.evidence_id,
            EVIDENCE_ID_CONTEXT_AWARE_RUNTIME_E2E,
        )
        self.assertTrue(comparison.candidate_vouchers_blank)
        self.assertTrue(comparison.runtime_ui_vouchers_blank)
        self.assertTrue(comparison.reexport_vouchers_zero)
        self.assertEqual(
            dict(comparison.status_counts),
            {
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK.value: 32,
                RuntimeReexportFieldStatus.INPUT_PRESERVED.value: 88,
            },
        )

    def test_simple_pair_runtime_evidence_is_verified_but_strictly_scoped(
        self,
    ) -> None:
        evidence = simple_plus_simple_runtime_real_import_evidence()
        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn("exactly two same-date simple journals", evidence.verified_scope)
        self.assertIn(
            "three or more simple journals or arbitrary batch sizes",
            evidence.not_verified,
        )

    def test_mixed_batch_runtime_evidence_is_verified_but_strictly_scoped(
        self,
    ) -> None:
        evidence = mixed_batch_runtime_real_import_evidence()
        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_MIXED_BATCH_RUNTIME)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertFalse(evidence.production_output_enabled)
        self.assertIn(
            "exactly twelve same-date logical journals and twenty-two physical records",
            evidence.verified_scope,
        )
        self.assertIn(
            "arbitrary journal counts, profile orders, dates, or batch sizes",
            evidence.not_verified,
        )

    def test_windows_gui_e2e_evidence_enables_strict_production_output(
        self,
    ) -> None:
        evidence = windows_gui_e2e_real_import_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_WINDOWS_GUI_E2E)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertTrue(evidence.production_output_enabled)
        self.assertIn("Windows packaged application and Tkinter GUI", evidence.verified_scope)
        self.assertIn("format-wide production readiness", evidence.not_verified)

    def test_simple_pair_runtime_comparison_is_privacy_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = root / "candidate.csv"
            reexport = root / "reexport.csv"
            self._write_simple_pair_candidate(candidate)
            self._write_synthetic_reexport(candidate, reexport)
            comparison = compare_simple_plus_simple_runtime(
                candidate,
                reexport,
                runtime_ui_vouchers_blank=True,
                runtime_logical_voucher_count=2,
            )
            payload = comparison.to_privacy_safe_dict()

        self.assertEqual(comparison.evidence_id, EVIDENCE_ID_SIMPLE_PLUS_SIMPLE_RUNTIME)
        self.assertTrue(comparison.flag_order_preserved)
        self.assertTrue(comparison.row_order_preserved)
        self.assertTrue(comparison.independently_balanced)
        self.assertEqual(
            dict(comparison.status_counts),
            {
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK.value: 18,
                RuntimeReexportFieldStatus.INPUT_PRESERVED.value: 42,
            },
        )
        self.assertIn("not a generator default", payload["interpretation"])
        serialized = json.dumps(payload, ensure_ascii=False)
        for private_value in ("借方甲", "貸方甲", "摘要甲", "20990104"):
            self.assertNotIn(private_value, serialized)

    @staticmethod
    def _write_synthetic_reexport(candidate: Path, destination: Path) -> None:
        rows = list(csv.reader(candidate.read_text(encoding="cp932").splitlines()))
        header = rows[0]
        records = rows[1:]
        indexes = {name: header.index(name) for name in header}
        for record in records:
            record[indexes["伝番"]] = "0"
            record[indexes["借方消費税"]] = "0"
            record[indexes["貸方科目"]] = "999"
            record[indexes["貸方科目正式名称"]] = "貸方正式"
            record[indexes["貸方消費税"]] = "0"
            record[indexes["借方部門コード"]] = "0"
            record[indexes["貸方部門コード"]] = "0"
            if record[indexes["借方科目名称"]]:
                record[indexes["借方科目"]] = "888"
                record[indexes["借方科目正式名称"]] = "借方正式"
        with destination.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(
                (["// synthetic metadata"], ["// synthetic period"], [], header, *records)
            )

    @staticmethod
    def _write_simple_pair_candidate(destination: Path) -> None:
        rows = []
        for debit, credit, amount, description in (
            ("借方甲", "貸方甲", "70", "摘要甲"),
            ("借方乙", "貸方乙", "90", "摘要乙"),
        ):
            row = {name: "" for name in OFFICIAL_HEADER}
            row.update(
                {
                    "//識別フラグ": "1111",
                    "日付": "20990104",
                    "借方科目名称": debit,
                    "借方金額": amount,
                    "貸方科目名称": credit,
                    "貸方金額": amount,
                    "摘要": description,
                }
            )
            rows.append([row[name] for name in OFFICIAL_HEADER])
        with destination.open("w", encoding="cp932", newline="") as handle:
            csv.writer(handle, lineterminator="\r\n").writerows(
                (OFFICIAL_HEADER, *rows)
            )

    def assert_blocked(
        self,
        config: JdlGeneratorAuthoredMultiGroupConfig,
        message: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(JdlGeneratorAuthoredMultiGroupError, message):
                generate_candidate(
                    config,
                    root / "data/private/experiments/jdl_import/multi_group",
                )

    @classmethod
    def config(cls) -> JdlGeneratorAuthoredMultiGroupConfig:
        return JdlGeneratorAuthoredMultiGroupConfig(
            simple=cls.simple_config(),
            compound=cls.compound_config(),
            journal_date_iso="2099-01-03",
            status=EXPERIMENT_STATUS,
        )

    @staticmethod
    def simple_config() -> JdlGeneratorAuthored1111Config:
        row = {name: "" for name in OFFICIAL_HEADER}
        row.update(
            {
                "//識別フラグ": "1111",
                "日付": "20990103",
                "借方科目名称": "借方甲",
                "借方金額": "70",
                "貸方科目名称": "貸方甲",
                "貸方金額": "70",
                "摘要": "単純摘要",
            }
        )
        decisions = _decisions(0, simple=True)
        return JdlGeneratorAuthored1111Config(
            jdl_columns=row,
            field_decisions=decisions,
            journal_date_iso="2099-01-03",
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

    @staticmethod
    def compound_config() -> JdlGeneratorAuthoredCompoundConfig:
        flags = ("1110", "1100", "1101")
        credits = ("50", "30", "20")
        rows: list[dict[str, str]] = []
        decisions: list[dict[str, str]] = []
        for index, flag in enumerate(flags):
            row = {name: "" for name in OFFICIAL_HEADER}
            row.update(
                {
                    "//識別フラグ": flag,
                    "日付": "20990103",
                    "借方科目名称": "借方甲" if index == 0 else "",
                    "借方金額": "100" if index == 0 else "0",
                    "貸方科目名称": ("貸方甲", "貸方乙", "貸方丙")[index],
                    "貸方金額": credits[index],
                    "摘要": "複合摘要" if index == 0 else "",
                }
            )
            rows.append(row)
            decisions.append(_decisions(index, simple=False))
        return JdlGeneratorAuthoredCompoundConfig(
            rows=tuple(rows),
            field_decisions=tuple(decisions),
            journal_date_iso="2099-01-03",
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
            source_observation={},
        )


def _decisions(index: int, *, simple: bool) -> dict[str, str]:
    decisions = {name: "EXPLICIT_EXPERIMENT_INPUT" for name in OFFICIAL_HEADER}
    decisions["伝番"] = "OFFICIAL_DOCUMENTED_OPTIONAL_BLANK"
    for field in (
        "借方科目",
        "借方科目正式名称",
        "貸方科目",
        "貸方科目正式名称",
    ):
        decisions[field] = "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK"
    decisions["借方科目名称"] = (
        "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME"
        if simple or index == 0
        else "OFFICIAL_DOCUMENTED_ACCOUNT_IDENTIFIER_ALTERNATIVE_BLANK"
    )
    decisions["貸方科目名称"] = "TARGET_MASTER_CONFIRMED_ACCOUNT_NAME"
    for field in SUBACCOUNT_FIELDS + DEPARTMENT_FIELDS:
        decisions[field] = "EXPLICIT_EXPERIMENT_CONDITION_BLANK"
    for field in TAX_FIELDS:
        decisions[field] = "OFFICIAL_DOCUMENTED_EXEMPT_BLANK"
    if not simple and index > 0:
        decisions["借方金額"] = "OFFICIAL_REQUIRED_AMOUNT_AND_OBSERVED_MISSING_SIDE_ZERO"
        decisions["摘要"] = "EXPLICIT_EXPERIMENT_CONDITION_BLANK"
    return decisions


if __name__ == "__main__":
    unittest.main()

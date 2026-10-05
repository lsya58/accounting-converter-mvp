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
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
)
from experiments.jdl_import.runtime_evidence import (
    EVIDENCE_ID_1000,
    RuntimeReexportFieldStatus,
    compare_generator_1000_runtime,
    generator_authored_1000_real_import_evidence,
)


OFFICIAL_HEADER = jdl_ibex_cashbook_official_journal_import_spec().column_names
NORMALIZED_FIELDS = (
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


class JdlGeneratorAuthored1000EvidenceTests(unittest.TestCase):
    def test_real_import_evidence_is_strictly_scoped(self) -> None:
        evidence = generator_authored_1000_real_import_evidence()

        self.assertEqual(evidence.evidence_id, EVIDENCE_ID_1000)
        self.assertEqual(evidence.evidence_level, EvidenceLevel.VERIFIED_BY_REAL_IMPORT)
        self.assertIn("one 1000 non-voucher journal record", evidence.verified_scope)
        self.assertIn("subaccount", evidence.not_verified)
        self.assertIn("production JDLOutputAdapter", evidence.not_verified)
        self.assertFalse(evidence.production_output_enabled)

    def test_candidate_to_reexport_comparison_is_privacy_safe(self) -> None:
        candidate_row = self.synthetic_row()
        reexport_row = list(candidate_row)
        for index, field in enumerate(NORMALIZED_FIELDS, start=1):
            self.assertEqual(candidate_row[OFFICIAL_HEADER.index(field)], "")
            reexport_row[OFFICIAL_HEADER.index(field)] = str(index)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = self.write_csv(root / "candidate.csv", candidate_row)
            reexport = self.write_csv(
                root / "reexport.csv",
                reexport_row,
                include_preamble=True,
            )
            comparison = compare_generator_1000_runtime(candidate, reexport)
            serialized = json.dumps(
                comparison.to_privacy_safe_dict(),
                ensure_ascii=False,
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
        for field in NORMALIZED_FIELDS:
            self.assertIs(
                statuses[field],
                RuntimeReexportFieldStatus.INPUT_BLANK_REEXPORT_NONBLANK,
            )
        self.assertNotIn("synthetic description", serialized)
        self.assertNotIn("synthetic debit", serialized)
        self.assertNotIn("synthetic credit", serialized)
        self.assertEqual(comparison.candidate_structure["preamble_row_count"], 0)
        self.assertEqual(comparison.reexport_structure["preamble_row_count"], 3)

    def test_expected_flag_mismatch_is_blocked(self) -> None:
        candidate_row = self.synthetic_row()
        reexport_row = list(candidate_row)
        reexport_row[0] = "1111"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidate = self.write_csv(root / "candidate.csv", candidate_row)
            reexport = self.write_csv(root / "reexport.csv", reexport_row)
            with self.assertRaisesRegex(ValueError, "expected identifier flag"):
                compare_generator_1000_runtime(candidate, reexport)

    def test_production_registry_is_enabled_by_final_acceptance_only(self) -> None:
        schema = jdl_ibex_cashbook_official_journal_import_schema_definition()

        self.assertEqual(schema.identity.evidence_level, EvidenceLevel.OFFICIAL_DOCUMENTED)
        self.assertEqual(
            production_adapter_registry().get_exact_output(schema.identity).status,
            AdapterAvailabilityStatus.EXACT,
        )

    def synthetic_row(self) -> list[str]:
        row = ["" for _ in OFFICIAL_HEADER]
        values = {
            "//識別フラグ": "1000",
            "日付": "20261003",
            "借方科目名称": "synthetic debit",
            "借方金額": "1200",
            "貸方科目名称": "synthetic credit",
            "貸方金額": "1200",
            "摘要": "synthetic description",
        }
        for field, value in values.items():
            row[OFFICIAL_HEADER.index(field)] = value
        return row

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

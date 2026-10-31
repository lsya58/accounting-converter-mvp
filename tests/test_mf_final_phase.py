from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application.moneyforward_description_replacement import (
    description_issues,
    description_replacement_candidate,
)
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_mf_final_evidence_batch as batch
from tests.test_mf_tax_capability_composition import context, entry


def two_d_one_c():
    return entry(
        ("DEBIT", "3561", False, "対象外", "500"),
        ("CREDIT", "1311", True, "対象外", "1100"),
        ("DEBIT", "8681", False, "課税仕入 10%", "600"),
    )


class GenericCompoundTest(unittest.TestCase):
    def test_0877_shapes_are_released_and_others_stay_blocked(self) -> None:
        item = two_d_one_c()
        result = ev.match_evidence_for_occurrence(item, item, context(), None)
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL)
        self.assertIn(
            "EVID-MF-JDL-35-5-2D1C-PURCHASE10-ROUNDTRIP-001",
            result.evidence.supporting_evidence_ids,
        )
        three_d_one_c = entry(
            ("DEBIT", "3561", False, "対象外", "300"),
            ("CREDIT", "1311", True, "対象外", "1100"),
            ("DEBIT", "8681", False, "課税仕入 10%", "400"),
            ("DEBIT", "8491", False, "課税仕入 10%", "400"),
        )
        blocked = ev.match_evidence_for_occurrence(three_d_one_c, three_d_one_c, context(), None)
        self.assertIsNone(blocked.evidence)
        self.assertIn("SHAPE_UNVERIFIED_IN_TAX_CONTEXT", blocked.mismatch_fields)
        with patch.dict(ev.VERIFIED_COMPOUND_SHAPES, {(3, 1): "EVID-TEST-3D1C"}):
            released = ev.match_evidence_for_occurrence(three_d_one_c, three_d_one_c, context(), None)
        self.assertIn("EVID-TEST-3D1C", released.evidence.supporting_evidence_ids)

    def test_generic_compound_rows_use_verified_literals(self) -> None:
        source = two_d_one_c()
        literal = ev.apply_tax_literals(source, source, "PENDING:test")
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL.value
        result = JdlOutputPreflight(context()).evaluate((literal,), jdl_ibex_35_5_output_profile())
        self.assertEqual(result.validation_results, ())
        flags = [row.identifier_flag for row in result.plan.rows]
        self.assertEqual(flags, ["1110", "1101"])
        taxed = result.plan.rows[1]
        self.assertEqual(
            (taxed.debit_tax_scope, taxed.debit_tax_category, taxed.debit_tax_input_method,
             taxed.debit_tax_amount, taxed.credit_account_code, taxed.credit_amount),
            ("仕　入", "10%", "内税", "54", "", "0"),
        )

    def test_generic_compound_rejects_unverified_literal(self) -> None:
        source = two_d_one_c()
        literal = ev.apply_tax_literals(source, source, "PENDING:test")
        literal.lines[2].tax_info.metadata["jdl_tax_input_method"] = "外税"
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL.value
        result = JdlOutputPreflight(context()).evaluate((literal,), jdl_ibex_35_5_output_profile())
        self.assertIn("JDL-OUT-TAX-LITERAL", {item.rule_id for item in result.validation_results})


class DescriptionCandidateTest(unittest.TestCase):
    def test_line_break_only_is_bulk_confirmable(self) -> None:
        candidate = description_replacement_candidate("振込手数料\n4月分")
        self.assertEqual(candidate.value, "振込手数料 4月分")
        self.assertTrue(candidate.bulk_confirmable)
        self.assertIn("改行などの制御文字を含みます", description_issues("振込手数料\n4月分"))

    def test_long_description_needs_individual_review(self) -> None:
        text = "あ" * 40
        candidate = description_replacement_candidate(text)
        self.assertEqual(candidate.value, "あ" * 32)
        self.assertEqual(candidate.kind, "TRUNCATED")
        self.assertFalse(candidate.bulk_confirmable)
        self.assertEqual(description_issues(text), ("32文字を超えています（40文字）",))

    def test_known_character_replacement_reused(self) -> None:
        candidate = description_replacement_candidate("髙橋商店")
        self.assertEqual((candidate.value, candidate.kind), ("高橋商店", "EXACT"))


def _write(path: Path, rows) -> Path:
    buffer = io.StringIO(newline="")
    header = jdl_ibex_cashbook_official_journal_import_spec().column_names
    csv.writer(buffer, lineterminator="\r\n").writerows((header, *rows))
    path.write_bytes(buffer.getvalue().encode("cp932"))
    return path


def _row(flag, description, *, debit="8681", credit="1311", credit_sub="0002", amount="1100", tax="100"):
    row = [""] * 30
    row[0], row[2] = flag, "20260529"
    row[3], row[4], row[5] = debit, "D", "D"
    row[8], row[9], row[10], row[11], row[12] = "仕　入", "10%", "内税", amount, tax
    row[13], row[14], row[15], row[16], row[17] = credit, "C", "C", credit_sub, "銀行A"
    row[21] = amount
    row[23] = description
    return row


class CaseCompareTest(unittest.TestCase):
    def test_each_case_is_judged_on_its_own(self) -> None:
        candidate_rows = [
            _row("1110", "EV482-A-R1"), _row("1101", "EV482-A-R2"),
            _row("1111", "EV482-B"),
        ]
        reexport_rows = []
        for row in candidate_rows:
            copy = list(row)
            copy[1], copy[26], copy[28] = "0", "0", "0"
            copy[16] = str(int(copy[16]))  # JDL drops leading zeros
            copy[22] = copy[22] or "0"
            reexport_rows.append(copy)
        reexport_rows[2][12] = "99"  # case B tax amount changed by JDL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "m.json"
            manifest.write_text(json.dumps({"cases": [
                {"case_id": "A", "marker": "EV482-A", "evidence_id_on_pass": "EVID-A"},
                {"case_id": "B", "marker": "EV482-B", "evidence_id_on_pass": "EVID-B"},
            ]}), encoding="utf-8")
            result = batch.compare(
                manifest, _write(root / "c.csv", candidate_rows), _write(root / "r.csv", reexport_rows)
            )
        self.assertTrue(result["cases"]["A"]["passed"], result["cases"]["A"])
        self.assertFalse(result["cases"]["B"]["passed"])
        self.assertEqual(result["cases"]["B"]["unexpected"][0]["field"], "debit_tax_amount")
        self.assertEqual(result["unexpected_reexport_groups"], [])


if __name__ == "__main__":
    unittest.main()


class FullE2eCompareTest(unittest.TestCase):
    def test_same_day_reorder_is_reported_separately_from_content_diffs(self) -> None:
        from accounting_converter.tools import mf_full_e2e_compare as full

        first, second = _row("1111", "A"), _row("1111", "B", amount="2200", tax="200")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = _write(root / "c.csv", [first, second])
            same = full.compare(candidate, _write(root / "same.csv", [first, second]))
            swapped = full.compare(candidate, _write(root / "swap.csv", [second, first]))
            changed_row = list(second)
            changed_row[12] = "199"
            changed = full.compare(candidate, _write(root / "chg.csv", [first, changed_row]))
        self.assertTrue(same["strict_passed"])
        self.assertFalse(swapped["strict_passed"])
        self.assertTrue(swapped["content_match"]["content_equal_ignoring_same_day_order"])
        self.assertEqual(swapped["content_match"]["dates_with_order_only_difference"], ["20260529"])
        self.assertFalse(changed["content_match"]["content_equal_ignoring_same_day_order"])


class DiagnosticSourceOfTruthTest(unittest.TestCase):
    def test_verified_shapes_include_exact_and_0877_shapes(self) -> None:
        shapes = ev.verified_mf_shapes()
        for shape in ((1, 1), (1, 2), (2, 2), (2, 1), (2, 3), (10, 9), (4, 6), (5, 7), (5, 8)):
            self.assertIn(shape, shapes)
        self.assertNotIn((3, 1), shapes)

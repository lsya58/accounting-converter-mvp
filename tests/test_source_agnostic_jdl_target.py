"""JDL target works from common journal semantics, whatever the source.

These tests do not mean Yayoi is supported: they only check that a non-MF
journal carrying the common row/tax semantics reaches the JDL target without
MF-specific dependencies, and that missing Evidence or Human mapping blocks.
"""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.adapters.input.moneyforward.observed_parser import MoneyForwardObservedParser
from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlEvidenceProfile,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl.preflight import JdlOutputPreflight
from accounting_converter.adapters.output.jdl.row_evidence import jdl_row_description_rows
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
    journal_physical_rows,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.profiles.known_formats import MONEYFORWARD_JOURNAL_EXPORT_HEADER
from tests.test_mf_tax_capability_composition import ACCOUNTS, SUBS, context

YAYOI_LIKE_SOURCE = "yayoi_like_test_double"


def neutral_entry(lines, *, entry_id="yayoi-like:1", tax_names=None) -> JournalEntry:
    """A journal built only from common semantics: no moneyforward_* keys."""
    reference = SourceReference("yayoi-like.txt", 1, "1")
    built, rows = [], []
    for side, code, sub, tax, amount, row, description in lines:
        rows.append(row)
        built.append(JournalLine(
            Side(side), ACCOUNTS[code], Decimal(amount), reference,
            sub_account=SUBS[code] if sub else None,
            tax_info=TaxInfo(category=tax) if tax else None,
            metadata={LINE_ROW_KEY: row, LINE_ROW_DESCRIPTION_KEY: description},
        ))
    return JournalEntry(
        entry_id, reference, date(2026, 5, 28), built, None,
        metadata={"source": YAYOI_LIKE_SOURCE, ROW_ORDER_KEY: tuple(sorted(set(rows)))},
    )


def yayoi_like_profile(confirmed: bool = True):
    """Different source tax names, confirmed to the same JDL target literals."""
    ctx = context()
    targets = {
        "課対仕入10%": ("10%", "仕　入"),
        "課税売上10%（弥生）": ("10%", "売　上"),
        "対象外（弥生）": ("", ""),
    }
    return SimpleNamespace(
        account_mappings={},
        subaccount_context_mappings={},
        tax_mappings={
            name: MappingValue(
                name, target, MappingStatus.USER_CONFIRMED if confirmed else MappingStatus.UNRESOLVED,
                metadata={
                    "jdl_tax_scope": scope,
                    "jdl_tax_context_identity_sha256": ev.tax_context_identity_sha256(ctx),
                },
            )
            for name, (target, scope) in targets.items()
        },
    )


class CommonRowSemanticsTest(unittest.TestCase):
    def test_mf_parser_fills_common_rows_in_order(self) -> None:
        rows = [
            ("1", "2026/05/18", "仕入高", "", "", "", "課税仕入 10%", "", "1000",
             "未払金", "", "", "", "対象外", "", "800", "ROW-A", "", ""),
            ("1", "2026/05/18", "", "", "", "", "", "", "",
             "預り金", "補助A", "", "", "対象外", "", "200", "ROW-B", "", ""),
        ]
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerows((MONEYFORWARD_JOURNAL_EXPORT_HEADER, *rows))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mf.csv"
            path.write_bytes(buffer.getvalue().encode("cp932"))
            (entry,) = MoneyForwardObservedParser().parse_path(path)
        physical = journal_physical_rows(entry)
        self.assertEqual([row.description for row in physical], ["ROW-A", "ROW-B"])
        self.assertEqual(physical[0].debit.account, "仕入高")
        self.assertEqual(physical[0].credit.account, "未払金")
        self.assertIsNone(physical[1].debit)
        self.assertEqual(physical[1].credit.sub_account, "補助A")

    def test_inconsistent_row_description_is_rejected(self) -> None:
        entry = neutral_entry([
            ("DEBIT", "3561", False, "", "500", 1, "A"),
            ("CREDIT", "1311", True, "", "500", 1, "B"),
        ])
        self.assertIsNone(journal_physical_rows(entry))


class SourceIndependenceTest(unittest.TestCase):
    def test_jdl_output_adapter_has_no_moneyforward_dependency(self) -> None:
        package = Path("src/accounting_converter/adapters/output/jdl")
        for path in package.glob("*.py"):
            with self.subTest(file=path.name):
                self.assertNotIn("moneyforward", path.read_text(encoding="utf-8").lower())

    def test_yayoi_like_compound_reaches_jdl_preflight(self) -> None:
        entry = neutral_entry([
            ("DEBIT", "3561", False, "対象外（弥生）", "500", 1, "ROW-1"),
            ("CREDIT", "1311", True, "対象外（弥生）", "1100", 1, "ROW-1"),
            ("DEBIT", "8681", False, "課対仕入10%", "600", 2, "ROW-2"),
        ])
        self.assertIsNotNone(jdl_row_description_rows(entry))
        result = ev.match_evidence_for_occurrence(entry, entry, context(), yayoi_like_profile())
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL)
        literal = ev.apply_verified_tax_semantics(entry, entry, context(), yayoi_like_profile())
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = result.evidence.profile.value
        preflight = JdlOutputPreflight(context()).evaluate((literal,), jdl_ibex_35_5_output_profile())
        self.assertEqual(preflight.validation_results, ())
        self.assertEqual([row.description for row in preflight.plan.rows], ["ROW-1", "ROW-2"])
        self.assertEqual(preflight.plan.rows[1].debit_tax_input_method, "内税")

    def test_shape_without_evidence_stays_blocked(self) -> None:
        entry = neutral_entry([
            ("DEBIT", "3561", False, "対象外（弥生）", "300", 1, "R1"),
            ("CREDIT", "1311", True, "対象外（弥生）", "1100", 1, "R1"),
            ("DEBIT", "8681", False, "課対仕入10%", "400", 2, "R2"),
            ("DEBIT", "8491", False, "課対仕入10%", "400", 3, "R3"),
        ])
        self.assertIsNone(jdl_row_description_rows(entry))
        result = ev.match_evidence_for_occurrence(entry, entry, context(), yayoi_like_profile())
        self.assertIsNone(result.evidence)
        self.assertIn("SHAPE_UNVERIFIED_IN_TAX_CONTEXT", result.mismatch_fields)


class TargetTaxEvidenceTest(unittest.TestCase):
    def test_other_source_tax_name_reuses_same_jdl_evidence(self) -> None:
        entry = neutral_entry([
            ("DEBIT", "1111", False, "対象外（弥生）", "1100", 1, "S"),
            ("CREDIT", "6121", False, "課税売上10%（弥生）", "1100", 1, "S"),
        ])
        result = ev.match_evidence_for_occurrence(entry, entry, context(), yayoi_like_profile())
        self.assertEqual(result.evidence.evidence_id, ev.SALES10_EVIDENCE_ID)
        self.assertEqual(
            ev.target_tax_semantic(entry.lines[1], yayoi_like_profile(), context()),
            JdlTaxSemantic.SALES_10_EXTERNAL.value,
        )

    def test_unconfirmed_source_mapping_blocks(self) -> None:
        entry = neutral_entry([
            ("DEBIT", "1111", False, "対象外（弥生）", "1100", 1, "S"),
            ("CREDIT", "6121", False, "課税売上10%（弥生）", "1100", 1, "S"),
        ])
        result = ev.match_evidence_for_occurrence(
            entry, entry, context(), yayoi_like_profile(confirmed=False)
        )
        self.assertIsNone(result.evidence)
        self.assertIn("TAX_MAPPING_UNCONFIRMED", result.mismatch_fields)

    def test_mapping_from_another_tax_context_blocks(self) -> None:
        profile = yayoi_like_profile()
        for mapping in profile.tax_mappings.values():
            mapping.metadata["jdl_tax_context_identity_sha256"] = "other-context"
        entry = neutral_entry([
            ("DEBIT", "1111", False, "対象外（弥生）", "1100", 1, "S"),
            ("CREDIT", "6121", False, "課税売上10%（弥生）", "1100", 1, "S"),
        ])
        result = ev.match_evidence_for_occurrence(entry, entry, context(), profile)
        self.assertIn("TAX_MAPPING_UNCONFIRMED", result.mismatch_fields)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservationError,
    JdlMasterObservationService,
)
from accounting_converter.diagnostics.jdl_csv.observed_schemas import (
    JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER,
)
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class JdlMasterObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = JdlMasterObservationService()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_extracts_exact_used_identities_without_claiming_full_master(self) -> None:
        source = self._write(
            "observed.csv",
            (
                self._row("1000", "1001", "架空現金", "架空現金正式", "2001", "架空売上", "架空売上正式"),
                self._row("1000", "1001", "架空現金", "架空現金正式", "3001", "架空預金", "架空預金正式"),
            ),
        )

        result = self.service.observe_journal_export(source)

        self.assertEqual(result.completeness, JdlMasterCompleteness.OBSERVED_USED_MASTER)
        self.assertEqual(len(result.accounts), 3)
        self.assertEqual(result.accounts[0].target_master_code, "1001")
        self.assertEqual(result.accounts[0].target_formal_name, "架空現金正式")
        self.assertEqual(result.sources[0].data_record_count, 2)
        self.assertNotIn("架空現金", str(result.privacy_safe_summary()))

    def test_observes_subaccount_parent_and_department_without_promoting_them(self) -> None:
        row = self._row(
            "1000", "1001", "架空現金", "架空現金正式", "2001", "架空売上", "架空売上正式"
        )
        row[6:8] = ["1", "架空補助"]
        row[26:28] = ["1", "架空部門"]
        result = self.service.observe_journal_export(self._write("optional.csv", (row,)))
        draft = self.service.build_unconfirmed_context_draft(result)

        self.assertEqual(len(result.subaccounts), 1)
        self.assertEqual(result.subaccounts[0].parent_account_code, "1001")
        self.assertEqual(len(result.departments), 1)
        self.assertFalse(draft.production_usable)
        self.assertFalse(draft.context.subaccounts)
        self.assertFalse(draft.context.departments)
        self.assertTrue(draft.validation_results)

    def test_merge_detects_conflicts_and_excludes_ambiguous_account(self) -> None:
        first = self.service.observe_journal_export(
            self._write("one.csv", (self._row("1000", "1001", "架空現金", "正式A", "2001", "架空売上", "正式売上"),))
        )
        second = self.service.observe_journal_export(
            self._write("two.csv", (self._row("1000", "1001", "架空現金", "正式B", "3001", "架空預金", "正式預金"),))
        )

        merged = self.service.merge((first, second))

        self.assertTrue(merged.conflicts)
        self.assertNotIn("1001", {item.target_master_code for item in merged.accounts})

    def test_merge_detects_subaccount_and_department_conflicts(self) -> None:
        first_row = self._row(
            "1000", "1001", "架空現金", "正式現金", "2001", "架空売上", "正式売上"
        )
        first_row[6:8] = ["1", "架空補助A"]
        first_row[26:28] = ["1", "架空部門A"]
        second_row = self._row(
            "1000", "1001", "架空現金", "正式現金", "2001", "架空売上", "正式売上"
        )
        second_row[6:8] = ["1", "架空補助B"]
        second_row[26:28] = ["1", "架空部門B"]

        merged = self.service.merge(
            (
                self.service.observe_journal_export(
                    self._write("optional-one.csv", (first_row,))
                ),
                self.service.observe_journal_export(
                    self._write("optional-two.csv", (second_row,))
                ),
            )
        )

        categories = {item.category for item in merged.conflicts}
        self.assertIn("SUBACCOUNT_CODE_CONFLICT", categories)
        self.assertIn("DEPARTMENT_CODE_CONFLICT", categories)
        self.assertFalse(merged.subaccounts)
        self.assertFalse(merged.departments)

    def test_coverage_uses_exact_identity_only(self) -> None:
        observed = self.service.observe_journal_export(
            self._write("coverage.csv", (self._row("1000", "1001", "架空現金", "架空現金正式", "2001", "架空売上", "架空売上正式"),))
        )
        coverage = self.service.coverage(
            ("架空現金", "架空売上正式", "似ているが別の科目"), observed
        )

        self.assertEqual(coverage.required_count, 3)
        self.assertEqual(coverage.exact_single_count, 2)
        self.assertEqual(coverage.missing_count, 1)
        self.assertEqual(coverage.ambiguous_count, 0)

    def test_wrong_header_is_blocked_and_partial_identity_is_not_guessed(self) -> None:
        path = self._write("bad.csv", (self._row("1000", "1001", "架空現金", "架空現金正式", "2001", "架空売上", "架空売上正式"),))
        raw = path.read_bytes().decode("cp932").replace("//識別フラグ", "識別")
        path.write_bytes(raw.encode("cp932"))
        with self.assertRaises(JdlMasterObservationError):
            self.service.observe_journal_export(path)

        partial = self._row("1000", "1001", "架空現金", "", "2001", "架空売上", "架空売上正式")
        result = self.service.observe_journal_export(
            self._write("partial.csv", (partial,))
        )
        self.assertNotIn("1001", {item.target_master_code for item in result.accounts})
        self.assertIn(
            "INCOMPLETE_ACCOUNT_IDENTITY",
            {item.category for item in result.conflicts},
        )

        malformed = self._write(
            "malformed.csv",
            (self._row("1000", "1001", "架空現金", "架空現金正式", "2001", "架空売上", "架空売上正式")[:-1],),
        )
        with self.assertRaises(JdlMasterObservationError):
            self.service.observe_journal_export(malformed)

    def test_production_registry_remains_unavailable(self) -> None:
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.assertEqual(
            registry.get_exact_input(source).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )
        self.assertFalse(registry.has_conversion_pair(source, target))

    def _write(self, name: str, rows: tuple[list[str], ...]) -> Path:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(("// synthetic evidence",))
        writer.writerow(JDL_IBEX_CASHBOOK_35_5_OBSERVED_HEADER)
        writer.writerows(rows)
        path = self.root / name
        path.write_bytes(output.getvalue().encode("cp932"))
        return path

    @staticmethod
    def _row(
        flag: str,
        debit_code: str,
        debit_name: str,
        debit_formal: str,
        credit_code: str,
        credit_name: str,
        credit_formal: str,
    ) -> list[str]:
        row = [""] * 30
        row[0] = flag
        row[2] = "20261001"
        row[3:6] = [debit_code, debit_name, debit_formal]
        row[11] = "100"
        row[13:16] = [credit_code, credit_name, credit_formal]
        row[21] = "100"
        return row


if __name__ == "__main__":
    unittest.main()

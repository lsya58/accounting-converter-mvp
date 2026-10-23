from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.adapters.input.jdl import JdlMigrationParser
from accounting_converter.tools.generate_jdl_migration_tax_scope_batch import (
    _candidate_bytes,
    compare_batch,
    _select_cases,
)


class JdlMigrationTaxScopeBatchTests(unittest.TestCase):
    def test_six_distinct_cases_generate_strict_private_probe_shape(self) -> None:
        entries = (
            self._entry(("1000",), "売五種", "10%", "612", False),
            self._entry(("1000",), "売五種", "10%", "613", False),
            self._entry(("1000",), "売五種", "10%", "612", True),
            self._entry(("1111",), "売五種", "10%", "612", True),
            self._entry(("1000",), "非売上", "", "612", False),
            self._entry(
                ("1110", "1100", "1100", "1100", "1100", "1100", "1101"),
                "売二種",
                "10%",
                "612",
                False,
            ),
        )
        selected = _select_cases(entries)
        raw = _candidate_bytes(
            selected, tuple(f"202603{20 + index:02d}" for index in range(6))
        )
        parsed = JdlMigrationParser().parse_text(raw.decode("cp932"))

        self.assertEqual(len(selected), 6)
        self.assertEqual(len(parsed.entries), 6)
        self.assertEqual(parsed.journal_record_count, 12)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertTrue(all(entry.is_balanced() for entry in parsed.entries))

        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.csv"
            reexport = Path(directory) / "reexport.csv"
            candidate.write_bytes(raw)
            reexport.write_bytes(raw)
            self.assertTrue(compare_batch(candidate, reexport)["comparison_pass"])

            rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
            rows[-1][0] = "1111"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerows(rows)
            reexport.write_bytes(stream.getvalue().encode("cp932"))
            result = compare_batch(candidate, reexport)
            self.assertFalse(result["comparison_pass"])
            self.assertEqual(
                result["case_results"][-1]["mismatched_fields"], ["flags"]
            )

    @staticmethod
    def _entry(flags, scope, category, tax_account_code, other_sub):
        rows = []
        debit_rows = 2 if len(flags) == 7 else 1
        credit_rows = 5 if len(flags) == 7 else 1
        debit_indexes = {0, 5} if len(flags) == 7 else {0}
        credit_indexes = set(range(len(flags))) - debit_indexes if len(flags) == 7 else {0}
        tax_row_index = min(credit_indexes)
        for index, flag in enumerate(flags):
            row = [""] * 30
            row[0:3] = [flag, "1", "20260301"]
            if index in debit_indexes:
                row[3:6] = ["111", "現金", "現金"]
                if other_sub:
                    row[6:8] = ["0001", "合成補助"]
            if index in credit_indexes:
                row[13:16] = [tax_account_code, "合成売上", "合成売上"]
            if index == tax_row_index:
                row[18:20] = [scope, category]
            row[26:30] = ["001", "合成部門", "001", "合成部門"]
            rows.append({"source_columns": tuple(row)})
        tax_info = SimpleNamespace(metadata={
            "jdl_tax_scope": scope,
            "jdl_tax_category": category,
        })
        debit = SimpleNamespace(
            tax_info=None,
            sub_account="合成補助" if other_sub else None,
            department="合成部門",
            metadata={
                "jdl_source_account_code": "111",
                "jdl_source_account_formal_name": "現金",
            },
        )
        credit = SimpleNamespace(
            tax_info=tax_info,
            sub_account=None,
            department="合成部門",
            metadata={
                "jdl_source_account_code": tax_account_code,
                "jdl_source_account_formal_name": "合成売上",
            },
        )
        return SimpleNamespace(
            lines=(debit, credit),
            metadata={"identifier_flags": flags, "physical_rows": tuple(rows)},
        )


if __name__ == "__main__":
    unittest.main()

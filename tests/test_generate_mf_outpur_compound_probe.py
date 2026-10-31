from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.adapters.input.moneyforward.observed_parser import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.tools import generate_mf_outpur_compound_probe as probe
from accounting_converter.tools.generate_mf_exact_shape_probe import ExactShapeProbeError
from accounting_converter.tools.mf_tax_context_probe import _journal_rows, _journal_count


class OutpurCompoundProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.company_dir = self.root / "company"
        self.company_dir.mkdir()
        self.company = self.company_dir / "company.json"
        self.profile = self.root / "profile.json"
        self.source = self.root / "source.csv"
        self.context = SimpleNamespace(
            account_master=(
                SimpleNamespace(target_master_code="8471", target_name="旅費交通", target_formal_name="旅費交通費"),
                SimpleNamespace(target_master_code="1111", target_name="現金", target_formal_name="現金"),
            ), subaccounts=(),
        )
        self.company.write_text(json.dumps({
            "conversion_profile_id": "profile-test", "context_fingerprint": "setup-test",
            "expected_source_format_key": "Money Forward", "expected_target_format_key": "JDL",
            "jdl_context_relative_path": "jdl-context.json",
        }))
        self._write_profile()
        self._write_source()

    def _write_profile(self, *, stale: bool = False) -> None:
        self.profile.write_text(json.dumps({
            "profile_id": "profile-test",
            "account_mappings": [
                {"source_value": source, "status": "USER_CONFIRMED", "metadata": {
                    "setup_context_sha256": "old" if stale else "setup-test",
                    "target_code": code, "target_formal_name": formal,
                }}
                for source, code, formal in (("旅費交通費", "8471", "旅費交通費"), ("現金", "1111", "現金"))
            ],
            "subaccount_context_mappings": [],
            "tax_mappings": [{"source_value": "対象外仕入", "status": "UNRESOLVED"}],
        }, ensure_ascii=False))

    def _write_source(self) -> None:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        for journal, (debits, credits) in enumerate(((4, 6),) * 5 + ((5, 7),) + ((5, 8),) * 5, 1):
            debit_amount = credits * 100 // debits
            for index in range(debits + credits):
                row = ["" for _ in range(19)]
                row[0] = str(journal)
                row[1] = "2026/5/1"
                row[16] = f"ROW-{journal}-{index}"
                if index < debits:
                    row[2] = "旅費交通費"
                    row[6] = "対象外仕入" if index == 0 else "対象外"
                    row[8] = str(debit_amount)
                else:
                    row[9] = "現金"
                    row[13] = "対象外"
                    row[15] = "100"
                writer.writerow(row)
        self.source.write_bytes(stream.getvalue().encode("cp932"))

    def generate(self) -> tuple[Path, Path]:
        with patch.object(probe.JdlTargetContextLoader, "load", return_value=self.context), patch.object(
            probe, "context_is_verified", return_value=True
        ), patch.object(probe, "tax_context_identity_sha256", return_value="tax-test"):
            return probe.generate(self.source, self.company, self.profile, self.root / "output")

    def test_gated_compound_probe_preserves_grouping_and_descriptions(self) -> None:
        output, manifest = self.generate()
        raw = output.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        rows = _journal_rows(output)
        self.assertEqual(len(rows), 127)
        self.assertEqual(_journal_count(rows), 11)
        self.assertTrue(all(len(row) == 30 for row in rows))
        self.assertEqual([rows[i][0] for i in (0, 9, 10, 19)], ["1110", "1101", "1110", "1101"])
        self.assertEqual(rows[0][23], "ROW-1-0")
        self.assertEqual(rows[9][23], "ROW-1-9")
        self.assertEqual(rows[0][8:10], ("", ""))
        self.assertEqual(rows[0][12], "0")
        data = json.loads(manifest.read_text())
        self.assertFalse(data["production_allowed"])
        self.assertEqual(data["source_tax_mapping_status"], "UNRESOLVED")
        self.assertEqual(len(data["cases"]), 11)
        with self.assertRaises(FileExistsError):
            self.generate()

    def test_stale_account_mapping_fails_closed(self) -> None:
        self._write_profile(stale=True)
        with self.assertRaises(ExactShapeProbeError):
            self.generate()
        self.assertFalse((self.root / "output" / "mf_outpur_compound_11_pending.csv").exists())


if __name__ == "__main__":
    unittest.main()

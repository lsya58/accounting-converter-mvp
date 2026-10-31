from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.tools import generate_mf_sales10_selfexport_probe as probe
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


class Sales10SelfExportProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = SimpleNamespace(
            product="JDL IBEX 出納帳",
            version="35.5",
            tax_processing_mode=SimpleNamespace(value="TAXABLE_TAX_EXCLUDED"),
            effective_taxation_method=SimpleNamespace(value="STANDARD"),
            effective_input_tax_credit_method=SimpleNamespace(value="PROPORTIONAL"),
            account_master=(
                SimpleNamespace(target_master_code="1111", target_name="現金", target_formal_name="現金"),
                SimpleNamespace(target_master_code="6121", target_name="売上高", target_formal_name="売上高"),
            ),
            subaccounts=(),
        )

    def self_export(self, *, tax_scope: str = "OBSERVED", debit_code: str = "1111", description: str = probe.MARKER) -> Path:
        row = ["" for _ in probe.HEADER]
        values = {
            "//識別フラグ": "1111", "日付": "20260523",
            "借方科目": debit_code, "借方科目名称": "現金", "借方科目正式名称": "現金",
            "借方金額": "1100", "貸方科目": "6121",
            "貸方科目名称": "売上高", "貸方科目正式名称": "売上高",
            "貸方課区": tax_scope, "貸方税区": "10%", "貸方税入力方法": "外税",
            "貸方金額": "1100", "貸方消費税": "100", "摘要": description,
        }
        for name, value in values.items():
            row[probe.FIELDS[name]] = value
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(probe.HEADER)
        writer.writerow(row)
        path = self.root / "self_export.csv"
        path.write_bytes(stream.getvalue().encode("cp932"))
        return path

    def generate(self, source: Path) -> tuple[Path, Path]:
        with patch.object(probe.JdlTargetContextLoader, "load", return_value=self.context), patch.object(
            probe, "context_is_verified", return_value=True
        ), patch.object(probe, "tax_context_identity_sha256", return_value="context-test"):
            return probe.generate(source, self.root / "context.json", self.root / "output")

    def test_observed_literal_only_and_no_overwrite(self) -> None:
        output, manifest = self.generate(self.self_export())
        raw = output.read_bytes()
        self.assertFalse(raw.startswith(bytes.fromhex("efbbbf")))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        rows = _journal_rows(output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 30)
        self.assertEqual(rows[0][probe.FIELDS["貸方課区"]], "OBSERVED")
        self.assertEqual(rows[0][probe.FIELDS["貸方税区"]], "10%")
        self.assertEqual(rows[0][probe.FIELDS["貸方税入力方法"]], "外税")
        self.assertEqual(rows[0][probe.FIELDS["貸方消費税"]], "100")
        self.assertEqual(rows[0][probe.FIELDS["日付"]], "20260524")
        self.assertEqual(rows[0][probe.FIELDS["摘要"]], probe.IMPORT_MARKER)
        self.assertEqual(json.loads(manifest.read_text())["production_allowed"], False)
        with self.assertRaises(FileExistsError):
            self.generate(self.root / "self_export.csv")

    def test_unknown_or_missing_sales_tax_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.generate(self.self_export(tax_scope=""))
        with self.assertRaises(ValueError):
            self.generate(self.self_export(debit_code="1551"))
        with self.assertRaises(ValueError):
            self.generate(self.self_export(tax_scope="売一種"))

    def test_single_unmarked_self_export_is_safe_to_identify(self) -> None:
        output, manifest = self.generate(self.self_export(tax_scope="売　上", description=""))
        self.assertEqual(_journal_rows(output)[0][probe.FIELDS["貸方課区"]], "売　上")
        self.assertEqual(
            json.loads(manifest.read_text())["self_export_selection_basis"],
            "SINGLE_ROW_EXACT_DATE_NO_DESCRIPTION",
        )


if __name__ == "__main__":
    unittest.main()

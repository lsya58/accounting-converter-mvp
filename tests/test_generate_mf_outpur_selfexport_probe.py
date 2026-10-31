from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.tools import generate_mf_outpur_selfexport_probe as probe
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


class OutpurSelfExportProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = SimpleNamespace(
            product="JDL IBEX 出納帳", version="35.5",
            tax_processing_mode=SimpleNamespace(value="TAXABLE_TAX_EXCLUDED"),
            effective_taxation_method=SimpleNamespace(value="STANDARD"),
            effective_input_tax_credit_method=SimpleNamespace(value="PROPORTIONAL"),
            account_master=(
                SimpleNamespace(target_master_code="8471", target_formal_name="旅費交通費"),
                SimpleNamespace(target_master_code="1111", target_formal_name="現金"),
            ),
            subaccounts=(),
        )

    def source(self, **changes: str) -> Path:
        values = {
            "//識別フラグ": "1111", "日付": "20260525",
            "借方科目": "8471", "借方科目名称": "旅費交通", "借方科目正式名称": "旅費交通費",
            "借方金額": "1100", "借方消費税": "0",
            "貸方科目": "1111", "貸方科目名称": "現金", "貸方科目正式名称": "現金",
            "貸方金額": "1100", "貸方消費税": "0",
            "借方部門コード": "0", "貸方部門コード": "0", "摘要": probe.SELF_MARKER,
        }
        values.update(changes)
        row = [values.get(name, "") for name in probe.HEADER]
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

    def test_exact_pending_probe_and_no_overwrite(self) -> None:
        source = self.source()
        output, manifest = self.generate(source)
        raw = output.read_bytes()
        self.assertFalse(raw.startswith(bytes.fromhex("efbbbf")))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        rows = _journal_rows(output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 30)
        row = rows[0]
        self.assertEqual(row[probe.FIELDS["日付"]], "20260526")
        self.assertEqual(row[probe.FIELDS["摘要"]], probe.IMPORT_MARKER)
        for side in ("借方", "貸方"):
            self.assertEqual(row[probe.FIELDS[f"{side}課区"]], "")
            self.assertEqual(row[probe.FIELDS[f"{side}税区"]], "")
            self.assertEqual(row[probe.FIELDS[f"{side}税入力方法"]], "")
            self.assertEqual(row[probe.FIELDS[f"{side}消費税"]], "0")
        metadata = json.loads(manifest.read_text())
        self.assertFalse(metadata["production_allowed"])
        self.assertEqual(metadata["human_selected_jdl_ui_label"], "0 対象外")
        with self.assertRaises(FileExistsError):
            self.generate(source)

    def test_rejects_changed_witness_or_context(self) -> None:
        for change in ({"借方課区": "対象外"}, {"借方補助": "0001"}, {"貸方科目": "1112"}, {"借方消費税": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.generate(self.source(**change))
        self.context.subaccounts = (SimpleNamespace(parent_account_code="8471"),)
        with self.assertRaises(ValueError):
            self.generate(self.source())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.profiles.jdl_official import jdl_ibex_cashbook_official_journal_import_spec
from accounting_converter.tools import generate_mf_nonpur_bank_probe as probe
from accounting_converter.tools.mf_tax_context_probe import _journal_rows


class NonpurBankProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.csv"
        self.source.write_bytes(b"synthetic-source")
        self.template = self.root / "template.csv"
        self.company_dir = self.root / "company"
        self.company_dir.mkdir()
        self.context_path = self.company_dir / "jdl-context.json"
        self.context_path.write_text("{}")
        self.company = self.company_dir / "company.json"
        self.profile_path = self.root / "profile.json"
        self.profile_path.write_text("{}")
        self.company.write_text(json.dumps({
            "jdl_context_relative_path": "jdl-context.json",
            "context_fingerprint": hashlib.sha256(self.context_path.read_bytes()).hexdigest(),
            "conversion_profile_id": "profile-test",
            "profile_fingerprint": hashlib.sha256(b"profile-test").hexdigest(),
        }))
        self.target_debit = SimpleNamespace(target_master_code="8571", target_name="保険料", target_formal_name="保険料")
        self.target_credit = SimpleNamespace(target_master_code="1311", target_name="普通預金", target_formal_name="普通預金")
        self.target_sub = SimpleNamespace(parent_account_code="1311", output_code="0002", output_name="テスト銀行")
        self.context = SimpleNamespace(account_master=(self.target_debit, self.target_credit), subaccounts=(self.target_sub,))
        self.entry = self._entry()
        self._write_template()

    def _entry(self) -> JournalEntry:
        ref = SourceReference("synthetic.csv", 2, "1")
        return JournalEntry(
            "synthetic-entry", ref, date(2026, 5, 1),
            [
                JournalLine(Side.DEBIT, "保険料", Decimal(1100), ref, tax_info=TaxInfo("非課税仕入")),
                JournalLine(Side.CREDIT, "普通預金", Decimal(1100), ref, sub_account="TEST", tax_info=TaxInfo("対象外")),
            ],
        )

    def _write_template(self) -> None:
        header = tuple(jdl_ibex_cashbook_official_journal_import_spec().column_names)
        row = [""] * 30
        row[0], row[2], row[3], row[4], row[5] = "1111", "20260521", "8571", "保険料", "保険料"
        row[8], row[11], row[13], row[14], row[15], row[16], row[17] = "非仕入", "1100", "3181", "未払金", "未払金", "0001", "旧補助"
        row[21], row[23] = "1100", "MF-TAX-NONPUR-PENDING"
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerow(row)
        self.template.write_bytes(stream.getvalue().encode("cp932"))

    def generate(self, *, credit_code: str = "1311"):
        profile = SimpleNamespace(profile_id="profile-test")
        with patch.object(probe.JdlTargetContextLoader, "load", return_value=self.context), patch.object(
            probe, "context_is_verified", return_value=True
        ), patch.object(probe, "tax_context_identity_sha256", return_value="context-test"), patch.object(
            probe.ConversionProfileStore, "from_json_text", return_value=profile
        ), patch.object(probe.ConversionProfileStore, "to_json_text", return_value="profile-test"), patch.object(
            probe.MoneyForwardObservedParser, "parse_path", return_value=(self.entry,)
        ), patch.object(probe, "_confirmed_target", side_effect=(
            (self.target_debit, None),
            (SimpleNamespace(target_master_code=credit_code), self.target_sub),
        )):
            return probe.generate(self.source, self.template, self.company, self.profile_path, self.root / "output")

    def test_exact_pending_and_no_overwrite(self) -> None:
        output, manifest = self.generate()
        rows = _journal_rows(output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 30)
        self.assertEqual(rows[0][2], "20260528")
        self.assertEqual(rows[0][13:18], ("1311", "普通預金", "普通預金", "0002", "テスト銀行"))
        self.assertEqual(rows[0][8], "非仕入")
        self.assertFalse(json.loads(manifest.read_text())["production_allowed"])
        self.assertNotIn(b"\n", output.read_bytes().replace(b"\r\n", b""))
        with self.assertRaises(FileExistsError):
            self.generate()

    def test_changed_mapping_or_context_blocks(self) -> None:
        from accounting_converter.tools.generate_mf_exact_shape_probe import ExactShapeProbeError

        with self.assertRaises(ExactShapeProbeError):
            self.generate(credit_code="OTHER")
        self.company.write_text(json.dumps({
            **json.loads(self.company.read_text()), "context_fingerprint": "stale",
        }))
        with self.assertRaises(ExactShapeProbeError):
            self.generate()


if __name__ == "__main__":
    unittest.main()

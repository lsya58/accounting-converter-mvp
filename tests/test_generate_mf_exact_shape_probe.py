from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.moneyforward.observed_parser import (
    MONEYFORWARD_OBSERVED_HEADER,
    MoneyForwardObservedParser,
)
from accounting_converter.domain.mapping import DEFAULT_SUBACCOUNT_SOURCE_VALUE
from accounting_converter.tools.generate_mf_exact_shape_probe import (
    ExactShapeProbeError,
    _compound_flags,
    _target_subaccount,
    generate,
)
from accounting_converter.tools.mf_tax_context_probe import compare_probe


class ExactShapeProbeTests(unittest.TestCase):
    def test_blank_source_uses_only_explicit_confirmed_default_subaccount(self) -> None:
        self.assertEqual(_target_subaccount("売掛金", None, []), ("", ""))
        mapping = {
            "source_parent": "売掛金",
            "source_subaccount": DEFAULT_SUBACCOUNT_SOURCE_VALUE,
            "policy": "PRESERVE_SUBACCOUNT",
            "target_code": "0006",
            "target_name": "確認済み補助",
            "human_confirmed": True,
        }
        self.assertEqual(
            _target_subaccount("売掛金", None, [mapping]),
            ("0006", "確認済み補助"),
        )
        with self.assertRaises(ExactShapeProbeError):
            _target_subaccount("売掛金", None, [{**mapping, "human_confirmed": False}])

    def test_ten_physical_rows_use_one_compound_voucher_flag_sequence(self) -> None:
        self.assertEqual(
            _compound_flags(10),
            ("1110", *("1100" for _ in range(8)), "1101"),
        )

    def test_generates_strict_pending_1d2c_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            self._write_source(source)
            config = root / "config.json"
            config.write_text(
                json.dumps(self._config(source), ensure_ascii=False), encoding="utf-8"
            )

            candidate, manifest = generate(source, config, root / "probe")

            raw = candidate.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)
            rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
            self.assertEqual([len(row) for row in rows], [30] * 6)
            self.assertEqual(rows[1][0], "// 出力期間 ： 20260501 ～ 20260501")
            self.assertEqual([row[0] for row in rows[4:]], ["1110", "1101"])
            self.assertEqual(rows[4][3], "7121")
            self.assertEqual(rows[5][16:18], ["0001", "所得税"])
            self.assertEqual(rows[5][11], "0")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(payload["NOT_FOR_PRODUCTION"])
            self.assertFalse(payload["production_allowed"])
            self.assertEqual(payload["source_line_count"], 3)
            self.assertEqual(payload["candidate_physical_row_count"], 2)
            self.assertEqual(payload["import_period"], {"start": "20260501", "end": "20260501"})
            with self.assertRaises(FileExistsError):
                generate(source, config, root / "probe")

    def test_refuses_missing_human_confirmed_subaccount_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            self._write_source(source)
            payload = self._config(source)
            payload["subaccount_mappings"] = []
            config = root / "config.json"
            config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(ExactShapeProbeError):
                generate(source, config, root / "probe")
            self.assertFalse((root / "probe" / "candidate.csv").exists())

    def test_blank_to_zero_unused_amount_is_not_silently_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            self._write_source(source)
            config = root / "config.json"
            config.write_text(
                json.dumps(self._config(source), ensure_ascii=False), encoding="utf-8"
            )
            reexport, _ = generate(source, config, root / "probe")
            rows = list(csv.reader(io.StringIO(reexport.read_bytes().decode("cp932"))))
            rows[-1][11] = ""
            stream = io.StringIO(newline="")
            csv.writer(stream, lineterminator="\r\n").writerows(rows)
            imported = root / "imported.csv"
            imported.write_bytes(stream.getvalue().encode("cp932"))

            result = compare_probe(imported, reexport)
            self.assertEqual(result.classification, "UNEXPECTED_CHANGE")
            self.assertEqual(result.unexpected_changes, ("row-2:借方金額",))
            self.assertEqual(compare_probe(reexport, reexport).classification, "EXACT_MATCH")

    @staticmethod
    def _write_source(path: Path) -> None:
        rows = [
            MONEYFORWARD_OBSERVED_HEADER,
            (
                "1", "2026/5/1", "仕入高", "", "", "", "課税仕入 10%", "", "1100",
                "買掛金", "", "", "", "対象外", "", "1000", "TEST", "", "",
            ),
            (
                "1", "2026/5/1", "", "", "", "", "", "", "",
                "預り金", "所得税", "", "", "対象外", "", "100", "TEST", "", "",
            ),
        ]
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\r\n").writerows(rows)
        path.write_bytes(buffer.getvalue().encode("cp932"))

    @staticmethod
    def _config(source: Path) -> dict[str, object]:
        entry = MoneyForwardObservedParser().parse_path(source)[0]
        return {
            "NOT_FOR_PRODUCTION": True,
            "production_allowed": False,
            "journal_sha256": hashlib.sha256(entry.id.encode("utf-8")).hexdigest(),
            "shape": "1D2C",
            "probe_date": "20260501",
            "output_name": "candidate.csv",
            "account_mappings": {
                "仕入高": {"code": "7121", "name": "仕入高", "human_confirmed": True},
                "買掛金": {"code": "3141", "name": "買掛金", "human_confirmed": True},
                "預り金": {"code": "3271", "name": "預り金", "human_confirmed": True},
            },
            "subaccount_mappings": [
                {
                    "source_parent": "預り金",
                    "source_subaccount": "所得税",
                    "policy": "PRESERVE_SUBACCOUNT",
                    "target_code": "0001",
                    "target_name": "所得税",
                    "human_confirmed": True,
                }
            ],
            "line_tax_mappings": {
                "0:DEBIT": {
                    "scope": "仕　入", "category": "10%", "input_method": "",
                    "tax_amount": "100", "human_confirmed": True,
                },
                "0:CREDIT": {"human_confirmed": True},
                "1:CREDIT": {"human_confirmed": True},
            },
        }


if __name__ == "__main__":
    unittest.main()

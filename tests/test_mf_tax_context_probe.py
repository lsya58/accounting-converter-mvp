from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.tools.mf_tax_context_probe import (
    HEADER,
    compare_probe,
    generate_probe,
)


class MfTaxContextProbeTests(unittest.TestCase):
    def test_generate_private_batch_and_compare_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            output = root / "probe.csv"
            manifest = root / "manifest.json"
            config.write_text(
                json.dumps(self._config(), ensure_ascii=False), encoding="utf-8"
            )
            generate_probe(config, output, manifest)
            result = compare_probe(output, output)

            raw = output.read_bytes()
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            self.assertEqual(result.classification, "EXACT_MATCH")
            self.assertEqual(payload["journal_count"], 1)
            self.assertFalse(payload["production_allowed"])

    def test_comparator_classifies_only_known_jdl_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            candidate = root / "probe.csv"
            manifest = root / "manifest.json"
            config.write_text(
                json.dumps(self._config(), ensure_ascii=False), encoding="utf-8"
            )
            generate_probe(config, candidate, manifest)
            rows = list(csv.reader(candidate.read_text(encoding="cp932").splitlines()))
            header_index = next(i for i, row in enumerate(rows) if tuple(row) == HEADER)
            rows[header_index + 1][HEADER.index("伝番")] = "9001"
            rows[header_index + 1][HEADER.index("借方科目名称")] = "旅費交通"
            reexport = root / "reexport.csv"
            with reexport.open("w", encoding="cp932", newline="") as handle:
                csv.writer(handle, lineterminator="\r\n").writerows(rows)

            result = compare_probe(candidate, reexport)

            self.assertEqual(
                result.classification, "KNOWN_JDL_CANONICAL_NORMALIZATION"
            )
            rows[header_index + 1][HEADER.index("摘要")] = "CHANGED"
            with reexport.open("w", encoding="cp932", newline="") as handle:
                csv.writer(handle, lineterminator="\r\n").writerows(rows)
            self.assertEqual(
                compare_probe(candidate, reexport).classification,
                "UNEXPECTED_CHANGE",
            )

    def test_unknown_tax_or_overwrite_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = self._config()
            payload["cases"][0]["rows"][0]["借方税入力方法"] = "外税"
            config = root / "config.json"
            config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                generate_probe(config, root / "probe.csv", root / "manifest.json")

            payload = self._config()
            config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            generate_probe(config, root / "probe.csv", root / "manifest.json")
            with self.assertRaises(FileExistsError):
                generate_probe(config, root / "probe.csv", root / "manifest.json")

    def test_unbalanced_or_invalid_grouping_is_blocked(self) -> None:
        for field, value in (("貸方金額", "1099"), ("//識別フラグ", "1110")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload = self._config()
                payload["cases"][0]["rows"][0][field] = value
                config = root / "config.json"
                config.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    generate_probe(config, root / "probe.csv", root / "manifest.json")

    @staticmethod
    def _config() -> dict[str, object]:
        return {
            "NOT_FOR_PRODUCTION": True,
            "production_allowed": False,
            "target_master_identity_sha256": "synthetic-master",
            "context": {
                "product": "JDL IBEX 出納帳",
                "version": "35.5",
                "tax_processing": "課税",
                "accounting": "税抜",
                "taxation_method": "原則課税",
                "input_tax_credit_method": "一括比例配分方式",
            },
            "cases": [
                {
                    "pattern_id": "MF-TAX-PATTERN-01",
                    "occurrence_count": 1,
                    "planned_evidence_id": "EVID-MF-JDL-TAX-EXCLUDED-PROPORTIONAL-P01-001",
                    "rows": [
                        {
                            "//識別フラグ": "1111",
                            "日付": "20260420",
                            "借方科目": "8471",
                            "借方科目名称": "旅費交通費",
                            "借方科目正式名称": "旅費交通費",
                            "借方課区": "仕　入",
                            "借方税区": "10%",
                            "借方税入力方法": "内税",
                            "借方金額": "1100",
                            "借方消費税": "100",
                            "貸方科目": "3181",
                            "貸方科目名称": "未払金",
                            "貸方科目正式名称": "未払金",
                            "貸方金額": "1100",
                            "摘要": "MF-TAX-CTX-P01",
                        }
                    ],
                }
            ],
        }

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.profiles.jdl_official import (
    jdl_ibex_cashbook_official_journal_import_spec,
)
from accounting_converter.tools.jdl_mvp_blocker_probe import (
    DESCRIPTION_CASES,
    JdlMvpBlockerProbeError,
    build_private_plan,
    compare_description_roundtrip,
    generate_description_candidates,
    write_private_plan,
)


class JdlMvpBlockerProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "data" / "private"
        self.private.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_private_plan_anonymizes_unknown_tax_literals(self) -> None:
        source = self.private / "synthetic-mf.csv"
        literals = ("対象外仕入テスト", "非課税売上テスト")
        self._write_mf(source, literals)

        plan = build_private_plan(source)

        self.assertEqual(plan["unknown_tax_literal_count"], 2)
        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertTrue(all(value not in serialized for value in literals))
        self.assertTrue(
            all(
                item["candidate_status"]
                == "BLOCKED_PENDING_HUMAN_JDL_EXPORT"
                for item in plan["unknown_tax_cases"]
            )
        )
        self.assertEqual(
            plan["trade_partner_probe"]["classification"],
            "NO_CONFIRMED_JDL_CSV_FIELD",
        )

    def test_plan_and_result_templates_are_private_and_no_overwrite(self) -> None:
        source = self.private / "synthetic-mf.csv"
        self._write_mf(source, ("対象外仕入テスト", "非課税売上テスト"))
        destination = self.private / "probes" / "plan.json"

        write_private_plan(source, destination, self.private)

        self.assertTrue(destination.exists())
        self.assertTrue(destination.with_name("unknown_tax_1_result.json").exists())
        self.assertTrue(destination.with_name("trade_partner_result.json").exists())
        with self.assertRaisesRegex(JdlMvpBlockerProbeError, "output exists"):
            write_private_plan(source, destination, self.private)

    def test_description_candidates_and_strict_comparator(self) -> None:
        base = self.private / "base.csv"
        self._write_compound(base)
        manifest = self.private / "base.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "probe_case": "compound_1d3c",
                    "NOT_FOR_PRODUCTION": True,
                    "output_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

        candidates = generate_description_candidates(
            base, manifest, self.private / "descriptions", self.private
        )

        self.assertEqual(len(candidates), 3)
        for candidate in candidates:
            raw = candidate.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)
            result = compare_description_roundtrip(
                candidate, candidate.with_suffix(".manifest.json"), candidate
            )
            self.assertTrue(result["comparison_pass"])
            self.assertTrue(result["description_sequence_preserved"])
            self.assertFalse(result["production_allowed"])

        changed = self.private / "changed.csv"
        changed.write_bytes(candidates[1].read_bytes().replace(b"JDL-DESC-LATER", b"JDL-DESC-OTHER", 1))
        mismatch = compare_description_roundtrip(
            candidates[1], candidates[1].with_suffix(".manifest.json"), changed
        )
        self.assertFalse(mismatch["comparison_pass"])
        self.assertIn("摘要", mismatch["mismatch_field_categories"])

    def test_description_candidate_requires_verified_base_manifest(self) -> None:
        base = self.private / "base.csv"
        self._write_compound(base)
        manifest = self.private / "bad.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "probe_case": "compound_1d3c",
                    "NOT_FOR_PRODUCTION": True,
                    "output_sha256": "wrong",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(JdlMvpBlockerProbeError, "verified synthetic"):
            generate_description_candidates(
                base, manifest, self.private / "descriptions", self.private
            )

    @staticmethod
    def _write_mf(path: Path, literals: tuple[str, str]) -> None:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        writer.writerow(("1", "2026/11/20", "架空費用", "", "", "", literals[0], "", "100", "架空資産", "", "", "", "対象外", "", "100", "SYNTHETIC-A", "", ""))
        writer.writerow(("2", "2026/11/21", "架空資産", "", "", "", "対象外", "", "200", "架空収益", "", "", "", literals[1], "", "200", "SYNTHETIC-B", "", ""))
        path.write_bytes(stream.getvalue().encode("cp932"))

    @staticmethod
    def _write_compound(path: Path) -> None:
        header = jdl_ibex_cashbook_official_journal_import_spec().column_names
        pos = {name: index for index, name in enumerate(header)}
        rows = []
        for flag, debit, debit_amount, credit, credit_amount in (
            ("1110", "架空借方", "1000", "架空貸方A", "500"),
            ("1100", "", "", "架空貸方B", "300"),
            ("1101", "", "", "架空貸方C", "200"),
        ):
            row = [""] * 30
            row[pos["//識別フラグ"]] = flag
            row[pos["日付"]] = "20261114"
            row[pos["借方科目名称"]] = debit
            row[pos["借方金額"]] = debit_amount
            row[pos["貸方科目名称"]] = credit
            row[pos["貸方金額"]] = credit_amount
            row[pos["摘要"]] = "JDL-DESC-BASE"
            rows.append(row)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
        path.write_bytes(stream.getvalue().encode("cp932"))


if __name__ == "__main__":
    unittest.main()

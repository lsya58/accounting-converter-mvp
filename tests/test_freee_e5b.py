"""freee E5B第1回: observations bound to their Evidence ID, what stays blocked, and information loss.

Synthetic fixtures reuse the helpers of test_freee_journal_csv (observed column NAMES, invented values).
The private originals are only read, by the opt-in E5BRealEvidenceTest.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from collections import Counter
from pathlib import Path

from accounting_converter.adapters.input.freee import journal_csv as jc
from accounting_converter.adapters.input.freee.journal_csv import (
    E4_EVIDENCE_ID,
    E5B1_EVIDENCE_ID,
    E5B2A_EVIDENCE_ID,
    E5B2B_EVIDENCE_ID,
    NEW_CSV_97_HEADER,
    OLD_CSV_29_HEADER,
    UNOBSERVED_VALUES_KEY,
    FreeeJournalCsvParser,
    FreeeJournalVariant,
)
from accounting_converter.application.freee_diagnosis import diagnose_parse_result, journal_blockers
from accounting_converter.application.freee_other_export_diagnosis import (
    FREEE_JDL9_HEADER,
    diagnose_freee_jdl9,
    diagnose_freee_yayoi25,
)
from accounting_converter.application.freee_tax_lines import BLOCKER_UNIDENTIFIED
from accounting_converter.application.yayoi_credit_period import PERIOD_BLOCKER
from accounting_converter.domain.journal_rows import journal_physical_rows
from accounting_converter.ui import freee_trial_view as fv
from tests.test_freee_journal_csv import (
    SYNTHETIC_ID_1,
    SYNTHETIC_ID_2,
    SYNTHETIC_ID_3,
    _cp932,
    _new,
    _new_side,
    _old,
    parse,
    yayoi25,
)

UNOBSERVED = "SYSTEM_EVIDENCE:FREEE_VALUE_UNOBSERVED"
SHAPE = "SYSTEM_EVIDENCE:FREEE_JOURNAL_SHAPE_UNOBSERVED"
REGISTRATION = "SYSTEM_EVIDENCE:FREEE_REGISTRATION_SOURCE_UNOBSERVED"
ALWAYS = {"HUMAN:ACCOUNT_MAPPING", "HUMAN:TAX_MAPPING", "SYSTEM_EVIDENCE:FREEE_SOURCE_FORMAT_UNVERIFIED",
          "SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION"}

# E4 as registered on 2026-11-16 (must never shrink).
E4_VALUE_SETS = {
    "決算整理仕訳": {"0", "1"}, "期末日取引フラグ": {"0", "1"}, "内税・外税": {"内税"}, "税率": {"0", "10"},
    "軽減税率有無": {"0"}, "消費税経理処理方法": {"税込経理"}, "登録した方法": {"振替伝票"}, "承認状況": {"なし"},
    "承認状況(仕訳承認)": {"なし"}, "税区分": {"対象外", "課税売上10%", "課対仕入10%", "非課売上"},
}
BOTH, DEBIT_ONLY, CREDIT_ONLY = (True, True), (True, False), (False, True)


def e5b_like_rows():
    """The SHAPES and product vocabulary of E5B-01〜08; every account / amount / ID is invented."""
    manual = {"登録した方法": "手動", "振替伝票ID": "", "取引ID": "", "取引支払日": ""}
    return (
        # 2D1C, credit of row 2 blank
        _new("1", "8800000011", 1, 2, "2026-11-02", **_new_side("借方", "合成費用", "330", "課対仕入10%", "30", "10"),
             **_new_side("貸方", "合成現金", "550")),
        _new("1", "8800000011", 2, 2, "2026-11-02", **_new_side("借方", "合成費用B", "220", "課対仕入10%", "20", "10")),
        # 2D2C, no blank side, rows not balanced one by one
        _new("2", "8800000012", 1, 2, "2026-11-03", **_new_side("借方", "合成現金", "660"),
             **_new_side("貸方", "合成売上", "880", "課税売上10%", "80", "10")),
        _new("2", "8800000012", 2, 2, "2026-11-03", **_new_side("借方", "合成売掛金", "440"),
             **_new_side("貸方", "合成雑収入", "220", "課税売上10%", "20", "10")),
        # reduced 8 %: purchase and sales
        _new("3", "8800000013", 1, 1, "2026-11-04",
             **{**_new_side("借方", "合成仕入", "108", "課対仕入8%（軽）", "8", "8"), "借方軽減税率有無": "1"},
             **_new_side("貸方", "合成現金", "108")),
        _new("4", "8800000014", 1, 1, "2026-11-05", **_new_side("借方", "合成現金", "216"),
             **{**_new_side("貸方", "合成売上", "216", "課税売上8%（軽）", "16", "8"), "貸方軽減税率有無": "1"}),
        # 経過措置 80 % before 2026-10-01, 70 % from it
        _new("5", "8800000015", 1, 1, "2026-09-15", **_new_side("借方", "合成費用", "110", "課対仕入（控80）10%", "8", "10"),
             **_new_side("貸方", "合成現金", "110")),
        _new("6", "8800000016", 1, 1, "2026-10-15", **_new_side("借方", "合成費用", "110", "課対仕入（控70）10%", "7", "10"),
             **_new_side("貸方", "合成現金", "110")),
        # 取引の登録 on a 口座: 取引ID only, 口座 display name differs from its account name
        _new("7", "8800000017", 1, 1, "2026-11-06", **{**manual, "取引ID": "6600000017"},
             **_new_side("借方", "合成費用", "330", "課対仕入10%", "30", "10"),
             **{**_new_side("貸方", "合成口座", "330"), "貸方決算書表示名": "合成その他預金", "貸方備考": ""}),
        _new("8", "8800000018", 1, 1, "2026-11-07", **{**manual, "取引ID": "6600000018"},
             **{**_new_side("借方", "合成口座", "1100"), "借方決算書表示名": "合成その他預金", "借方備考": ""},
             **_new_side("貸方", "合成売上", "1100", "課税売上10%", "100", "10")),
    )


class EvidenceBindingTest(unittest.TestCase):
    def test_ids_are_distinct_and_e4_is_unchanged(self):
        self.assertEqual(E4_EVIDENCE_ID, "EVID-FREEE-JOURNAL-CSV-REAL-EXPORT-20261115-001")
        self.assertEqual(jc.EVIDENCE_ID, E4_EVIDENCE_ID)
        self.assertEqual(jc.OBSERVATION_EVIDENCE_IDS,
                         (E4_EVIDENCE_ID, E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID, E5B2B_EVIDENCE_ID))
        self.assertEqual({k: set(v) for k, v in jc.E4_OBSERVATION.value_sets.items()}, E4_VALUE_SETS)
        self.assertEqual(jc.E4_OBSERVATION.row_layouts, {(BOTH,), (BOTH, CREDIT_ONLY)})
        for key, values in E4_VALUE_SETS.items():  # the union never loses an E4 value
            self.assertTrue(values <= jc.OBSERVED_VALUE_SETS[key], key)
        self.assertTrue(jc.E4_OBSERVATION.row_layouts <= jc.OBSERVED_ROW_LAYOUTS)
        self.assertEqual(jc.E5B1_OBSERVATION.header_fingerprints, jc.E4_OBSERVATION.header_fingerprints)

    def test_new_values_are_bound_to_e5b1_only(self):
        # First seen in E5B第1回; seen again in E5B-2A (same journals re-exported). Never E4, never E5B-2B.
        for key, value in (("税区分", "課対仕入8%（軽）"), ("税区分", "課税売上8%（軽）"), ("税区分", "課対仕入（控80）10%"),
                           ("税区分", "課対仕入（控70）10%"), ("税率", "8"), ("軽減税率有無", "1"), ("登録した方法", "手動")):
            with self.subTest(value=value):
                self.assertEqual(jc.evidence_for_value(key, value), (E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID))
        self.assertEqual(jc.evidence_for_value("税区分", "課対仕入10%"),
                         (E4_EVIDENCE_ID, E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID, E5B2B_EVIDENCE_ID))
        self.assertEqual(jc.evidence_for_value("消費税経理処理方法", "税抜経理"), (E5B2A_EVIDENCE_ID, E5B2B_EVIDENCE_ID))
        self.assertEqual(jc.evidence_for_value("税区分", "非課売上"), (E4_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_value("決算整理仕訳", "1"), (E4_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_column(FreeeJournalVariant.NEW_CSV, "取引ID"), (E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID))
        self.assertEqual(jc.evidence_for_column(FreeeJournalVariant.NEW_CSV, "借方品目"), (E4_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_layout((BOTH, DEBIT_ONLY)), (E5B1_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_layout((BOTH, BOTH)), (E5B1_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_layout((BOTH, CREDIT_ONLY)), (E4_EVIDENCE_ID,))
        self.assertEqual(jc.evidence_for_registration_source(("手動", False, True)), (E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID))
        for value in ("外税", "課対仕入（控50）10%", "課対仕入8%(軽)", "5", "2", "自動で経理"):
            for key in ("内税・外税", "消費税経理処理方法", "税区分", "税率", "軽減税率有無", "登録した方法"):
                self.assertEqual(jc.evidence_for_value(key, value), (), (key, value))
        self.assertEqual(jc.evidence_for_column(FreeeJournalVariant.NEW_CSV, "口座振替ID"), ())

    def test_entries_and_report_name_both_evidence_ids(self):
        result = parse(NEW_CSV_97_HEADER, e5b_like_rows())
        ids = (E4_EVIDENCE_ID, E5B1_EVIDENCE_ID, E5B2A_EVIDENCE_ID, E5B2B_EVIDENCE_ID)
        self.assertEqual(result.entries[0].metadata["evidence_ids"], ids)
        report = diagnose_parse_result(result).to_dict()
        self.assertEqual(report["evidence_ids"], list(ids))
        self.assertEqual(report["formal_ready"], 0)


class E5BObservedTest(unittest.TestCase):
    def setUp(self):
        self.result = parse(NEW_CSV_97_HEADER, e5b_like_rows())
        self.diagnosis = diagnose_parse_result(self.result)

    def test_observed_values_and_shapes_no_longer_block_as_unobserved(self):
        self.assertEqual(self.result.issues, ())
        self.assertEqual((len(self.result.entries), self.result.accepted_rows), (8, 10))
        for entry in self.result.entries:
            with self.subTest(entry=entry.id):
                blockers = set(self.diagnosis.journal_blockers[entry.id])
                self.assertEqual(entry.metadata[UNOBSERVED_VALUES_KEY], ())
                self.assertFalse({UNOBSERVED, SHAPE, REGISTRATION, PERIOD_BLOCKER} & blockers)
                self.assertTrue(ALWAYS <= blockers)  # Human mappings and the direction guard stay
        self.assertEqual(dict(self.diagnosis.shapes), {(1, 1, 1): 6, (2, 1, 2): 1, (2, 2, 2): 1})

    def test_bank_account_display_name_stays_a_human_decision(self):
        manual = [e for e in self.result.entries if e.metadata.get(jc.REGISTRATION_METHOD_KEY) == "手動"]
        self.assertEqual(len(manual), 2)
        for entry in manual:
            self.assertEqual(entry.metadata[jc.REGISTRATION_SOURCE_KEY], ("手動", False, True))
            self.assertIn("HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS", self.diagnosis.journal_blockers[entry.id])
            self.assertIn("合成口座", {line.account for line in entry.lines})  # never replaced by the display name

    def test_never_ready(self):
        self.assertEqual(self.diagnosis.formal_ready, 0)
        self.assertFalse(self.diagnosis.ready_allowed)
        self.assertTrue(all(self.diagnosis.journal_blockers.values()))
        # Even an unblocked journal would not count while the direction is not PRODUCTION.
        self.diagnosis.journal_blockers = {key: () for key in self.diagnosis.journal_blockers}
        self.assertEqual(self.diagnosis.formal_ready, 0)


class StillBlockedTest(unittest.TestCase):
    def _blockers(self, rows, header=NEW_CSV_97_HEADER):
        result = parse(header, rows)
        self.assertEqual(result.accepted_rows, len(rows))
        return set(diagnose_parse_result(result).journal_blockers[result.entries[0].id])

    def test_unobserved_values_still_block(self):
        base = e5b_like_rows()[4]  # reduced 8 % purchase
        index = NEW_CSV_97_HEADER.index
        for column, value in (("借方内税・外税", "外税"), ("借方税区分", "課対仕入8%(軽)"),
                              ("借方税区分", "課対仕入（控50）10%"), ("借方税率", "5"), ("借方軽減税率有無", "2"),
                              ("登録した方法", "自動で経理"), ("口座振替ID", "5500000001"), ("借方部門", "合成部門")):
            with self.subTest(column=column, value=value):
                row = list(base)
                row[index(column)] = value
                self.assertIn(UNOBSERVED, self._blockers([tuple(row)]))
        # 税抜経理 is observed since E5B-2A, but a 税抜経理 journal without its tax row still blocks.
        row = list(base)
        row[index("消費税経理処理方法")] = "税抜経理"
        self.assertIn(BLOCKER_UNIDENTIFIED, self._blockers([tuple(row)]))

    def test_old_csv_unobserved_tax_category_still_blocks(self):
        row = _old("1", "50001", "2026/11/04", 借方勘定科目="合成費用", 借方金額="110", 借方税区分="課対仕入（控50）10%",
                   貸方勘定科目="合成現金", 貸方金額="110", 貸方税区分="対象外", 摘要="合成")
        self.assertIn(UNOBSERVED, self._blockers([row], OLD_CSV_29_HEADER))

    def test_unobserved_registration_sources_block(self):
        index = NEW_CSV_97_HEADER.index
        manual = e5b_like_rows()[8]
        voucher = e5b_like_rows()[4]
        cases = {
            "手動 with 振替伝票ID": (manual, {"振替伝票ID": "7700000001"}),
            "手動 without any ID": (manual, {"取引ID": ""}),
            "振替伝票 with 取引ID": (voucher, {"取引ID": "6600000001"}),
            "振替伝票 without 振替伝票ID": (voucher, {"振替伝票ID": ""}),
        }
        for name, (base, changes) in cases.items():
            with self.subTest(name):
                row = list(base)
                for column, value in changes.items():
                    row[index(column)] = value
                self.assertIn(REGISTRATION, self._blockers([tuple(row)]))

    def test_transitional_credit_period_reuses_the_existing_rule(self):
        index = NEW_CSV_97_HEADER.index
        for category, day, blocked in (("課対仕入（控80）10%", "2026-09-30", False), ("課対仕入（控80）10%", "2026-10-01", True),
                                       ("課対仕入（控70）10%", "2026-10-01", False), ("課対仕入（控70）10%", "2026-09-30", True),
                                       ("課対仕入（控80）10%", "2023-09-30", True)):
            with self.subTest(category=category, day=day):
                row = list(e5b_like_rows()[6])
                row[index("借方税区分")] = category
                row[index("取引日")] = row[index("取引支払日")] = day
                self.assertEqual(PERIOD_BLOCKER in self._blockers([tuple(row)]), blocked)
        old = _old("1", "50001", "2026/10/15", 借方勘定科目="合成費用", 借方金額="110", 借方税区分="課対仕入（控80）10%",
                   貸方勘定科目="合成現金", 貸方金額="110", 貸方税区分="対象外", 摘要="合成")
        self.assertIn(PERIOD_BLOCKER, self._blockers([old], OLD_CSV_29_HEADER))

    def test_unknown_header_still_rejected_or_blocked(self):
        rows = e5b_like_rows()[:1]
        extra = parse((*NEW_CSV_97_HEADER, "合成の新列"), [(*rows[0], "")])
        self.assertFalse(extra.header.observed)
        blockers = diagnose_parse_result(extra).journal_blockers
        self.assertTrue(all("SYSTEM_EVIDENCE:FREEE_HEADER_NOT_OBSERVED" in codes for codes in blockers.values()))
        unknown = FreeeJournalCsvParser().parse_bytes("合成A,合成B\n1,2\n".encode(), "synthetic.csv")
        self.assertFalse(unknown.file_readable)
        self.assertIn(jc.FreeeIssue.VARIANT_UNKNOWN, {issue.code for issue in unknown.issues})

    def test_new_reason_codes_have_labels(self):
        for code in (REGISTRATION, PERIOD_BLOCKER):
            self.assertIn(code, fv.REASON_LABELS)

    def test_journal_blockers_does_not_need_new_csv_metadata(self):
        # 旧CSV entries carry no registration source: nothing is assumed for them.
        row = _old("1", "50001", "2026/11/04", 借方勘定科目="合成費用", 借方金額="110", 借方税区分="課対仕入10%",
                   貸方勘定科目="合成現金", 貸方金額="110", 貸方税区分="対象外", 摘要="合成")
        entry = parse(OLD_CSV_29_HEADER, [row]).entries[0]
        self.assertNotIn(jc.REGISTRATION_SOURCE_KEY, entry.metadata)
        self.assertNotIn(REGISTRATION, journal_blockers(entry, header_verified=False, ready_allowed=False,
                                                        has_description=True, header_observed=True))


class OtherExportInformationLossTest(unittest.TestCase):
    def test_jdl9_blank_tax_cells_are_lost_information_not_out_of_scope(self):
        rows = [
            ["＜仕訳一覧＞"], list(FREEE_JDL9_HEADER),
            ["20260915", "8001", "8002", "", "0009", "110", "合成", "", ""],
            ["20261102", "8003", "8002", "", "0009", "330", "合成", "31", "10"],
            ["20261103", "8002", "8004", "0009", "", "220", "合成", "0", "0"],
            ["＜仕訳一覧終了＞"],
        ]
        report = diagnose_freee_jdl9(_cp932(rows)).to_dict()
        self.assertTrue(report["readable"])
        self.assertEqual(report["information_loss"]["JDL9_TAX_CELLS_BLANK"]["count"], 1)
        self.assertEqual(report["values"]["課区/税区"], {"/": 1, "31/10": 1, "0/0": 1})  # blank kept blank
        self.assertIn("TRANSITIONAL_CREDIT_TAX_CELLS_BLANK", report["differences"])
        self.assertEqual(report["formal_ready"], 0)
        partial = [*rows[:2], ["20261102", "8003", "8002", "", "", "330", "合成", "31", ""], rows[-1]]
        self.assertEqual(diagnose_freee_jdl9(_cp932(partial)).issues["TAX_CELL_PAIR_PARTIAL"], 1)
        self.assertNotIn("合成", json.dumps(report, ensure_ascii=False))

    def test_yayoi25_blank_tax_category_is_lost_not_untaxed(self):
        rows = [
            yayoi25("2000", day="2026/09/15", debit=("合成費用", "", "", "110", "")),
            yayoi25("2000", day="2026/11/02", debit=("合成費用", "", "課対仕入10%", "330", "")),
        ]
        report = diagnose_freee_yayoi25(_cp932(rows)).to_dict()
        self.assertTrue(report["readable"])
        self.assertEqual(report["information_loss"]["YAYOI25_TAX_CATEGORY_BLANK"]["count"], 1)
        self.assertEqual(report["counts"]["taxed_sides"], 1)
        self.assertEqual(report["values"]["借方税区分"], {"(空欄)": 1, "課対仕入10%": 1})
        self.assertIn("TRANSITIONAL_CREDIT_TAX_CATEGORY_BLANK", report["differences"])

    def test_no_loss_reported_when_nothing_is_blank(self):
        rows = [yayoi25("2000", debit=("合成費用", "", "課対仕入10%", "330", ""))]
        self.assertEqual(diagnose_freee_yayoi25(_cp932(rows)).to_dict()["information_loss"], {})


# ----------------------------------------------------------------------------- real Evidence (opt-in, read-only)

E5B1_DIR = Path(__file__).resolve().parents[1] / "data" / "private" / "freee_e5b_20261122" / "before_tax_exclusive"
E5B1_FILES = {
    "new": ("仕訳帳（新）CSV （2026年09月~2026年11月）.csv",
            "b05c095a1eb00832a04559e9efeacdb43ad51bde0ab961b5fadaaf60d50e60c7"),
    "old": ("仕訳帳（旧）CSV （2026年09月~2026年11月）.csv",
            "a118c4af52a54cebbfeac0902b1f4724574081c1cc403300c388601df353429b"),
    "jdl9": ("仕訳帳 JDLインポート形式 （2026年09月~2026年11月）.csv",
             "33579bd3e88e58bc68a085b99e6f34ab526ba542facd907799613bd18e8f8b2e"),
    "yayoi25": ("仕訳帳 弥生会計インポート形式 （2026年09月~2026年11月）.csv",
                "3978aaacfec767f71829d75b3c46b34e540bca33189f6595f9b31f2ada59d0c5"),
}


@unittest.skipUnless(all((E5B1_DIR / name).is_file() for name, _ in E5B1_FILES.values()),
                     "private freee E5B Evidence not present")
class E5BRealEvidenceTest(unittest.TestCase):
    """Reads the private originals (bytes only) and checks the registered observation against them."""

    def setUp(self):
        self.raw = {}
        for key, (name, digest) in E5B1_FILES.items():
            self.raw[key] = (E5B1_DIR / name).read_bytes()
            self.assertEqual(hashlib.sha256(self.raw[key]).hexdigest(), digest, name)

    def _parse(self, key):
        return FreeeJournalCsvParser().parse_bytes(self.raw[key], E5B1_FILES[key][0])

    def test_registered_observation_equals_the_files(self):
        observation = jc.E5B1_OBSERVATION
        seen_values: dict[str, set[str]] = {}
        for key, variant in (("new", FreeeJournalVariant.NEW_CSV), ("old", FreeeJournalVariant.OLD_CSV)):
            result = self._parse(key)
            self.assertIn(result.header.fingerprint, observation.header_fingerprints)
            columns = {name for entry in result.entries for name, _ in entry.metadata[jc.NONBLANK_COLUMNS_KEY]}
            self.assertEqual(columns, observation.columns_with_values[variant], key)
            rows = list(csv.reader(io.StringIO(self.raw[key].decode("utf-8"), newline="")))
            for record in (dict(zip(rows[0], row)) for row in rows[1:]):
                for name, value in record.items():
                    base = name[2:] if name[:2] in {"借方", "貸方"} else name
                    if value and base in observation.value_sets:
                        seen_values.setdefault(base, set()).add(value)
        self.assertEqual({k: set(v) for k, v in observation.value_sets.items()}, seen_values)
        result = self._parse("new")
        layouts = {tuple((r.debit is not None, r.credit is not None) for r in journal_physical_rows(e))
                   for e in result.entries}
        self.assertEqual(layouts, set(observation.row_layouts))
        self.assertEqual({e.metadata[jc.REGISTRATION_SOURCE_KEY] for e in result.entries},
                         set(observation.registration_sources))

    def test_diagnosis_of_the_real_files(self):
        for key in ("new", "old"):
            with self.subTest(key):
                result = self._parse(key)
                self.assertEqual((result.data_rows, result.accepted_rows, len(result.entries), result.issues),
                                 (10, 10, 8, ()))
                diagnosis = diagnose_parse_result(result)
                self.assertEqual(diagnosis.formal_ready, 0)
                blockers = Counter(code for codes in diagnosis.journal_blockers.values() for code in codes)
                for code in (UNOBSERVED, SHAPE, REGISTRATION, PERIOD_BLOCKER):
                    self.assertNotIn(code, blockers)
                self.assertEqual(blockers["HUMAN:ACCOUNT_MAPPING"], 8)
                self.assertEqual(blockers["HUMAN:TAX_MAPPING"], 8)
                self.assertEqual(blockers["SYSTEM_IMPLEMENTATION:DIRECTION_NOT_PRODUCTION"], 8)
                if key == "new":
                    self.assertEqual(blockers["HUMAN:ACCOUNT_DISPLAY_NAME_DIFFERS"], 2)
                    self.assertEqual(diagnosis.tax_inclusion_raw, {"内税": 19})  # 外税 not acquired
                text = json.dumps(diagnosis.to_dict(), ensure_ascii=False)
                self.assertNotIn("@", text)

    def test_other_exports_lose_the_transitional_tax_category(self):
        jdl = diagnose_freee_jdl9(self.raw["jdl9"])
        self.assertTrue(jdl.readable)
        self.assertEqual(jdl.information_loss, Counter({"JDL9_TAX_CELLS_BLANK": 2}))
        self.assertEqual(jdl.values["課区/税区"]["/"], 2)
        self.assertEqual(jdl.counts["data_rows"], 13)
        yayoi = diagnose_freee_yayoi25(self.raw["yayoi25"])
        self.assertTrue(yayoi.readable)
        self.assertEqual(yayoi.information_loss, Counter({"YAYOI25_TAX_CATEGORY_BLANK": 2}))
        self.assertEqual(yayoi.counts["data_rows"], 10)


if __name__ == "__main__":
    unittest.main()

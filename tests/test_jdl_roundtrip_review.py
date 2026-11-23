"""JDL round-trip check for the screen (Phase 1, 弥生インポート形式): the existing verdict, never upgraded.

Synthetic company (tests.test_yayoi_import_format, invented values). The private company B Evidence is read only by
the opt-in CompanyBEvidenceTest (store copied to a temporary folder; nothing in data/private is written).
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from accounting_converter.application import jdl_description_trailing_space as trailing
from accounting_converter.application import jdl_roundtrip_review as rr
from accounting_converter.application.yayoi_jdl_workflow import YayoiJdlWorkflow, audit_path_for
from accounting_converter.tools import yayoi_roundtrip_check as cli
from accounting_converter.ui import roundtrip_view as rv
from tests import test_yayoi_import_format as import_format_tests
from tests.test_yayoi_import_format import (
    IMPORT, OUTSIDE, PURCHASE, REPORT, YAYOI, Company, floor_context, journals, write_import,
)

COMPANY = "company-o"
_ALLOWED = None


def setUpModule():
    """Synthetic companies stand in for company B (the production allowlist is only company B)."""
    global _ALLOWED
    _ALLOWED = mock.patch.object(rr, "EVIDENCE_COMPANY_IDS", frozenset({COMPANY, "company-other", "company-yayoi-act"}))
    _ALLOWED.start()


def tearDownModule():
    _ALLOWED.stop()


def rows_of(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_bytes().decode("cp932"), newline="")))


def write_rows(path: Path, rows, encoding="cp932") -> Path:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerows(rows)
    path.write_bytes(buffer.getvalue().encode(encoding))
    return path


def listing(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class Env:
    """A 弥生インポート形式 company whose output has an audit record (部門・生成元 kept outside JDL), like company B."""

    def __init__(self, root: Path, source_rows=None):
        self.root = root
        if source_rows is None:
            self.company = import_format_tests.NonRetainedInformationTest()._company(root)
        else:
            self.company = Company(root, COMPANY, write_import(root, source_rows), IMPORT, floor_context())
            self.company.confirm_all()
        import_format_tests.NonRetainedInformationTest()._confirm_fields(self.company, ["生成元", "部門"])
        self.resolved = self.company.resolved()
        self.candidate = root / "out" / "jdl.csv"
        self.candidate.parent.mkdir()
        prepared = YayoiJdlWorkflow().prepare(input_path=self.company.source, output_path=self.candidate,
                                              profile=self.resolved.profile, context=self.resolved.context,
                                              company_setting_validated=True)
        result = YayoiJdlWorkflow().execute(prepared)
        assert result.status.value == "SUCCESS", [v.rule_id for v in result.validation_results]

    def reexport(self, change=None, name="reexport.csv", encoding="cp932") -> Path:
        """JDL's re-export: the voucher numbers JDL assigns (a known canonical normalization), then `change`."""
        rows = rows_of(self.candidate)
        voucher = 0
        for data in rows[1:]:
            if data[0] in {"1111", "1110"}:
                voucher += 1
            data[1] = str(voucher)
        if change is not None:
            change(rows)
        return write_rows(self.root / name, rows, encoding)

    def review(self, reexport: Path, candidate: Path | None = None, company_id=COMPANY, resolved=None):
        return rr.review(resolved or self.company.companies.resolve(company_id), company_id, self.company.source,
                         candidate or self.candidate, reexport)


class ScopeTest(unittest.TestCase):
    def test_an_import_format_company_without_evidence_is_not_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(Path(directory))
            self.assertEqual(rr.route_of(env.company.companies.resolve(COMPANY).profile, COMPANY), rr.ROUTE_YAYOI_IMPORT)
            with mock.patch.object(rr, "EVIDENCE_COMPANY_IDS", frozenset({"company-yayoi-act"})):
                result = env.review(env.reexport())
                self.assertEqual(result.state, rr.NOT_RUN)
                self.assertEqual(result.reasons, ("ROUTE_COMPANY_NOT_IN_PHASE_1",))
                self.assertIsNone(rr.route_of(env.company.companies.resolve(COMPANY).profile, COMPANY))
        self.assertEqual(rr.EVIDENCE_COMPANY_IDS, frozenset({COMPANY, "company-other", "company-yayoi-act"}))


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = Env(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_pass_is_the_existing_verdict_and_counts(self):
        reexport = self.env.reexport()
        before = listing(self.env.root)
        review = self.env.review(reexport)
        self.assertEqual(listing(self.env.root), before)                    # read-only: nothing written or changed
        self.assertEqual(review.state, rr.PASS)
        self.assertTrue(review.is_pass)
        existing = cli.run_check(self.env.company.source, self.env.resolved.profile, self.env.resolved.context,
                                 COMPANY, self.env.candidate, reexport)
        self.assertEqual(review.existing_verdict, existing["verdict"])      # CLI and screen: the same judgement
        self.assertEqual(review.verdict_information_outside_jdl, "PASS")
        self.assertEqual(review.counts["source"], {"journals": 3, "physical_rows": 4})
        self.assertEqual(review.reexport["journals"], [3, 3])
        self.assertEqual(review.reexport["physical_rows"], [4, 4])
        self.assertEqual((review.reexport["missing_rows"], review.reexport["extra_rows"],
                          review.reexport["unexplained_differences"]), (0, 0, 0))
        self.assertGreater(review.reexport["canonical_normalizations"], 0)
        self.assertEqual(review.audit_found_by, "NAME")
        self.assertEqual(review.route, rr.ROUTE_YAYOI_IMPORT)
        self.assertFalse(review.ready_only)

    def _fail(self, change, category):
        review = self.env.review(self.env.reexport(change))
        self.assertEqual(review.state, rr.FAIL, review)
        self.assertFalse(review.is_pass)
        self.assertEqual(review.existing_verdict, "FAIL")
        self.assertIn(category, {item["category"] for item in review.first_failures})
        self.assertGreaterEqual(review.reexport["unexplained_differences"], 1)
        return review

    def test_amount_tax_and_account_differences_fail(self):
        # Balanced changes, like a real JDL re-export (an unbalanced file is refused before comparing).
        def amount(rows):
            rows[2][11] = rows[2][21] = str(int(rows[2][11]) + 1)

        def tax(rows):
            rows[2][22] = str(int(rows[2][22]) + 1)

        def account(rows):
            rows[2][3] = "1311"

        self._fail(amount, "AMOUNT")
        self._fail(tax, "TAX_AMOUNT")
        self._fail(account, "ACCOUNT")

    def test_missing_and_extra_rows_fail_with_full_counts(self):
        review = self._fail(lambda rows: rows.__delitem__(slice(-2, None)), "MISSING_ROW")  # the last journal (2 rows)
        self.assertEqual(review.reexport["missing_rows"], 2)
        # A journal missing in the middle shifts every later row: the first 20 details are then column differences,
        # while the full count still says one row is missing (the screen explains the positional comparison).
        shifted = self.env.review(self.env.reexport(lambda rows: rows.pop(2), name="shifted.csv"))
        self.assertEqual((shifted.state, shifted.reexport["missing_rows"]), (rr.FAIL, 1))
        review = self._fail(lambda rows: rows.append(list(rows[2])), "EXTRA_ROW")    # the same journal twice
        self.assertEqual(review.reexport["extra_rows"], 1)
        self.assertIn("余分", rv.CATEGORY_TEXT["EXTRA_ROW"])

    def test_source_to_candidate_difference_fails(self):
        reexport = self.env.reexport()
        changed = self.env.root / "out" / "changed.csv"
        rows = rows_of(self.env.candidate)
        rows[1][11] = rows[1][21] = str(int(rows[1][11]) + 1)          # balanced, but not what the source says
        write_rows(changed, rows)
        shutil.copyfile(audit_path_for(self.env.candidate), audit_path_for(changed))
        def same_change(rows_):
            rows_[1][11] = rows_[1][21] = rows[1][11]

        review = self.env.review(self.env.reexport(same_change, name="re2.csv"), candidate=changed)
        self.assertEqual(review.state, rr.FAIL)
        lines = review.source_vs_candidate["lines_account_subaccount_amount_tax_date"]
        self.assertGreaterEqual(lines["missing"], 1)
        self.assertIn("INFORMATION_OUTSIDE_JDL_FAIL", review.reasons)          # the audit names the other CSV
        self.assertNotEqual(self.env.review(reexport).state, rr.FAIL)

    def test_unreadable_missing_and_wrong_header_are_read_errors(self):
        utf8 = self.env.reexport(name="utf8.csv", encoding="utf-8")
        review = self.env.review(utf8)
        self.assertEqual(review.state, rr.READ_ERROR)
        self.assertTrue({"REEXPORT_NOT_COMPARABLE", "CHECK_RAISED"} & set(review.reasons), review.reasons)
        header = self.env.reexport(lambda rows: rows[0].__setitem__(3, "借方コード"), name="header.csv")
        self.assertEqual(self.env.review(header).state, rr.READ_ERROR)
        missing = self.env.review(self.env.root / "nothing.csv")
        self.assertEqual((missing.state, missing.reasons), (rr.READ_ERROR, ("FILE_NOT_FOUND:reexport",)))
        for review in (self.env.review(utf8), missing):
            self.assertFalse(review.is_pass)
            self.assertEqual(rv.headline(review)[0], "error")

    def test_any_exception_is_a_read_error_never_a_pass(self):
        with mock.patch.object(cli, "run_check", side_effect=RuntimeError("synthetic 振込手数料 details")):
            review = self.env.review(self.env.reexport())
        self.assertEqual((review.state, review.error_type), (rr.READ_ERROR, "RuntimeError"))
        self.assertNotIn("振込手数料", json.dumps(review.summary(), ensure_ascii=False))   # the message is not kept

    def test_the_candidate_as_its_own_reexport_is_never_compared(self):
        copy = self.env.root / "copy.csv"
        shutil.copyfile(self.env.candidate, copy)
        # The command line alone would say PASS here (no JDL involved); the screen refuses before comparing.
        self.assertEqual(cli.check(self.env.company.source, self.env.resolved.profile, self.env.resolved.context,
                                   self.env.candidate, copy)["verdict"], "PASS")
        for reexport in (copy, self.env.candidate):
            review = self.env.review(reexport)
            self.assertEqual(review.state, rr.NOT_RUN)
            self.assertFalse(review.is_pass)
        self.assertIn("REEXPORT_IDENTICAL_TO_CANDIDATE", self.env.review(copy).reasons)
        self.assertIn("SAME_FILE_SELECTED_TWICE", self.env.review(self.env.candidate).reasons)

    def test_files_changed_during_the_check_give_no_verdict(self):
        reexport = self.env.reexport()
        original = cli.run_check

        def touching(*args, **kwargs):
            result = original(*args, **kwargs)
            reexport.write_bytes(reexport.read_bytes() + b"\r\n")
            return result

        with mock.patch.object(cli, "run_check", side_effect=touching):
            review = self.env.review(reexport)
        self.assertEqual((review.state, review.reasons), (rr.READ_ERROR, ("FILES_CHANGED_DURING_CHECK",)))

    def test_audit_record_must_stay_next_to_the_csv(self):
        moved = self.env.root / "elsewhere"
        moved.mkdir()
        candidate = moved / "jdl.csv"
        shutil.copyfile(self.env.candidate, candidate)
        review = self.env.review(self.env.reexport(), candidate=candidate)
        self.assertEqual(review.state, rr.FAIL)
        self.assertIn("AUDIT_RECORD_NOT_FOUND_NEXT_TO_CSV", review.reasons)
        self.assertIn(".audit.json", " ".join(rv.reason_lines(review)))


class BindingTest(unittest.TestCase):
    def test_another_company_unsupported_route_and_ready_only_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(Path(directory))
            reexport = env.reexport()
            # Another company with other mappings: its source / setting do not produce this CSV.
            other_root = Path(directory) / "other"
            other_root.mkdir()
            other = Company(other_root, "company-other", write_import(other_root, journals(purchase_amount=2200,
                                                                                        purchase_tax=200)),
                            IMPORT, floor_context())
            other.confirm_all()
            review = rr.review(other.resolved(), "company-other", other.source, env.candidate, reexport)
            self.assertEqual(review.state, rr.FAIL)
            # The setting resolved for another id than the one asked for: refused.
            mismatch = rr.review(env.company.resolved(), "company-other", env.company.source, env.candidate, reexport)
            self.assertEqual((mismatch.state, mismatch.reasons), (rr.NOT_RUN, ("COMPANY_SETTING_MISMATCH",)))
            # A 仕訳日記帳 (company A form) company: not in Phase 1.
            report_root = Path(directory) / "report"
            report_root.mkdir()
            from tests.test_yayoi_journal_report_parser import build, detail, write

            report_source = write(report_root, build([detail(
                "令和08年05月10日", 1, debit=(YAYOI["fee"], "", PURCHASE, 1100, 100),
                credit=(YAYOI["bank"], "", OUTSIDE, 1100, 0), description="合成")]))
            report = Company(report_root, "company-report", report_source, REPORT, floor_context())
            unsupported = rr.review(report.resolved(), "company-report", report.source, env.candidate, reexport)
            self.assertEqual((unsupported.state, unsupported.reasons),
                             (rr.NOT_RUN, ("ROUTE_YAYOI_JOURNAL_REPORT_NOT_IN_PHASE_1",)))
            # A READY-only manifest next to the CSV that does not belong to it: verified first, never compared.
            (env.candidate.parent / "jdl.csv.ready_only.json").write_text("{}", encoding="utf-8")
            ready_only = env.review(reexport)
            self.assertTrue(ready_only.ready_only)
            self.assertEqual((ready_only.state, ready_only.reasons), (rr.FAIL, ("READY_ONLY_FILES_DO_NOT_MATCH",)))


class PendingTest(unittest.TestCase):
    def test_trailing_space_loss_without_acceptance_is_pending_not_pass(self):
        """The 弥生インポート形式 reader strips cell spaces, so company B never meets this loss. The shared state logic is
        checked on a synthetic 仕訳日記帳 company (whose 摘要 keeps a trailing space), with the Phase 1 route limit and
        the Evidence scope patched for that synthetic company only; the verdict itself is the real check's."""
        from tests.test_yayoi_journal_report_parser import build, detail, write

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write(root, build([detail("令和08年05月10日", 1, debit=(YAYOI["fee"], "", PURCHASE, 1100, 100),
                                               credit=(YAYOI["bank"], "口座A", OUTSIDE, 1100, None),
                                               description="振込手数料 ")]))
            company = Company(root, "company-r", source, REPORT, floor_context())
            company.confirm_all()
            resolved = company.resolved()
            candidate = root / "jdl.csv"
            YayoiJdlWorkflow().execute(YayoiJdlWorkflow().prepare(
                input_path=source, output_path=candidate, profile=resolved.profile, context=resolved.context,
                company_setting_validated=True))
            rows = rows_of(candidate)
            self.assertEqual(rows[1][23], "振込手数料 ")
            rows[1][1] = "1"
            rows[1][23] = "振込手数料"                                       # JDL removed the trailing space
            reexport = write_rows(root / "reexport.csv", rows)
            self.assertEqual(rr.review(resolved, "company-r", source, candidate, reexport).reasons,
                             ("ROUTE_YAYOI_JOURNAL_REPORT_NOT_IN_PHASE_1",))   # Phase 1: not offered for it
            with mock.patch.object(rr, "route_of", return_value=rr.ROUTE_YAYOI_IMPORT):
                outside = rr.review(resolved, "company-r", source, candidate, reexport)
                with mock.patch.object(trailing, "scope_problems", return_value=()), \
                        mock.patch.object(trailing, "applicable_suffixes", return_value=frozenset({" "})):
                    review = rr.review(resolved, "company-r", source, candidate, reexport)
                    existing = cli.run_check(source, resolved.profile, resolved.context, "company-r", candidate,
                                             reexport)
            self.assertEqual(outside.state, rr.FAIL)                         # outside the Evidence: unexplained
            self.assertEqual(existing["verdict"], "NORMALIZATION_ACCEPTANCE_PENDING")
            self.assertEqual(review.state, rr.PENDING)
            self.assertFalse(review.is_pass)
            self.assertEqual(review.trailing_space["rows"], 1)
            self.assertEqual(review.trailing_space["acceptance_state"], trailing.NOT_RECORDED)
            level, badge, words, text = rv.headline(review)
            self.assertEqual((level, words), ("warning", "PENDING"))
            self.assertIn("合格ではありません", text)
            self.assertNotIn("振込手数料", json.dumps(review.summary(), ensure_ascii=False))  # descriptions stay out

    def test_unknown_or_unverified_verdicts_are_never_upgraded(self):
        self.assertEqual(rr._state_of({"verdict": "SOMETHING_NEW"})[0], rr.FAIL)
        self.assertEqual(rr._state_of({"verdict": "SOURCE_TO_CSV_PASS_REEXPORT_PENDING"})[0], rr.NOT_RUN)
        self.assertEqual(rr._state_of({"verdict": "PASS_WITH_ACCEPTED_NORMALIZATION"})[0], rr.FAIL)
        accepted = {"verdict": "PASS_WITH_ACCEPTED_NORMALIZATION",
                    "description_trailing_space_loss": {"acceptance": {"state": trailing.ACCEPTED}}}
        self.assertEqual(rr._state_of(accepted)[0], rr.PASS_WITH_ACCEPTED_NORMALIZATION)
        self.assertEqual(rr._state_of({"verdict": "PASS", "candidate_vs_reexport": {"error": "ValueError"}})[0],
                         rr.READ_ERROR)


class SummaryAndViewTest(unittest.TestCase):
    def test_summary_has_no_customer_values_and_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(Path(directory))
            def change(rows):
                rows[2][11] = rows[2][21] = "9999"

            review = env.review(env.reexport(change))
            target = Path(directory) / "summary.json"
            rr.save_summary(review, target)
            text = target.read_text(encoding="utf-8")
            for value in ("振込手数料", "文具", "手数料", "普通預金", "銀行A", "部門A", "取込", *YAYOI.values(), "9999"):
                self.assertNotIn(value, text)
            payload = json.loads(text)
            self.assertEqual(payload["schema"], rr.SUMMARY_SCHEMA)
            self.assertEqual(payload["state"], rr.FAIL)
            self.assertIn("最初の20件", payload["first_failures_note"])
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                rr.save_summary(review, target)
            self.assertEqual(target.read_bytes(), before)

    def test_view_labels_the_sample_and_every_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(Path(directory))

            def many(rows):
                rows[2][11] = rows[2][21] = "9999"
                rows[2][3] = "1311"
                rows[1][23] = rows[2][23] = "合成の変更"

            review = env.review(env.reexport(many))
            heading = rv.failures_heading(review)
            self.assertIn("最初の20件", heading)
            self.assertIn(f"全{review.reexport['unexplained_differences']:,}件のうち", heading)
            self.assertIn("全件の内訳ではありません", heading)
            self.assertTrue(all(len(row) == 3 for row in rv.failure_rows(review)))
            labels = dict(rv.count_rows(review))
            self.assertIn("出力CSV→再出力：説明できない差分（全件）", labels)
        for state in rr.STATES:
            self.assertIn(state, rv.STATE_TEXT)
        for state in (rr.PENDING, rr.FAIL, rr.READ_ERROR, rr.NOT_RUN):
            self.assertNotEqual(rv.STATE_TEXT[state][0], "success")
        for code in ("COMPANY_SETTING_NOT_AVAILABLE", "ROUTE_NOT_YAYOI_IMPORT_FORMAT", "REEXPORT_IDENTICAL_TO_CANDIDATE",
                     "FILES_CHANGED_DURING_CHECK", "READY_ONLY_FILES_DO_NOT_MATCH", "AUDIT_RECORD_NOT_FOUND_NEXT_TO_CSV"):
            self.assertIn(code, rv.REASON_TEXT)


# ----------------------------------------------------------------------------- company B (opt-in, read-only)

PRIVATE = Path(__file__).resolve().parents[1] / "data" / "private"
COMPANY_B = {
    "source": ("yayoi_act/source.txt", "7ac94294455b37e4d8e2804ef541d2c1153be1d6659a4fa9368d65429ff45417"),
    "candidate": ("yayoi_act/act_202603_formal_jdl.csv",
                  "97426c9a37c008484406484754e0ec724f8b1aba64accf1e4993671a6ebd9111"),
    "audit": ("yayoi_act/act_202603_formal_jdl.csv.audit.json",
              "50fc939393e262a48da3814172fac74db6bad2d037333a9a330dd3a9a4cb48e2"),
    "reexport": ("yayoi_act/act_reexport_202603_after_formal.csv",
                 "4f3e240479fae9866cb0067bb8bda7b5155836d64f11c44d6a341908a427befb"),
}
STORE = PRIVATE / "yayoi_store"


@unittest.skipUnless(STORE.is_dir() and all((PRIVATE / name).is_file() for name, _ in COMPANY_B.values()),
                     "private data is not present")
class CompanyBEvidenceTest(unittest.TestCase):
    """`EVID-YAYOI-JDL-35-5-COMPANYB-202603-FULL-ROUNDTRIP-001`: the screen gives the command line's PASS."""

    def test_company_b_round_trip_passes_like_the_command_line(self):
        from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
        from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore

        for name, digest in COMPANY_B.values():
            self.assertEqual(hashlib.sha256((PRIVATE / name).read_bytes()).hexdigest(), digest, name)
        store_before = listing(STORE)
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "store"
            shutil.copytree(STORE, store)                                # the private store is never opened for writing
            resolved = CompanySettingStore(store / "companies", ConversionProfileStore(store / "profiles")).resolve(
                "company-yayoi-act")
            paths = {key: PRIVATE / name for key, (name, _) in COMPANY_B.items()}
            review = rr.review(resolved, "company-yayoi-act", paths["source"], paths["candidate"], paths["reexport"])
            existing = cli.run_check(paths["source"], resolved.profile, resolved.context, "company-yayoi-act",
                                     paths["candidate"], paths["reexport"])
        self.assertEqual(existing["verdict"], "PASS")
        self.assertEqual((review.state, review.existing_verdict), (rr.PASS, "PASS"))
        self.assertEqual(review.counts["source"], {"journals": 80, "physical_rows": 86})
        self.assertEqual(review.counts["candidate"], {"journals": 80, "physical_rows": 86})
        self.assertEqual(review.reexport["journals"], [80, 80])
        self.assertEqual(review.reexport["physical_rows"], [86, 86])
        self.assertEqual((review.reexport["missing_rows"], review.reexport["extra_rows"],
                          review.reexport["unexplained_differences"]), (0, 0, 0))
        self.assertEqual(review.reexport["canonical_normalizations"], 454)
        self.assertEqual(review.verdict_information_outside_jdl, "PASS")
        self.assertEqual(review.closing_verdict, "PASS")
        lines = review.source_vs_candidate["lines_account_subaccount_amount_tax_date"]
        self.assertEqual(lines, {"missing": 0, "extra": 0})
        for name, digest in COMPANY_B.values():                          # still read-only
            self.assertEqual(hashlib.sha256((PRIVATE / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(listing(STORE), store_before)


if __name__ == "__main__":
    unittest.main()

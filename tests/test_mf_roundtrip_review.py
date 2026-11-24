"""JDL往復照合 Phase 2 (Money Forward pilot): regeneration binding, fiscal year chosen independently of the CSV,
explicit pilot enablement, states, no customer values, temporary files removed, Phase 1 untouched.

Synthetic data only, except the opt-in test at the end: it reads the existing FY2026-05 / FY2027-05 files of
`EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001` (data/private, read-only) with a COPY of a company store
named by AC_MF_PILOT_STORE / AC_MF_PILOT_COMPANY (never the real store itself).
"""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from accounting_converter.application import jdl_roundtrip_pilot as pilot
from accounting_converter.application import jdl_roundtrip_review as rr
from accounting_converter.application import mf_roundtrip_review as mf
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.tools import mf_formal_output_by_period as by_period
from accounting_converter.ui import roundtrip_view as rv
from tests import test_moneyforward_to_jdl_e2e as mf_e2e

COMPANY = "company-mf"
FY2026 = date(2026, 5, 31)
FY2027 = date(2027, 5, 31)
DESCRIPTION = "MF-JDL-SYNTHETIC"

# (transaction, date, amount, debit account). One journal per fiscal year, or a same-day pair: the only multi-journal
# batches the JDL output preflight allows in this synthetic (exempt) context.
JOURNALS = (("1", "2025/05/31", "500", "現金"),                              # FY2025-05
            ("2", "2026/05/31", "700", "現金"), ("3", "2026/05/31", "900", "小口現金"),  # FY2026-05: the last day
            ("4", "2026/06/01", "300", "現金"))                              # FY2027-05


def _fixtures():
    case = mf_e2e.MoneyForwardToJdlSyntheticE2ETests("test_simple_pair_and_supported_1d3c_pass")
    case.setUp()
    return case


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Env:
    def __init__(self, root: Path, journals=JOURNALS, *, company=COMPANY, account_override=None, enable=True):
        self.root = root
        self.case = _fixtures()
        self.store = root / "store"
        self.profiles = ConversionProfileStore(self.store / "profiles")
        self.companies = CompanySettingStore(self.store / "companies", self.profiles)
        context = self.case._target_context()
        profile = self.case._conversion_profile()
        if account_override:  # another mapping: 現金 → the given (name, code) of the same JDL master
            name, code = account_override
            profile.account_mappings["現金"] = MappingValue("現金", name, MappingStatus.USER_CONFIRMED,
                                                            metadata={"target_code": code, "target_formal_name": name})
        self.profiles.create(profile)
        context_file = root / "context.json"
        context_file.write_text(JdlTargetContextLoader().to_json_text(context), encoding="utf-8")
        self.companies.create(company_setting_id=company, display_name="MF合成", conversion_profile_id=profile.profile_id,
                              context_source=context_file)
        self.company = company
        self.source = self.write_source(root / "mf.csv", journals)
        self.pilot_file = pilot.pilot_path(self.store / "companies")
        if enable:
            self.enable()

    def write_source(self, path: Path, journals) -> Path:
        rows = []
        for number, day, amount, debit in journals:
            row = list(self.case._row(number, amount=amount, debit=debit, description=DESCRIPTION))
            row[1] = day
            rows.append(tuple(row))
        return self.case._write(path, rows)

    def resolved(self):
        return self.companies.resolve(self.company)

    def entry(self, fiscal_year_end="05-31", **override) -> dict:
        s = self.resolved().setting
        values = {"route": pilot.ROUTE_MONEYFORWARD, "company_setting_id": s.company_setting_id,
                  "conversion_profile_id": s.conversion_profile_id, "profile_fingerprint": s.profile_fingerprint,
                  "context_fingerprint": s.context_fingerprint, "source_format_key": s.expected_source_format_key,
                  "target_format_key": s.expected_target_format_key, "fiscal_year_end": fiscal_year_end}
        values.update(override)
        return values

    def enable(self, *entries):
        payload = {"schema": pilot.PILOT_SCHEMA, "pilots": list(entries) or [self.entry()]}
        self.pilot_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def candidates(self, source: Path | None = None, name="out") -> dict[str, Path]:
        """The command line tool's own formal output per fiscal year (generate), as the candidate CSVs."""
        output = self.root / name
        output.mkdir(exist_ok=True)
        by_period.generate(source or self.source, self.store, self.company, output, fy_end_month=5, fy_end_day=31)
        return {path.stem.rsplit("_FY", 1)[1]: path for path in output.glob("mf_formal_jdl_FY*.csv")}

    def reexport(self, candidate: Path, name="reexport.csv", change=None) -> Path:
        """What JDL gives back: the candidate with only canonical normalizations (blank voucher -> 0)."""
        rows = list(csv.reader(io.StringIO(candidate.read_bytes().decode("cp932"), newline="")))
        for row in rows[1:]:
            row[1] = row[1] or "0"
        if change:
            change(rows)
        out = io.StringIO(newline="")
        csv.writer(out, lineterminator="\r\n").writerows(rows)
        path = self.root / name
        path.write_bytes(out.getvalue().encode("cp932"))
        return path

    def review(self, candidate, reexport, period_end=FY2026, *, source=None, resolve=None):
        return mf.review(resolve or self.resolved, self.company, source or self.source, candidate, reexport,
                         period_end, self.pilot_file)


class _Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = Env(self.root)
        self.out = self.env.candidates()


class BindingAndVerdictTest(_Case):
    def test_pass_needs_the_regenerated_csv_and_the_strict_comparison(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        before = {p: sha(p) for p in (self.env.source, candidate, reexport)}
        listing = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        result = self.env.review(candidate, reexport)
        self.assertEqual(result.state, rr.PASS, result.reasons)
        self.assertTrue(result.is_pass)
        self.assertEqual(result.route, mf.ROUTE_MONEYFORWARD)
        self.assertTrue(result.regeneration["byte_identical"])
        self.assertEqual(result.regeneration["regenerated_sha256"], sha(candidate))
        self.assertEqual(result.period, {"start": "2025-06-01", "end": "2026-05-31", "fiscal_year_end": "05-31",
                                         "chosen_on_screen": True})
        self.assertEqual(result.counts["source"], {"journals": 2, "physical_rows": 2})
        self.assertEqual(result.counts["candidate"], {"journals": 2, "physical_rows": 2})
        self.assertEqual((result.reexport["journals"], result.reexport["unexplained_differences"]), ([2, 2], 0))
        self.assertGreater(result.reexport["canonical_normalizations"], 0)
        self.assertEqual(result.evidence_reference, {})                    # synthetic: no recorded result
        self.assertEqual({p: sha(p) for p in before}, before)               # read-only
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")), listing)

    def test_first_or_last_journal_missing_from_the_candidate_is_not_reproduced(self):
        # Last day: the candidate made from a source without the period's last journal.
        partial = self.env.write_source(self.root / "partial.csv", [j for j in JOURNALS if j[0] != "3"])
        short = self.env.candidates(partial, name="short")["2026-05"]
        result = self.env.review(short, self.env.reexport(short))
        self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("CANDIDATE_NOT_REPRODUCED",)))
        self.assertFalse(result.regeneration["byte_identical"])
        self.assertEqual(result.regeneration["source_journals_in_period"], 2)
        self.assertEqual(result.counts["candidate"]["journals"], 1)
        # First day of the year.
        with tempfile.TemporaryDirectory() as directory:
            first = (("1", "2025/06/01", "700", "現金"), ("2", "2025/06/01", "900", "小口現金"))
            env = Env(Path(directory), first)
            partial = env.write_source(Path(directory) / "partial.csv", first[1:])
            short = env.candidates(partial, name="short")["2026-05"]
            result = env.review(short, env.reexport(short))
            self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("CANDIDATE_NOT_REPRODUCED",)))

    def test_the_year_is_chosen_independently_of_the_candidate(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        for period_end in (FY2027, date(2025, 5, 31)):
            with self.subTest(period_end=period_end):
                result = self.env.review(candidate, reexport, period_end)
                self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("CANDIDATE_OUTSIDE_PERIOD",)))
                self.assertEqual(result.regeneration["candidate_journals_outside_period"], 2)
        self.assertEqual(self.env.review(candidate, reexport, None).reasons, ("PERIOD_NOT_SELECTED",))
        result = self.env.review(candidate, reexport, date(2026, 3, 31))      # not the company's fiscal year end
        self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("PERIOD_NOT_FISCAL_YEAR_END",)))
        self.assertEqual(by_period.period_bounds(FY2026), (date(2025, 6, 1), FY2026))
        self.assertEqual(by_period.period_bounds(FY2027), (date(2026, 6, 1), FY2027))

    def test_without_a_reexport_only_the_regeneration_is_checked(self):
        candidate = self.out["2027-05"]
        result = self.env.review(candidate, None, FY2027)
        self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("REEXPORT_NOT_SELECTED",)))
        self.assertTrue(result.regeneration["byte_identical"])
        self.assertFalse(result.is_pass)
        self.assertEqual(result.counts["candidate"], {"journals": 1, "physical_rows": 1})
        # Another year's re-export is no substitute.
        wrong = self.env.reexport(self.out["2026-05"])
        result = self.env.review(candidate, wrong, FY2027)
        self.assertEqual((result.state, result.reasons), (rr.FAIL, ("JDL_ROUNDTRIP_FAIL",)))

    def test_another_company_mapping_or_source_is_not_reproduced(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        # Another company with another mapping (現金 -> 当座預金), enabled for the pilot too.
        with tempfile.TemporaryDirectory() as directory:
            other = Env(Path(directory), company="company-other", account_override=("当座預金", "1003"))
            result = mf.review(other.resolved, "company-other", self.env.source, candidate, reexport, FY2026,
                               other.pilot_file)
            self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("CANDIDATE_NOT_REPRODUCED",)))
            self.assertEqual(result.regeneration["readiness"], "READY")
        # The same company id after a mapping change (pilot re-enabled for the new setting).
        with tempfile.TemporaryDirectory() as directory:
            changed = Env(Path(directory), account_override=("当座預金", "1003"))
            result = mf.review(changed.resolved, COMPANY, self.env.source, candidate, reexport, FY2026,
                               changed.pilot_file)
            self.assertEqual(result.reasons, ("CANDIDATE_NOT_REPRODUCED",))
        # A changed source (one amount).
        changed_source = self.env.write_source(self.root / "changed.csv",
                                               [(n, d, "800" if n == "2" else a, acc) for n, d, a, acc in JOURNALS])
        result = self.env.review(candidate, reexport, source=changed_source)
        self.assertEqual(result.reasons, ("CANDIDATE_NOT_REPRODUCED",))

    def test_regeneration_that_is_not_ready_is_not_run(self):
        blocked = self.env.write_source(self.root / "blocked.csv",
                                        (("2", "2026/05/30", "700", "現金"), ("3", "2026/05/31", "900", "小口現金")))
        candidate = self.out["2026-05"]
        result = self.env.review(candidate, self.env.reexport(candidate), source=blocked)
        self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("REGENERATION_NOT_READY",)))
        self.assertEqual(result.regeneration["readiness"], "BLOCKED")
        empty = self.env.write_source(self.root / "empty.csv", JOURNALS[:1])
        result = self.env.review(candidate, self.env.reexport(candidate), source=empty)
        self.assertEqual(result.reasons, ("SOURCE_HAS_NO_JOURNALS_IN_PERIOD",))

    def test_roundtrip_differences_fail_and_unreadable_files_are_read_errors(self):
        candidate = self.out["2026-05"]

        def amount(rows):
            rows[1][11] = rows[1][21] = str(int(rows[1][11]) + 1)          # balanced amount change

        result = self.env.review(candidate, self.env.reexport(candidate, "amount.csv", amount))
        self.assertEqual((result.state, result.reasons), (rr.FAIL, ("JDL_ROUNDTRIP_FAIL",)))
        self.assertIn("AMOUNT", {item["category"] for item in result.first_failures})
        result = self.env.review(candidate, self.env.reexport(candidate, "missing.csv", lambda rows: rows.pop()))
        self.assertEqual(result.state, rr.FAIL)
        self.assertEqual(result.reexport["missing_rows"], 1)
        utf8 = self.root / "utf8.csv"
        utf8.write_bytes(self.env.reexport(candidate).read_bytes().decode("cp932").encode("utf-8") + "あ".encode())
        result = self.env.review(candidate, utf8)
        self.assertEqual(result.state, rr.READ_ERROR)
        broken = self.root / "broken.csv"
        broken.write_bytes(b"\xff\xfe not cp932 \x81")
        self.assertEqual(self.env.review(broken, self.env.reexport(candidate)).state, rr.READ_ERROR)
        self.assertEqual(self.env.review(self.root / "none.csv", None).reasons, ("FILE_NOT_FOUND:candidate",))

    def test_same_content_and_same_file_are_not_compared(self):
        candidate = self.out["2026-05"]
        copy = self.root / "copy.csv"
        copy.write_bytes(candidate.read_bytes())
        result = self.env.review(candidate, copy)
        self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("REEXPORT_IDENTICAL_TO_CANDIDATE",)))
        self.assertEqual(self.env.review(candidate, candidate).reasons, ("SAME_FILE_SELECTED_TWICE",))

    def test_changes_during_the_check_give_no_verdict(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        original = by_period.regenerate_period

        def touch_source(*args, **kwargs):
            info = original(*args, **kwargs)
            self.env.source.write_bytes(self.env.source.read_bytes() + b"\r\n")
            return info

        with mock.patch.object(by_period, "regenerate_period", touch_source):
            result = self.env.review(candidate, reexport)
        self.assertEqual((result.state, result.reasons), (rr.READ_ERROR, ("FILES_CHANGED_DURING_CHECK",)))
        self.env.source.write_bytes(self.env.source.read_bytes()[:-2])
        calls = []

        def resolve():
            calls.append(1)
            resolved = self.env.resolved()
            if len(calls) > 1:  # the setting was saved again meanwhile
                from dataclasses import replace

                resolved = replace(resolved, setting=replace(resolved.setting, context_fingerprint="0" * 64))
            return resolved

        result = self.env.review(candidate, reexport, resolve=resolve)
        self.assertEqual((result.state, result.reasons), (rr.READ_ERROR, ("SETTING_CHANGED_DURING_CHECK",)))

    def test_exceptions_are_read_errors_temporary_files_are_removed_nothing_is_logged(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        temp_root = self.root / "os_temp"
        temp_root.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(temp_root)), \
                mock.patch("accounting_converter.infrastructure.local_diagnostic_log.log_local_exception") as logged:
            with self.assertNoLogs(level="DEBUG"):
                passed = self.env.review(candidate, reexport)
            self.assertEqual(passed.state, rr.PASS)
            self.assertEqual(list(temp_root.iterdir()), [])
            with mock.patch("accounting_converter.application.moneyforward_conversion_workflow."
                            "MoneyForwardConversionWorkflow.execute", side_effect=RuntimeError(DESCRIPTION)):
                failed = self.env.review(candidate, reexport)
            self.assertEqual((failed.state, failed.reasons, failed.error_type),
                             (rr.READ_ERROR, ("CHECK_RAISED",), "RuntimeError"))
            self.assertEqual(list(temp_root.iterdir()), [])               # removed after the exception too
            logged.assert_not_called()
        self.assertNotIn(DESCRIPTION, json.dumps(failed.summary(), ensure_ascii=False))


class PilotTest(_Case):
    def test_disabled_by_default_and_bound_to_the_setting(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        self.env.pilot_file.unlink()
        self.assertEqual(self.env.review(candidate, reexport).reasons, ("PILOT_NOT_ENABLED",))
        for broken in ("{", json.dumps({"schema": "other", "pilots": []}),
                       json.dumps({"schema": pilot.PILOT_SCHEMA, "pilots": [{"route": "MONEYFORWARD"}]})):
            self.env.pilot_file.write_text(broken, encoding="utf-8")
            self.assertEqual(self.env.review(candidate, reexport).reasons, ("PILOT_FILE_INVALID",))
        self.env.enable(self.env.entry(fiscal_year_end="02-29"))
        self.assertEqual(self.env.review(candidate, reexport).reasons, ("PILOT_FILE_INVALID",))
        self.env.enable(self.env.entry(company_setting_id="company-other"))
        self.assertEqual(self.env.review(candidate, reexport).reasons, ("PILOT_COMPANY_NOT_LISTED",))
        for name in ("profile_fingerprint", "context_fingerprint", "conversion_profile_id", "source_format_key",
                     "target_format_key"):
            with self.subTest(changed=name):
                self.env.enable(self.env.entry(**{name: "changed"}))
                result = self.env.review(candidate, reexport)
                self.assertEqual((result.state, result.reasons), (rr.NOT_RUN, ("PILOT_SETTING_CHANGED",)))
        self.env.enable(self.env.entry(fiscal_year_end="03-31"))        # no 05-31 default: the entry decides
        self.assertEqual(self.env.review(candidate, reexport).reasons, ("PERIOD_NOT_FISCAL_YEAR_END",))
        self.env.enable()
        self.assertEqual(self.env.review(candidate, reexport).state, rr.PASS)
        self.assertEqual(self.env.review(candidate, reexport, resolve=lambda: None).reasons,
                         ("COMPANY_SETTING_NOT_AVAILABLE",))

    def test_controller_offers_the_check_only_for_an_enabled_pilot_and_never_writes_the_pilot_file(self):
        from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
        from accounting_converter.ui.controllers import AccountingConverterController

        controller = AccountingConverterController(
            profile_store=self.env.profiles, company_store=self.env.companies,
            preferences_store=ApplicationPreferencesStore(self.root / "preferences.json"))
        pilot_bytes = self.env.pilot_file.read_bytes()
        self.assertEqual(controller.jdl_roundtrip_route(COMPANY), (True, None))
        self.assertEqual(controller.jdl_roundtrip_period(COMPANY), "05-31")
        candidate = self.out["2026-05"]
        result = controller.jdl_roundtrip_review(COMPANY, self.env.source, candidate, self.env.reexport(candidate),
                                                 period_end=FY2026)
        self.assertEqual(result.state, rr.PASS)
        self.assertEqual(self.env.pilot_file.read_bytes(), pilot_bytes)
        self.env.pilot_file.unlink()
        self.assertEqual(controller.jdl_roundtrip_route(COMPANY), (False, "PILOT_NOT_ENABLED"))
        self.assertIsNone(controller.jdl_roundtrip_period(COMPANY))
        self.assertFalse(self.env.pilot_file.exists())
        self.assertEqual(controller.jdl_roundtrip_review(COMPANY, self.env.source, candidate, None,
                                                         period_end=FY2026).reasons, ("PILOT_NOT_ENABLED",))

    def test_a_yayoi_company_is_never_a_moneyforward_pilot(self):
        from tests.test_jdl_roundtrip_review import Env as YayoiEnv

        with tempfile.TemporaryDirectory() as directory:
            yayoi = YayoiEnv(Path(directory))
            resolved = yayoi.company.companies.resolve("company-o")
            self.assertFalse(mf.is_moneyforward(resolved.profile))
            self.assertEqual(mf.route_status(resolved, self.env.pilot_file), (None, "ROUTE_NOT_MONEYFORWARD"))


class SummaryAndViewTest(_Case):
    def test_summary_has_no_customer_values_and_is_never_overwritten(self):
        candidate = self.out["2026-05"]
        result = self.env.review(candidate, self.env.reexport(candidate))
        text = json.dumps(result.summary(), ensure_ascii=False)
        for value in (DESCRIPTION, "普通預金", "小口現金", "700", "900", "2026/05/31"):
            self.assertNotIn(value, text)
        self.assertIn('"regeneration"', text)
        target = self.root / "summary.json"
        rr.save_summary(result, target)
        saved = target.read_bytes()
        with self.assertRaises(FileExistsError):
            rr.save_summary(result, target)
        self.assertEqual(target.read_bytes(), saved)

    def test_screen_separates_the_four_meanings_and_shows_a_record_only_when_everything_matches(self):
        candidate = self.out["2026-05"]
        reexport = self.env.reexport(candidate)
        result = self.env.review(candidate, reexport)
        rows = dict(rv.count_rows(result))
        self.assertEqual(rows["① 元データ→出力CSV：現在の会社設定で作り直した内容との一致"], "バイト単位で一致")
        self.assertEqual(rows["② 出力CSV→再出力：データの整合性"], "整合")
        self.assertEqual(rows["③ 既存Evidenceとの一致（参考）"], "記録と一致する結果はありません")
        self.assertIn("できません", rows["④ JDLを経由したことの独立した証明"])
        self.assertIn("過去に使った設定", rv.headline(result)[3])
        record = mf.RecordedRoundTrip("EVID-SYNTHETIC", "2026-11-24", "2026-05-31", sha(self.env.source),
                                      sha(candidate), sha(reexport), "PASS", 2, 2, "docs")
        with mock.patch.object(mf, "RECORDED_ROUNDTRIPS", (record,)):
            shown = self.env.review(candidate, reexport)
            self.assertEqual(shown.evidence_reference["evidence_id"], "EVID-SYNTHETIC")
            self.assertEqual(shown.evidence_reference["not_in_record"], ["company_setting"])
            self.assertIn("会社設定は記録に含まれません", dict(rv.count_rows(shown))["③ 既存Evidenceとの一致（参考）"])
            other = self.env.reexport(candidate, "other.csv", lambda rows: rows[1].__setitem__(1, "00"))
            self.assertEqual(self.env.review(candidate, other).evidence_reference, {})  # candidate hash alone: no
        not_run = self.env.review(self.out["2027-05"], None, FY2027)
        self.assertEqual(dict(rv.count_rows(not_run))["② 出力CSV→再出力：データの整合性"], "照合していません")
        self.assertEqual(rv.period_label(FY2026), "FY2026-05（2025-06-01〜2026-05-31）")
        self.assertIn("税理士の承認ではありません", "".join(rv.guidance(True)))

    def test_phase_1_summary_is_unchanged(self):
        self.assertNotIn("regeneration", rr.RoundTripReview(rr.PASS, "company-b", rr.ROUTE_YAYOI_IMPORT).summary())


PRIVATE = Path(__file__).resolve().parents[1] / "data" / "private"
MF_SOURCE = PRIVATE / "mf_to_jdl_ready_batch_20260107_20260110" / "仕訳帳_20261009_1130.csv"
MF_OUTPUT = PRIVATE / "mf_482_formal_output"
MF_FILES = {
    MF_SOURCE: "f056c8d7781ab6743ac8a82fd3785a5c603a4a9d8d40984c618deef3241687ea",
    MF_OUTPUT / "mf_formal_jdl_FY2026-05.csv": "ec2bcc3bd02aa2e31b818bcfffba3b1b4d02fe25ab87b37ca7ba5e76f4f9b90b",
    MF_OUTPUT / "mf_formal_jdl_FY2027-05.csv": "090f3633f5fa153f1ef2daf6f0fc9890588285ca0ec7543d8789b0187ec794fb",
    MF_OUTPUT / "JDL出納帳-0514-0878-仕訳.csv": "d8b5014194978970ee2a1d0c7172222baaaed55e43688d73a537f0a57a0c17df",
}
STORE_ENV, COMPANY_ENV = "AC_MF_PILOT_STORE", "AC_MF_PILOT_COMPANY"


@unittest.skipUnless(os.environ.get(STORE_ENV) and os.environ.get(COMPANY_ENV) and all(p.is_file() for p in MF_FILES),
                     "opt-in: existing MF Evidence files and AC_MF_PILOT_STORE / AC_MF_PILOT_COMPANY")
class ExistingMfEvidenceTest(unittest.TestCase):
    """Existing Evidence, read-only. The named company store is COPIED to a temporary folder first."""

    def test_fy2026_passes_like_the_record_and_fy2027_has_no_reexport(self):
        for path, expected in MF_FILES.items():
            self.assertEqual(sha(path), expected, path.name)
        company = os.environ[COMPANY_ENV]
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "store"
            shutil.copytree(Path(os.environ[STORE_ENV]) / "profiles", store / "profiles")
            shutil.copytree(Path(os.environ[STORE_ENV]) / "companies" / company, store / "companies" / company)
            companies = CompanySettingStore(store / "companies", ConversionProfileStore(store / "profiles"))
            resolve = lambda: companies.resolve(company)  # noqa: E731
            s = resolve().setting
            pilot_file = pilot.pilot_path(store / "companies")
            pilot_file.write_text(json.dumps({"schema": pilot.PILOT_SCHEMA, "pilots": [{
                "route": pilot.ROUTE_MONEYFORWARD, "company_setting_id": s.company_setting_id,
                "conversion_profile_id": s.conversion_profile_id, "profile_fingerprint": s.profile_fingerprint,
                "context_fingerprint": s.context_fingerprint, "source_format_key": s.expected_source_format_key,
                "target_format_key": s.expected_target_format_key, "fiscal_year_end": "05-31"}]}), encoding="utf-8")
            fy2026 = mf.review(resolve, company, MF_SOURCE, MF_OUTPUT / "mf_formal_jdl_FY2026-05.csv",
                               MF_OUTPUT / "JDL出納帳-0514-0878-仕訳.csv", FY2026, pilot_file)
            self.assertEqual(fy2026.state, rr.PASS, fy2026.reasons)
            self.assertTrue(fy2026.regeneration["byte_identical"])
            self.assertEqual((fy2026.regeneration["source_journals_in_period"],
                              fy2026.regeneration["source_journals_total"]), (378, 482))
            self.assertEqual(fy2026.counts["candidate"], {"journals": 378, "physical_rows": 479})
            self.assertEqual((fy2026.reexport["journals"], fy2026.reexport["physical_rows"]), ([378, 378], [479, 479]))
            self.assertEqual((fy2026.reexport["missing_rows"], fy2026.reexport["extra_rows"],
                              fy2026.reexport["unexplained_differences"], fy2026.reexport["canonical_normalizations"]),
                             (0, 0, 0, 2442))
            self.assertEqual(fy2026.evidence_reference["evidence_id"],
                             "EVID-MF-JDL-35-5-REAL-482-FY2026-05-FULL-ROUNDTRIP-001")
            fy2027 = mf.review(resolve, company, MF_SOURCE, MF_OUTPUT / "mf_formal_jdl_FY2027-05.csv", None, FY2027,
                               pilot_file)
            self.assertEqual((fy2027.state, fy2027.reasons), (rr.NOT_RUN, ("REEXPORT_NOT_SELECTED",)))
            self.assertTrue(fy2027.regeneration["byte_identical"])
            self.assertEqual(fy2027.counts["candidate"]["journals"], 104)
            self.assertEqual(fy2027.evidence_reference, {})
        for path, expected in MF_FILES.items():
            self.assertEqual(sha(path), expected, path.name)


if __name__ == "__main__":
    unittest.main()

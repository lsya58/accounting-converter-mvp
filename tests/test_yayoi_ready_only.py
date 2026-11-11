"""READY-only Yayoi → JDL output (application/yayoi_ready_only). Synthetic data only."""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from accounting_converter.application import yayoi_ready_only as ro
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    NEGATIVE_AMOUNT_BLOCKER,
    YayoiJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.application.yayoi_sources import IMPORT
from tests.test_yayoi_import_format import (
    OUTSIDE as IMPORT_OUTSIDE,
    YAYOI as IMPORT_YAYOI,
    Company,
    NonRetainedInformationTest,
    floor_context,
    journals,
    row,
    write_import,
)
from tests.test_yayoi_jdl_workflow import OUTSIDE, YAYOI
from tests.test_yayoi_journal_report_parser import detail
from tests.test_yayoi_scoped_workflow import DATE, make, sales_voucher

COMPANY = "company-yayoi"


def mixed(extra=()):
    """voucher 1: 3 rows (READY) / voucher 2: 17 rows (over the 16-row limit, both sides multi-line: BLOCK) /
    voucher 3: 2 rows (READY)."""
    return sales_voucher(3, voucher=1) + sales_voucher(17, voucher=2) + sales_voucher(2, voucher=3) + list(extra)


def confirm(plan, **changes):
    values = dict(plan_fingerprint=plan.fingerprint, output_journals=plan.ready_count,
                  excluded_journals=plan.excluded_count, confirmed_by="架空の確認者",
                  acknowledged_not_full_migration=True, acknowledged_duplicate_check=True,
                  acknowledged_excluded_follow_up=True)
    values.update(changes)
    return ro.ReadyOnlyConfirmation(**values)


def jdl_rows(path: Path):
    return [r for r in csv.reader(io.StringIO(path.read_bytes().decode("cp932"), newline="")) if r and r[0].isdigit()]


class Run:
    def __init__(self, directory, rows=None):
        self.root = Path(directory)
        self.fixture = make(directory, rows if rows is not None else mixed())
        self.resolved = self.fixture.resolved()
        self.source = self.fixture.source
        self.output = self.root / "out" / "ready_only.csv"

    def plan(self):
        return ro.plan_ready_only(self.source, self.resolved.profile, self.resolved.context, COMPANY)

    def prepare(self, plan, confirmation):
        return ro.prepare_ready_only(plan, confirmation, input_path=self.source, output_path=self.output,
                                     profile=self.resolved.profile, context=self.resolved.context,
                                     company_setting_validated=self.resolved.available)

    def write(self):
        plan = self.plan()
        confirmation = confirm(plan)
        prepared = self.prepare(plan, confirmation)
        assert prepared.summary.readiness is FirstReleaseReadiness.READY, prepared.summary.blocking_reasons
        return plan, ro.execute_ready_only(prepared, plan, confirmation)

    def verify(self):
        return ro.verify_ready_only_output(self.source, self.output, self.resolved.profile, self.resolved.context,
                                           COMPANY)


def _edit_manifest(output, change):
    path = ro.manifest_path_for(output)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


class DefaultModeTest(unittest.TestCase):
    def test_the_full_conversion_still_writes_nothing_when_any_journal_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            prepared = YayoiJdlWorkflow().prepare(input_path=run.source, output_path=run.output,
                                                  profile=run.resolved.profile, context=run.resolved.context,
                                                  company_setting_validated=True)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            self.assertIsNone(YayoiJdlWorkflow().execute(prepared))
            self.assertFalse(run.output.exists())


class PlanTest(unittest.TestCase):
    def test_every_journal_is_either_written_or_listed_with_its_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Run(directory).plan()
        self.assertTrue(plan.available, plan.problems)
        self.assertEqual((plan.total_journals, plan.ready_count, plan.excluded_count), (3, 2, 1))
        excluded = plan.excluded[0]
        self.assertEqual((excluded.date, excluded.voucher, excluded.debit_total, excluded.credit_total),
                         ("2026-05-10", "2", Decimal(17 * 1100), Decimal(17 * 1100)))
        self.assertIn("HUMAN:VOUCHER_ROW_LIMIT_EXCEEDED", excluded.blockers)
        self.assertTrue(excluded.reasons)
        self.assertEqual(plan.totals["all"]["debit"], str(22 * 1100))
        self.assertEqual(Decimal(plan.totals["ready"]["debit"]) + Decimal(plan.totals["excluded"]["debit"]),
                         Decimal(plan.totals["all"]["debit"]))
        self.assertEqual(plan.totals["ready"]["debit"], plan.totals["ready"]["credit"])

    def test_not_offered_when_nothing_is_excluded_or_nothing_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Run(directory, sales_voucher(3)).plan().problems, (ro.NOTHING_EXCLUDED,))
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn(ro.NO_READY_JOURNAL, Run(directory, sales_voucher(17)).plan().problems)

    def test_a_negative_amount_is_never_ready(self):
        negative = [detail(DATE, 9, debit=(YAYOI["cash"], "", OUTSIDE, -500, None),
                           credit=(YAYOI["cash"], "", OUTSIDE, -500, None), description="負", number=9)]
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory, mixed(negative))
            assessment = YayoiJdlWorkflow().assess(run.source, run.resolved.profile, run.resolved.context)
            blocked = {key for key, found in assessment.journal_blockers.items() if NEGATIVE_AMOUNT_BLOCKER in found}
            self.assertEqual(len(blocked), 1)
            plan = run.plan()
            self.assertIn(NEGATIVE_AMOUNT_BLOCKER, {code for item in plan.excluded for code in item.blockers})
            self.assertEqual(plan.ready_count, 2)


class ConfirmationTest(unittest.TestCase):
    def test_nothing_is_written_without_the_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            plan = run.plan()
            for confirmation in (None, confirm(plan, plan_fingerprint="0" * 64), confirm(plan, output_journals=3),
                                 confirm(plan, excluded_journals=0), confirm(plan, confirmed_by=" "),
                                 confirm(plan, acknowledged_not_full_migration=False),
                                 confirm(plan, acknowledged_duplicate_check=False),
                                 confirm(plan, acknowledged_excluded_follow_up=False)):
                with self.subTest(confirmation=confirmation):
                    prepared = run.prepare(plan, confirmation)
                    self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
                    self.assertIsNone(ro.execute_ready_only(prepared, plan, confirmation or confirm(plan)))
                    self.assertFalse(any(path.exists() for path in ro.run_paths(run.output)))

    def test_a_changed_input_after_the_confirmation_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            plan = run.plan()
            run.source.write_bytes(run.source.read_bytes().replace("売上1".encode("cp932"), "売上X".encode("cp932"), 1))
            prepared = run.prepare(plan, confirm(plan))
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            self.assertTrue(any("変わりました" in reason for reason in prepared.summary.blocking_reasons))

    def test_existing_files_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            plan = run.plan()
            run.output.parent.mkdir(parents=True)
            ro.excluded_list_path_for(run.output).write_text("occupied", encoding="utf-8")
            self.assertIs(run.prepare(plan, confirm(plan)).summary.readiness, FirstReleaseReadiness.BLOCKED)


class WriteTest(unittest.TestCase):
    def test_only_whole_ready_journals_are_written_and_everything_is_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            plan, result = run.write()
            self.assertEqual(result.status, "SUCCESS")
            self.assertEqual((result.output_journals, result.output_vouchers, result.output_rows,
                              result.excluded_journals, result.total_journals), (2, 2, 5, 1, 3))
            rows = jdl_rows(run.output)
            # Voucher 1 (3 rows) and voucher 3 (2 rows) whole; nothing of voucher 2.
            self.assertEqual([r[0] for r in rows], ["1110", "1100", "1101", "1110", "1101"])
            self.assertEqual([r[23] for r in rows], ["売上1", "売上2", "売上3", "売上1", "売上2"])
            self.assertEqual(sum(Decimal(r[11]) for r in rows), Decimal(5 * 1100))
            manifest = json.loads(ro.manifest_path_for(run.output).read_text(encoding="utf-8"))
            self.assertEqual((manifest["mode"], manifest["full_migration"], manifest["not_migrated_journals"]),
                             ("READY_ONLY", False, 1))
            self.assertEqual(manifest["counts"]["input_journals"],
                             manifest["counts"]["output_journals"] + manifest["counts"]["excluded_journals"])
            self.assertEqual(manifest["settings"]["voucher_row_limit"], 16)
            self.assertEqual(manifest["company_setting_id"], COMPANY)
            self.assertEqual(manifest["confirmation"]["confirmed_by"], "架空の確認者")
            listed = ro.excluded_list_path_for(run.output).read_bytes().decode("utf-8-sig").splitlines()
            self.assertEqual(listed[0].split(","), list(ro.EXCLUDED_HEADER))
            self.assertEqual(len(listed), 2)
            self.assertEqual(run.verify()["verdict"], "PASS")

    def test_tampering_or_a_missing_file_is_detected(self):
        changes = {
            "excluded list edited": lambda out: ro.excluded_list_path_for(out).write_bytes(
                ro.excluded_list_path_for(out).read_bytes().replace(b"2026-05-10", b"2026-05-11")),
            "excluded list deleted": lambda out: ro.excluded_list_path_for(out).unlink(),
            "manifest edited": lambda out: ro.manifest_path_for(out).write_text(
                ro.manifest_path_for(out).read_text(encoding="utf-8").replace('"excluded_journals": 1', '"excluded_journals": 0'),
                encoding="utf-8"),
            "manifest deleted": lambda out: ro.manifest_path_for(out).unlink(),
            "CSV edited": lambda out: out.write_bytes(out.read_bytes().replace(b",1100,", b",1101,", 1)),
            "not-migrated statement edited": lambda out: _edit_manifest(out, lambda m: m.update(not_migrated_journals=0)),
            "full-migration flag edited": lambda out: _edit_manifest(out, lambda m: m.update(full_migration=True)),
            "notes removed": lambda out: _edit_manifest(out, lambda m: m.update(notes=[])),
            "confirmation removed": lambda out: _edit_manifest(out, lambda m: m.pop("confirmation")),
            "acknowledgement edited": lambda out: _edit_manifest(
                out, lambda m: m["confirmation"].update(acknowledged_duplicate_check=False)),
            "confirmer erased": lambda out: _edit_manifest(out, lambda m: m["confirmation"].update(confirmed_by="")),
        }
        for name, change in changes.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                run = Run(directory)
                run.write()
                change(run.output)
                self.assertEqual(run.verify()["verdict"], "FAIL")

    def test_a_failure_in_the_middle_leaves_no_file(self):
        for target in ("_excluded_csv", "expected_vouchers", "verify_non_retained_audit"):
            with self.subTest(target), tempfile.TemporaryDirectory() as directory:
                run = Run(directory)
                with mock.patch.object(ro, target, side_effect=OSError("disk")):
                    with self.assertRaises(OSError):
                        run.write()
                self.assertFalse(any(path.exists() for path in ro.run_paths(run.output)))

    def test_a_refused_output_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(directory)
            plan = run.plan()
            confirmation = confirm(plan)
            prepared = run.prepare(plan, confirmation)
            failed = mock.Mock(status=mock.Mock(value="FAILED"), output_path=None, validation_results=())
            with mock.patch.object(prepared.conversion_service, "convert", return_value=failed):
                result = ro.execute_ready_only(prepared, plan, confirmation)
            self.assertEqual(result.status, "FAILED")
            self.assertFalse(any(path.exists() for path in ro.run_paths(run.output)))


class AuditScopeTest(unittest.TestCase):
    """Information JDL does not hold: only the confirmed kinds, only for the written journals."""

    def _company(self, root, confirm_fields):
        rows = journals(origin="取込", department="部門A") + [
            row("2000", 7, "R.08/05/13", ("未登録科目Y", "", IMPORT_OUTSIDE, 500, 0),
                (IMPORT_YAYOI["cash"], "", IMPORT_OUTSIDE, 500, 0), "未確認の科目"),
        ]
        company = Company(root, "company-o", write_import(root, rows), IMPORT, floor_context())
        company.confirm_all()
        if confirm_fields:
            NonRetainedInformationTest()._confirm_fields(company, ["生成元", "部門"])
        return company

    def test_the_audit_covers_exactly_the_written_journals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = self._company(root, confirm_fields=True)
            resolved = company.resolved()
            plan = ro.plan_ready_only(company.source, resolved.profile, resolved.context, company.company_id)
            self.assertEqual((plan.ready_count, plan.excluded_count), (3, 1))
            output = root / "ro.csv"
            confirmation = confirm(plan)
            prepared = ro.prepare_ready_only(plan, confirmation, input_path=company.source, output_path=output,
                                             profile=resolved.profile, context=resolved.context,
                                             company_setting_validated=True)
            result = ro.execute_ready_only(prepared, plan, confirmation)
            self.assertEqual(result.status, "SUCCESS")
            audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
            self.assertEqual(audit["journal_scope"]["mode"], "READY_ONLY")
            ready = frozenset(plan.ready_ids)
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile,
                                                       resolved.context, journal_ids=ready)["verdict"], "PASS")
            # A READY-only audit never passes as the audit of a full output (and the reverse).
            self.assertEqual(verify_non_retained_audit(company.source, output, resolved.profile,
                                                       resolved.context)["verdict"], "FAIL")
            self.assertEqual(ro.verify_ready_only_output(company.source, output, resolved.profile, resolved.context,
                                                         company.company_id)["verdict"], "PASS")
            # The round-trip check can compare just those journals.
            from accounting_converter.tools.yayoi_roundtrip_check import check

            report = check(company.source, resolved.profile, resolved.context, output, None, journal_ids=ready)
            self.assertEqual(report["verdict"], "SOURCE_TO_CSV_PASS_REEXPORT_PENDING", report)

    def test_unconfirmed_information_outside_jdl_keeps_the_journal_out(self):
        with tempfile.TemporaryDirectory() as directory:
            company = self._company(Path(directory), confirm_fields=False)
            resolved = company.resolved()
            plan = ro.plan_ready_only(company.source, resolved.profile, resolved.context, company.company_id)
            codes = {code for item in plan.excluded for code in item.blockers}
            self.assertTrue({"HUMAN:OPTIONAL_FIELD_POLICY", "HUMAN:DEPARTMENT_POLICY"} & codes, codes)
            self.assertIn("HUMAN:ACCOUNT_MAPPING", codes)
            self.assertEqual(plan.ready_count + plan.excluded_count, plan.total_journals)
            self.assertLess(plan.ready_count, 3)


if __name__ == "__main__":
    unittest.main()

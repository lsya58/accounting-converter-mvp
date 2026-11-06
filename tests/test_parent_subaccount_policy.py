"""Per-parent subaccount policy: classification, parent-only approval, audit, readiness == output guard. Synthetic data."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.adapters.output.jdl import JdlSubaccountIdentity
from accounting_converter.application import parent_subaccount_policy as policy
from accounting_converter.application.company_mapping_update import PARENT_ONLY_SELECTION, CompanyMappingUpdateService
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.application.yayoi_jdl_workflow import (
    DROPPED_SUBACCOUNT_FIELD,
    YayoiJdlWorkflow,
    audit_path_for,
    verify_non_retained_audit,
)
from accounting_converter.application.yayoi_sources import IMPORT
from tests.test_yayoi_import_format import OUTSIDE, PURCHASE, YAYOI, Company, floor_context, journals, row, write_import

FEE = YAYOI["fee"]  # JDL 8681: no subaccount in the JDL master
BANK = YAYOI["bank"]  # JDL 1311: has JDL subaccount 銀行A


def source_rows():
    return journals() + [
        row("2000", 3, "R.08/05/13", (FEE, "取引先P", PURCHASE, 1100, 100), (YAYOI["cash"], "", OUTSIDE, 1100, 0), "手数料P"),
        row("2000", 4, "R.08/05/14", (FEE, "取引先Q", PURCHASE, 2200, 200), (YAYOI["cash"], "", OUTSIDE, 2200, 0), "手数料Q"),
        row("2000", 5, "R.08/05/15", (YAYOI["cash"], "", OUTSIDE, 3300, 0), (BANK, "口座B", OUTSIDE, 3300, 0), "口座B入金"),
    ]


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = write_import(self.root, source_rows())
        self.company = Company(self.root, "company-p", self.source, IMPORT, floor_context())
        self.company.confirm_all()
        self.service = CompanyMappingUpdateService(self.company.companies, self.company.profiles)

    def tearDown(self):
        self._tmp.cleanup()

    def review(self):
        return self.service.review(self.company.company_id, self.source)

    def groups(self):
        return {g.source_parent: g for g in policy.parent_groups(self.review())}

    def approve_parent_only(self, *subs):
        review = self.review()
        keys = {i.source_value: i.key for i in review.items if i.mapping_type == "SUBACCOUNT" and i.parent_account == FEE}
        chosen = {keys[name]: PARENT_ONLY_SELECTION for name in subs}
        self.service.apply(review, chosen, set(chosen))

    # ---- classification
    def test_classes_follow_the_jdl_master(self):
        groups = self.groups()
        fee, bank = groups[FEE], groups[BANK]
        self.assertEqual({m.klass for m in fee.members}, {policy.PARENT_ONLY_OK})
        self.assertTrue(fee.parent_only_possible)
        self.assertEqual({m.klass for m in bank.members}, {policy.NEEDS_JDL_SUB})  # 口座B has no JDL counterpart
        self.assertFalse(bank.parent_only_possible)
        self.assertIn("補助科目が設定されている", bank.reason_parent_only_forbidden)
        self.assertEqual(policy.summarize(tuple(groups.values()))["parent_only_whole_parent_possible"],
                         {"parents": 1, "items": 2, "approvals_if_chosen_per_parent": 1})

    def test_parent_only_is_refused_where_the_jdl_parent_has_subaccounts(self):
        bank = self.groups()[BANK]
        with self.assertRaises(ValueError):
            policy.parent_only_selections(bank)
        review = self.review()
        item = next(i for i in review.items if i.parent_account == BANK)
        with self.assertRaises(ValueError):  # the save path refuses it as well
            self.service.apply(review, {item.key: PARENT_ONLY_SELECTION}, {item.key})

    def test_nothing_is_selected_for_the_human(self):
        fee = self.groups()[FEE]
        selections = policy.parent_only_selections(fee)
        self.assertEqual(set(selections.values()), {PARENT_ONLY_SELECTION})
        # Building the selections saved nothing: both journals are still blocked.
        self.assertIn("HUMAN:SUBACCOUNT_MAPPING", self.company.assess().blocker_counts())

    # ---- approval, readiness and output guard
    def test_without_approval_the_source_subaccount_is_never_dropped(self):
        assessment = self.company.assess()
        self.assertIn("HUMAN:SUBACCOUNT_MAPPING", assessment.blocker_counts())
        resolved = self.company.resolved()
        prepared = YayoiJdlWorkflow().prepare(input_path=self.source, output_path=self.root / "n.csv",
                                              profile=resolved.profile, context=resolved.context,
                                              company_setting_validated=resolved.available)
        self.assertIsNot(prepared.summary.readiness, FirstReleaseReadiness.READY)

    def test_parent_only_after_one_approval_per_parent_converts_and_is_audited(self):
        review = self.review()
        selections = policy.parent_only_selections(self.groups()[FEE])
        self.assertEqual(len(selections), 2)
        self.service.apply(review, selections, set(selections))  # one Human action for the whole parent
        groups = self.groups()
        self.assertNotIn(FEE, groups)  # nothing left to confirm for this parent
        self.assertIn(BANK, groups)  # other parents are untouched
        resolved = self.company.resolved()
        assessment = self.company.assess()
        self.assertFalse(assessment.information_fully_retained)
        self.assertEqual(assessment.non_retained_journals, {DROPPED_SUBACCOUNT_FIELD: 2})
        output = self.root / "out.csv"
        # Journal 5 (口座B) is still blocked, so the whole file is not READY: readiness and output agree.
        prepared = YayoiJdlWorkflow().prepare(input_path=self.source, output_path=output, profile=resolved.profile,
                                              context=resolved.context, company_setting_validated=resolved.available)
        self.assertIsNot(prepared.summary.readiness, FirstReleaseReadiness.READY)
        self.assertFalse(output.exists())

    def _ready_company(self):
        """Same company, but the source holds only journals that are fully decided."""
        rows = [r for r in source_rows() if r[1] != "5"]
        (self.root / "ready").mkdir()
        source = write_import(self.root / "ready", rows)
        company = Company(self.root, "company-r", source, IMPORT, floor_context())
        company.confirm_all()
        service = CompanyMappingUpdateService(company.companies, company.profiles)
        review = service.review(company.company_id, source)
        selections = policy.parent_only_selections(
            {g.source_parent: g for g in policy.parent_groups(review)}[FEE])
        service.apply(review, selections, set(selections))
        return company, source

    def test_formal_output_blank_subaccount_and_audit_keep_the_original(self):
        company, source = self._ready_company()
        assessment = company.assess()
        self.assertEqual(assessment.ready_journals, len(assessment.journal_blockers), assessment.blocker_counts())
        resolved = company.resolved()
        output = self.root / "ready" / "out.csv"
        prepared = YayoiJdlWorkflow().prepare(input_path=source, output_path=output, profile=resolved.profile,
                                              context=resolved.context, company_setting_validated=resolved.available)
        self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
        result = YayoiJdlWorkflow().execute(prepared)
        self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
        text = output.read_bytes().decode("cp932")
        self.assertNotIn("取引先P", text)
        self.assertNotIn("取引先Q", text)
        audit = json.loads(audit_path_for(output).read_text(encoding="utf-8"))
        self.assertFalse(audit["information_fully_retained"])
        self.assertEqual(audit["jdl_output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        values = {(i["field"], i["value"]) for j in audit["journals"] for i in j["not_in_jdl"]}
        self.assertEqual(values, {(DROPPED_SUBACCOUNT_FIELD, f"DEBIT|{FEE}|取引先P"),
                                  (DROPPED_SUBACCOUNT_FIELD, f"DEBIT|{FEE}|取引先Q")})
        self.assertEqual(verify_non_retained_audit(source, output, resolved.profile)["verdict"], "PASS")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), audit["source_sha256"])  # source untouched

    def test_audit_is_not_produced_when_no_subaccount_is_dropped(self):
        (self.root / "plain").mkdir()
        company = Company(self.root, "company-n", write_import(self.root / "plain", journals()), IMPORT, floor_context())
        company.confirm_all()
        self.assertTrue(company.assess().information_fully_retained)
        self.assertEqual(policy.parent_groups(
            CompanyMappingUpdateService(company.companies, company.profiles).review("company-n", company.source)), ())

    # ---- a later JDL master re-evaluates the decision
    def test_parent_only_stops_working_when_jdl_gets_a_subaccount_under_the_parent(self):
        company, source = self._ready_company()
        resolved = company.resolved()
        added = JdlSubaccountIdentity("手数料", "新補助", "0009", "0009", "新補助", True,
                                      parent_account_code="8681", target_name="新補助")
        later = replace(resolved.context, subaccounts=resolved.context.subaccounts + (added,))
        assessment = YayoiJdlWorkflow().assess(source, resolved.profile, later)
        self.assertLess(assessment.ready_journals, len(assessment.journal_blockers))
        blockers = assessment.blocker_counts()
        self.assertTrue({"HUMAN:SUBACCOUNT_DEFAULT", "HUMAN:SUBACCOUNT_MAPPING"} & set(blockers), blockers)
        output = self.root / "ready" / "late.csv"
        prepared = YayoiJdlWorkflow().prepare(input_path=source, output_path=output, profile=resolved.profile,
                                              context=later, company_setting_validated=resolved.available)
        self.assertIsNot(prepared.summary.readiness, FirstReleaseReadiness.READY)

    # ---- the form-side view model
    def test_policy_rows_respect_what_the_open_form_can_carry(self):
        groups = policy.parent_groups(self.review())
        rows = {r.group.source_parent: r for r in policy.policy_rows(groups)}
        self.assertTrue(rows[FEE].parent_only_allowed)
        self.assertEqual((rows[FEE].subaccounts, rows[FEE].preserve_allowed), (2, False))
        self.assertIn("補助科目がありません", rows[FEE].preserve_reason)
        self.assertFalse(rows[BANK].parent_only_allowed)
        blocked = {r.group.source_parent: r for r in policy.policy_rows(groups, lambda _item: False)}
        self.assertFalse(blocked[FEE].parent_only_allowed)  # the form cannot carry it: not offered

    def test_unconfirmed_parent_is_undecided(self):
        (self.root / "u").mkdir()
        company = Company(self.root, "company-u", write_import(self.root / "u", source_rows()), IMPORT, floor_context())
        service = CompanyMappingUpdateService(company.companies, company.profiles)
        groups = policy.parent_groups(service.review("company-u", company.source))
        self.assertTrue(groups)
        for group in groups:
            self.assertFalse(group.parent_confirmed)
            self.assertFalse(group.parent_only_possible and group.parent_target is None)
        undecided = [g for g in groups if g.parent_target is None]
        self.assertTrue(undecided)  # parents with no exact JDL candidate wait for the parent decision
        for group in undecided:
            self.assertEqual({m.klass for m in group.members}, {policy.PARENT_UNDECIDED})
            self.assertIn("親科目", group.reason_parent_only_forbidden)


if __name__ == "__main__":
    unittest.main()

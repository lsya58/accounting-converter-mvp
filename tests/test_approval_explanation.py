"""Approval screen content (application/approval_explanation) and the controller behind it. Synthetic data only."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.application import approval_explanation as ex
from accounting_converter.application import approval_ledger as al
from accounting_converter.application import noncredit_approval as nc
from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
from accounting_converter.ui.controllers import AccountingConverterController
from tests.test_approval_ledger import COMPANY, Env, store_digest
from tests.test_noncredit_approval import NC10, evidence_covers_test_company


def controller_for(env):
    return AccountingConverterController(profile_store=env.fixture.profiles, company_store=env.fixture.companies,
                                         preferences_store=ApplicationPreferencesStore(env.root / "prefs.json"))


def extras(env):
    """The two private inputs: a 摘要末尾空白 record and an operating-policy catalog (synthetic)."""
    record = env.root / "record.json"
    record.write_text(json.dumps({"rows": [{"x": 1}], "rows_count": 3, "journals_count": 2, "evidence_ids": ["EVID-X"],
                                  "rows_sha256": "0" * 64, "files": {"candidate": {"sha256": "a" * 64}}}),
                      encoding="utf-8")
    line = next(int(l.metadata["journal_row_number"]) for e in env.entries()
                if e.metadata.get("yayoi_voucher_number") == "2" for l in e.lines)
    catalog = env.root / "catalog.json"
    catalog.write_text(json.dumps({"company_id": COMPANY, "policies": [
        {"item_id": "POLICY-OVERSEAS", "journal": env.label(2), "lines": [line], "change": "海外購入の方針（架空）",
         "evidence_ids": ["EVID-POLICY"]}]}), encoding="utf-8")
    return record, catalog


class ExplanationTest(unittest.TestCase):
    def _all(self, env):
        record, catalog = extras(env)
        overview = controller_for(env).approval_overview(COMPANY, env.source, trailing_space_record=record,
                                                         catalog_path=catalog)
        return overview, overview["explanations"]

    def test_every_item_answers_the_accountants_questions_and_keeps_the_technical_facts(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            overview, explanations = self._all(env)
            kinds = {item.kind for item, _ in overview["items"]}
            self.assertEqual(kinds, {al.KIND_SPLIT, al.KIND_NONCREDIT, al.KIND_TRAILING_SPACE, al.KIND_POLICY})
            self.assertEqual(overview["guides"], ())
            self.assertTrue(all(state == "未判断" for _, state in overview["items"]))
            for item, _ in overview["items"]:
                e = explanations[item.item_id]
                for field in ("what", "yayoi", "jdl", "lost", "alternatives", "needs", "technical"):
                    self.assertTrue(getattr(e, field), (item.item_id, field))
                self.assertTrue(e.question)
                technical = dict(e.technical)
                self.assertEqual(technical["会社ID"], COMPANY)
                self.assertIn("根拠Evidence ID", technical)

    def test_noncredit_states_the_yayoi_class_the_jdl_treatment_and_what_is_lost(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            _, explanations = self._all(env)
            e = explanations[f"NONCREDIT-{env.label(2)}"]
            text = "\n".join((*e.what, *e.yayoi, *e.jdl, *e.lost, e.question))
            for needle in ("課対仕入10%", "区分記載", "控除不可", "内税", "税額 0円", "非仕入", "コード34", "空欄",
                           "非課税仕入", "区別", "申告上同じ扱い"):
                self.assertIn(needle, text)
            self.assertIn(nc.LOSS_TEXT, e.lost)
            lost = "\n".join(e.lost)
            self.assertIn("今回検証済みのJDL CSV取込方式では、元の「控除不可」の区別をそのまま保持できません", lost)
            self.assertIn("別の入力方法については未確認です", lost)
            self.assertNotIn("取り込む方法はありません", lost)          # no claim beyond the Evidence
            needs = "\n".join(e.needs)
            self.assertIn("EQUIVALENCE_CONFIRMED", needs)
            self.assertIn("運用方針", needs)            # the policy is named but not a substitute
            self.assertEqual(dict(e.technical)["元の税区分（弥生）"], NC10)
            # the operating policy is related, never listed as another approval this journal needs
            self.assertIn("POLICY-OVERSEAS", "\n".join(e.related))
            self.assertNotIn("別の承認も必要です: POLICY", needs)
            self.assertIn("この個別承認だけです", needs)

    def test_the_policy_is_explained_as_record_only_and_different_from_the_individual_approval(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            _, explanations = self._all(env)
            e = explanations["POLICY-OVERSEAS"]
            self.assertTrue(e.record_only)
            text = "\n".join((*e.jdl, *e.needs))
            for needle in ("変換には使われません", "個別承認", "自動で当てはめません", "BLOCKのまま"):
                self.assertIn(needle, text)

    def test_split_lists_each_journal_and_points_to_the_other_approval_a_journal_needs(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            _, explanations = self._all(env)
            e = explanations["SPLIT-V1"]
            self.assertEqual(len(e.what), 2)                                    # vouchers 1 and 3
            self.assertTrue(all("1伝票・" in line and "伝票に分割" in line for line in e.what))
            self.assertIn(f"NONCREDIT-{env.label(3)}", "\n".join(e.related))
            self.assertIn("今後の仕訳には及びません", e.question)

    def test_trailing_space_is_never_recordable_from_here(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            _, explanations = self._all(env)
            e = explanations["TRAILING-SPACE"]
            self.assertTrue(e.record_only)
            self.assertIn("jdl_description_trailing_space_acceptance", "\n".join(e.needs))

    def test_the_two_other_route_items_are_shown_as_guides_when_their_inputs_are_not_loaded(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            overview = controller_for(env).approval_overview(COMPANY, env.source)
            self.assertEqual([g.guide_id for g in overview["guides"]], ["TRAILING-SPACE", "POLICY"])
            text = "\n".join(line for g in overview["guides"] for line in g.lines)
            self.assertIn("jdl_description_trailing_space_acceptance", text)
            self.assertIn("04_摘要末尾空白_承認資料.md", text)
            self.assertIn("承認条件も変わりません", text)


class OverviewSafetyTest(unittest.TestCase):
    def test_overview_and_preview_write_nothing_and_a_foreign_catalog_is_refused(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            controller = controller_for(env)
            record, catalog = extras(env)
            digest = store_digest(env.root)
            controller.approval_overview(COMPANY, env.source, trailing_space_record=record, catalog_path=catalog)
            preview, view = controller.approval_preview_view(COMPANY, env.source, ["SPLIT-V1"])
            self.assertEqual(preview.problems, ())            # the real resolve path passes the company check
            self.assertEqual(store_digest(env.root), digest)
            self.assertFalse(al.default_ledger_path(env.root, COMPANY).exists())
            self.assertFalse(env.ledger.path.exists())
            foreign = env.root / "foreign.json"
            foreign.write_text(json.dumps({"company_id": "company-other", "policies": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "別の会社"):
                controller.approval_overview(COMPANY, env.source, catalog_path=foreign)
            with self.assertRaisesRegex(ValueError, "承認待ちにない"):
                controller.approval_preview_view(COMPANY, env.source, ["NOPE"])

    def test_a_broken_ledger_is_reported_on_the_screen_data_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            path = al.default_ledger_path(env.root, COMPANY)
            path.parent.mkdir(parents=True)
            path.write_text('{"broken": true}\n', encoding="utf-8")
            overview = controller_for(env).approval_overview(COMPANY, env.source)
            self.assertIn("改変", overview["ledger_error"])
            self.assertTrue(all(state == "台帳を読めません" for _, state in overview["items"]))
            self.assertEqual(path.read_text(encoding="utf-8"), '{"broken": true}\n')   # not repaired


class PreviewViewTest(unittest.TestCase):
    def test_split_only_leaves_the_journal_that_needs_a_noncredit_approval_and_says_so(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            _, view = controller_for(env).approval_preview_view(COMPANY, env.source, ["SPLIT-V1"])
            self.assertEqual((view.ready_before, view.block_before), (view.ready_before, view.block_before))
            self.assertEqual([r.label for r in view.released], [env.label(1)])
            self.assertEqual([r.label for r in view.remaining], [env.label(3)])
            self.assertEqual((view.released[0].voucher, view.released[0].date), ("1", "2026-05-10"))
            row = view.remaining[0]
            self.assertTrue(row.reasons)
            self.assertTrue(any(f"NONCREDIT-{env.label(3)}" in hint and "未承認" in hint for hint in row.hints))
            self.assertIn("控除不可の未承認条件", view.expected_note)
            self.assertEqual(view.ready_after, view.ready_before + 1)

    def test_after_both_approvals_only_conditions_that_approvals_cannot_resolve_are_left_and_named(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            ids = ["SPLIT-V1", f"NONCREDIT-{env.label(3)}"]
            _, view = controller_for(env).approval_preview_view(COMPANY, env.source, ids)
            self.assertEqual([r.label for r in view.released], [env.label(1)])
            row = view.remaining[0]                      # this synthetic shape has an unverified layout after the split
            self.assertEqual(row.label, env.label(3))
            self.assertFalse(any("未承認" in hint for hint in row.hints))     # no approval is missing any more
            self.assertTrue(any("承認だけでは解消しません" in hint for hint in row.hints))
            self.assertTrue(row.reasons)
            self.assertTrue(any("EQUIVALENCE_CONFIRMED" in text for text in view.prerequisites))

    def test_noncredit_preview_states_the_missing_prerequisites_and_the_technical_scope(self):
        with tempfile.TemporaryDirectory() as directory:    # the Evidence names only the real company
            env = Env(directory)
            _, view = controller_for(env).approval_preview_view(COMPANY, env.source, [f"NONCREDIT-{env.label(2)}"])
            text = "\n".join(view.prerequisites)
            self.assertIn("EQUIVALENCE_CONFIRMED", text)
            self.assertIn("技術確認の範囲外", text)
            self.assertEqual(view.released, ())
            self.assertEqual(view.ready_after, view.ready_before)

    def test_the_zero_tax_journal_and_record_only_items_never_release_anything(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            record, catalog = extras(env)
            controller = controller_for(env)
            ids = ["POLICY-OVERSEAS", "TRAILING-SPACE"]
            preview, view = controller.approval_preview_view(COMPANY, env.source, ids, record, catalog)
            self.assertEqual((view.released, view.ready_after, view.ready_before), ((), view.ready_before, view.ready_before))
            every = controller.approval_preview(
                COMPANY, env.source, [i.item_id for i, _ in controller.approval_items(COMPANY, env.source, None, record, catalog)],
                record, catalog)
            zero = next(e for e in env.entries() if e.metadata.get("yayoi_voucher_number") == "4")
            self.assertNotIn(zero.id, preview.ready_after_ids)
            self.assertNotIn(zero.id, every.ready_after_ids)      # no item, and no combination, releases voucher 4


if __name__ == "__main__":
    unittest.main()

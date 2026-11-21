"""設定ページ・対応の確認 (Phase 3C): the pure view data and the read-only controller methods behind them.

Synthetic data only. Viewing never writes: every controller read is checked against a byte listing of the store."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from accounting_converter.application.company_mapping_update import CompanyMappingUpdateItem
from accounting_converter.application.moneyforward_profile_setup import TaxMappingSetupItem, TaxMappingSetupReview
from accounting_converter.ui import mapping_review_view as mv
from accounting_converter.ui import settings_view as sv
from tests.test_unmigrated_view import Env, listing
from tests.test_yayoi_ready_only import COMPANY


def facts(**changes) -> sv.SettingsFacts:
    base = dict(
        company_id="c", display_name="合成会社", source_kind=sv.YAYOI, status="AVAILABLE", context_loaded=True,
        product="JDL IBEX 出納帳", version="35.5", context_confirmed=True, master_state="設定済み",
        master_updated_at="2026/11/01", accounts=99, subaccounts=280, departments=0, unusable_subaccounts=9,
        department_processing=False, tax_mode="TAXABLE_TAX_EXCLUDED", taxation_method="STANDARD",
        credit_method="PROPORTIONAL", sales_rounding="CEILING", purchase_rounding="HALF_UP", voucher_row_limit=16,
        verified_row_limits=(16,), account_mappings=(70, 70), subaccount_mappings=(10, 10), tax_mappings=(11, 11),
        information_fields_confirmed=3, profile_id="p-rowlimit", created_at="2026/11/01 10:00",
        updated_at="2026/11/02 10:00")
    base.update(changes)
    return sv.SettingsFacts(**base)


def rows(overview, section):
    return {r.key: r for r in next(s for s in overview.sections if s.key == section).rows}


class SettingsOverviewTest(unittest.TestCase):
    def test_six_sections_in_the_required_order(self):
        overview = sv.build_settings_overview(facts())
        self.assertEqual([s.key for s in overview.sections],
                         ["company", "software", "accounts", "tax", "conditions", "technical"])
        self.assertEqual([s.title for s in overview.sections],
                         ["会社の基本情報", "会計ソフト・変換先", "科目・補助科目", "消費税設定", "変換条件", "技術情報・設定履歴"])
        self.assertEqual(overview.next_steps, ())
        self.assertEqual(overview.message[0], "success")

    def test_no_company_is_a_clear_empty_state_not_default_values(self):
        overview = sv.build_settings_overview(None)
        self.assertFalse(overview.has_company)
        self.assertEqual(overview.sections, ())
        self.assertEqual(overview.next_steps[0].action, sv.ACT_ADD_COMPANY)

    def test_an_unconfirmed_tax_context_is_unconfirmed_and_blocks_everything_by_its_own_words(self):
        overview = sv.build_settings_overview(facts(
            context_loaded=False, context_draft=True, context_confirmed=False, product="", version="",
            accounts=None, tax_mode="", taxation_method="", credit_method="", sales_rounding="",
            purchase_rounding="", voucher_row_limit=None))
        tax = rows(overview, "tax")
        self.assertEqual(tax["tax_context"].state, sv.UNCONFIRMED)
        self.assertIn("BLOCK", tax["tax_context"].impact)
        self.assertEqual(rows(overview, "software")["context"].state, sv.UNCONFIRMED)
        self.assertEqual(rows(overview, "conditions")["row_limit"].state, sv.UNCONFIRMED)
        self.assertNotIn("16", rows(overview, "conditions")["row_limit"].value)       # never pre-filled
        self.assertEqual(overview.message[0], "warning")
        self.assertEqual(overview.next_steps[0].action, sv.ACT_TAX_CONTEXT)
        actions = [s.action for s in overview.next_steps]
        self.assertEqual(len(actions), len(set(actions)))                              # one button per screen

    def test_row_limit_states_16_verified_64_waiting_for_evidence_none_unconfirmed(self):
        by_limit = {limit: rows(sv.build_settings_overview(facts(voucher_row_limit=limit)), "conditions")["row_limit"]
                    for limit in (16, 64, None)}
        self.assertEqual(by_limit[16].state, sv.CONFIRMED)
        self.assertEqual(by_limit[64].state, sv.WAITING_EVIDENCE)       # not "unconfirmed": nobody can confirm it here
        self.assertIn("BLOCK", by_limit[64].note)
        self.assertEqual(by_limit[None].state, sv.UNCONFIRMED)
        overview = sv.build_settings_overview(facts(voucher_row_limit=64))
        self.assertEqual(overview.message[0], "warning")
        self.assertIn("実機", overview.message[1])

    def test_confirmed_never_means_default_and_unreadable_is_not_unconfirmed(self):
        overview = sv.build_settings_overview(facts(sales_rounding="", purchase_rounding="UNCONFIRMED"))
        self.assertEqual(rows(overview, "tax")["rounding"].state, sv.UNCONFIRMED)
        overview = sv.build_settings_overview(facts(account_mappings=None, errors=("対応設定を読み込めませんでした",)))
        self.assertEqual(rows(overview, "accounts")["accounts"].state, sv.UNREADABLE)
        self.assertEqual(overview.message[0], "error")
        self.assertIn("変更していません", overview.message[1])

    def test_saved_mapping_counts_are_not_presented_as_a_confirmation_of_the_source(self):
        none_saved = rows(sv.build_settings_overview(facts(account_mappings=(0, 0))), "accounts")["accounts"]
        self.assertEqual((none_saved.state, none_saved.state_text), (sv.NOT_APPLICABLE, "未登録"))
        partly = rows(sv.build_settings_overview(facts(account_mappings=(3, 5))), "accounts")["accounts"]
        self.assertEqual(partly.state, sv.UNCONFIRMED)
        self.assertIn("保存済み 5件のうち確認済み 3件", partly.value)

    def test_source_specific_rows(self):
        mf = rows(sv.build_settings_overview(facts(source_kind=sv.MONEYFORWARD, trade_partner_confirmed=False,
                                                    information_fields_confirmed=None)), "conditions")
        self.assertEqual(mf["trade_partner"].state, sv.UNCONFIRMED)
        self.assertNotIn("information", mf)
        yayoi = rows(sv.build_settings_overview(facts()), "conditions")
        self.assertIn("information", yayoi)
        self.assertNotIn("trade_partner", yayoi)
        jdl = rows(sv.build_settings_overview(facts(source_kind=sv.JDL, information_fields_confirmed=None)), "conditions")
        self.assertIn("jdl_migration", jdl)
        self.assertEqual(rows(sv.build_settings_overview(facts(source_kind=sv.UNSUPPORTED)), "software")["source"].state,
                         sv.UNREADABLE)

    def test_exempt_and_simplified_show_what_applies(self):
        exempt = rows(sv.build_settings_overview(facts(tax_mode="EXEMPT", taxation_method="", credit_method="")), "tax")
        self.assertEqual(exempt["taxation"].state, sv.NOT_APPLICABLE)
        simplified = rows(sv.build_settings_overview(facts(taxation_method="SIMPLIFIED", simplified_category="THIRD")), "tax")
        self.assertEqual(simplified["simplified"].value, "第三種事業")
        self.assertNotIn("credit", simplified)

    def test_every_row_that_changes_ready_says_how_and_technical_rows_are_never_counted(self):
        overview = sv.build_settings_overview(facts())
        for section in overview.sections:
            if section.key == "technical":
                self.assertTrue(all(r.technical for r in section.rows))
                self.assertEqual(section.counts(), (0, 0))
                continue
            for row in section.rows:
                if row.action and row.state != sv.NOT_APPLICABLE:
                    self.assertTrue(row.impact, row.key)
        self.assertEqual(overview.confirmed, overview.needed)

    def test_overview_is_a_value_so_a_change_is_detected_by_comparison(self):
        a = sv.build_settings_overview(facts())
        self.assertEqual(a, sv.build_settings_overview(facts()))
        self.assertNotEqual(a, sv.build_settings_overview(facts(voucher_row_limit=64)))
        self.assertNotEqual(a, sv.build_settings_overview(facts(profile_fingerprint="x" * 64)))   # any saved change


def item(mapping_type="ACCOUNT", source="現金", **changes) -> CompanyMappingUpdateItem:
    base = dict(key=f"{mapping_type}|{source}", mapping_type=mapping_type, source_value=source, parent_account=None,
                available_targets=("現金",), exact_candidate="現金", affected_journal_count=3)
    base.update(changes)
    return CompanyMappingUpdateItem(**base)


class Review:
    def __init__(self, items=(), **fields):
        self.items = tuple(items)
        self.descriptions = ()
        self.logical_journal_count = 100
        self.unsupported_shape_count = 0
        self.optional_field_blocker_count = 0
        self.source_is_yayoi = False
        self.information_fields = ()
        for key, value in fields.items():
            setattr(self, key, value)


class Field:
    def __init__(self, field, journals, meaning=""):
        self.field, self.journals, self.meaning = field, journals, meaning
        self.confirmed = bool(meaning)


class SettingsSummaryTest(unittest.TestCase):
    def test_section_summaries_show_the_main_values(self):
        overview = sv.build_settings_overview(facts())
        by_key = {s.key: s.summary for s in overview.sections}
        self.assertIn("勘定科目の対応", by_key["accounts"])
        self.assertIn("補助科目の対応", by_key["accounts"])
        self.assertTrue(by_key["conditions"].startswith("振替伝票入力行数: "))
        self.assertIn("利用できます", by_key["company"])


class MappingReviewViewTest(unittest.TestCase):
    def view(self, review, **snapshot):
        return mv.build_mapping_review(mv.MappingSnapshot(review=review, **snapshot))

    def test_unconfirmed_first_confirmed_last_and_the_kinds_of_waiting_are_separate(self):
        review = Review([
            item(source="売上", already_confirmed=True),
            item(source="雑費"),
            item(source="特殊科目", blocker_code="JDL-ACCOUNT-MISSING", blocker_reason="JDLに同名の科目がありません"),
            item("SUBACCOUNT", "補助A", parent_account="売掛金", available_targets=(), subaccount_targets_by_parent=()),
            item("SUBACCOUNT", "補助B", parent_account="売掛金", already_confirmed=True),
            item("SUBACCOUNT", "補助C", parent_account="買掛金", blocker_code="NO-SUB"),
        ])
        view = self.view(review)
        accounts = view.group(mv.G_ACCOUNT)
        self.assertEqual([r.state for r in accounts.rows], [mv.UNCONFIRMED, mv.NEEDS_JDL, mv.CONFIRMED])
        self.assertEqual(len(accounts.pending), 2)
        self.assertEqual(accounts.confirmed[0].source, "売上")
        subs = view.group(mv.G_SUBACCOUNT)
        self.assertEqual([r.state for r in subs.rows], [mv.WAITING_PARENT, mv.NEEDS_JDL, mv.CONFIRMED])
        self.assertEqual(len({mv.STATE_WORDS[s] for s in (mv.UNCONFIRMED, mv.NEEDS_JDL, mv.NEEDS_EVIDENCE)}), 3)
        self.assertEqual(view.message[0], "warning")
        self.assertEqual([step[1] for step in view.next_steps], [mv.G_ACCOUNT, mv.G_SUBACCOUNT])   # only what a person can do

    def test_tax_human_confirmable_vs_missing_evidence_vs_confirmed_vs_not_yet_registered(self):
        tax_review = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("課税仕入 10%", "課税仕入10%", "課仕10%", human_confirmable=True, action_owner="HUMAN",
                                blocker_code="HUMAN-CONFIRM", affected_row_count=40),
            TaxMappingSetupItem("特殊税", reason="実機の確認がありません", affected_row_count=2),
        ), context_compatible=True)
        view = self.view(Review(), tax_review=tax_review,
                         saved_tax=(("課税売上 10%", "課税売上10%"),),
                         observed_tax=(("課税仕入 10%", 40), ("特殊税", 2), ("課税売上 10%", 9), ("新税区分", 1)))
        rows_by_source = {r.source: r for r in view.group(mv.G_TAX).rows}
        self.assertEqual(rows_by_source["課税仕入 10%"].state, mv.UNCONFIRMED)
        self.assertEqual(rows_by_source["特殊税"].state, mv.NEEDS_EVIDENCE)         # not a person's job
        self.assertEqual(rows_by_source["課税売上 10%"].state, mv.CONFIRMED)
        self.assertEqual(rows_by_source["課税売上 10%"].candidate, "課税売上10%")
        self.assertEqual(rows_by_source["新税区分"].state, mv.UNCONFIRMED)           # never silently "confirmed"
        self.assertTrue(all(r.unit == "明細行" for r in rows_by_source.values()))   # journal lines, not CSV rows
        self.assertEqual(sum(len(g.pending) for g in view.groups), 3)
        self.assertEqual([step[1] for step in view.next_steps], [mv.G_TAX])

    def test_every_state_has_its_own_next_action_and_evidence_cannot_be_confirmed_on_screen(self):
        tax_review = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("特殊税", reason="この税区分の実機の確認がありません", affected_row_count=7),
        ), context_compatible=True)
        view = self.view(Review([item(source="雑費"), item(source="特殊科目", blocker_code="NO-ACCOUNT"),
                                 item(source="売上", already_confirmed=True)]),
                         tax_review=tax_review, observed_tax=(("特殊税", 7),))
        waiting = view.evidence_waiting
        self.assertEqual([(r.source, r.usage) for r in waiting], [("特殊税", "7明細行")])   # basis + size, own unit
        self.assertIn("Evidence", waiting[0].next_action)
        self.assertIn("確認済みにできません", waiting[0].next_action)
        self.assertEqual(waiting[0].reason, "この税区分の実機の確認がありません")
        rows = {r.source: r for r in view.group(mv.G_ACCOUNT).rows}
        self.assertIn("科目を確認", rows["雑費"].next_action)                    # a person confirms on the screen
        self.assertIn("JDLで科目・補助を登録", rows["特殊科目"].next_action)     # JDL registration, not a person
        self.assertIn("対応は不要", rows["売上"].next_action)
        actions = {mv.next_action(mv.G_TAX, s) for s in (mv.UNCONFIRMED, mv.NEEDS_JDL, mv.NEEDS_EVIDENCE, mv.CONFIRMED)}
        self.assertEqual(len(actions), 4)                                        # never the same words for two states
        self.assertIn("CSVの行数ではなく", mv.COUNT_NOTE)

    def test_the_accountant_card_summary_comes_from_the_rows_and_never_says_approved(self):
        """Phase 5B: the summary (state, target, 明細行 per item, technical Evidence, missing, next) from the view model."""
        signoff = "YAYOI-JDL-TAX-NONCREDIT-TAX-ACCOUNTANT-SIGNOFF-REQUIRED"
        evidence = "EVID-SYNTHETIC-NONCREDIT"
        tax_review = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("課対仕入10%｜区分記載｜控除不可", target_display="非仕入（税区空欄）※税理士確認後のみ",
                                evidence_id=evidence, reason="技術確認は済み。申告上の扱いは税理士の確認が必要。区別はCSVに残りません。",
                                action_owner="HUMAN", blocker_code=signoff, affected_row_count=3),
            TaxMappingSetupItem("課対仕入8%（軽）｜区分記載｜控除不可", target_display="非仕入（税区空欄）※税理士確認後のみ",
                                evidence_id=evidence, reason="技術確認は済み。", action_owner="HUMAN", blocker_code=signoff,
                                affected_row_count=1),
        ), context_compatible=True)
        view = self.view(Review(), tax_review=tax_review, observed_tax=(
            ("課対仕入10%｜区分記載｜控除不可", 3), ("課対仕入8%（軽）｜区分記載｜控除不可", 1)))
        summary = mv.accountant_summary(view.accountant_waiting)
        self.assertEqual(summary.target, "税区分 2項目")
        self.assertEqual(summary.lines, ("課対仕入10%｜区分記載｜控除不可: 3明細行", "課対仕入8%（軽）｜区分記載｜控除不可: 1明細行"))
        self.assertTrue(summary.evidence.startswith("確認済み"))
        self.assertIn("税理士の判断と、正式なSIGNOFFの記録", summary.missing)
        self.assertIn("仕訳ごと", summary.next_action)
        self.assertIn("未承認", summary.state)
        for text in (summary.state, summary.evidence, summary.missing, summary.next_action):
            self.assertNotIn("承認済み", text)
        facts = dict(summary.details[0][1])                      # nothing of the details is dropped
        self.assertEqual(facts["変換先の候補"], "非仕入（税区空欄）※税理士確認後のみ")
        self.assertIn("区別はCSVに残りません", facts["根拠と理由"])
        self.assertEqual(facts["JDL技術Evidence"], evidence)
        self.assertIn(signoff, facts["確認コード"])
        self.assertTrue(any("CLI" in step for step in summary.procedure))
        # without the technical Evidence id the summary says so (never 確認済み by default)
        bare = mv.accountant_summary([replace(view.accountant_waiting[0], evidence="")])
        self.assertFalse(bare.evidence.startswith("確認済み"))
        self.assertIsNone(mv.accountant_summary(()))

    def test_an_accountant_signoff_wait_is_not_a_jdl_evidence_wait(self):
        """Company A's 控除不可: the JDL technical Evidence exists; what is missing is the accountant's sign-off."""
        signoff = "YAYOI-JDL-TAX-NONCREDIT-TAX-ACCOUNTANT-SIGNOFF-REQUIRED"
        tax_review = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("課対仕入10%｜区分記載｜控除不可", reason="JDL実機の技術確認は済み。税理士の確認が必要です。",
                                action_owner="HUMAN", blocker_code=signoff, affected_row_count=2),
            TaxMappingSetupItem("課対仕入8%（軽）｜区分記載｜控除不可", reason="JDL実機の技術確認は済み。税理士の確認が必要です。",
                                action_owner="HUMAN", blocker_code=signoff, affected_row_count=1),
            TaxMappingSetupItem("別の税区分", reason="実機の確認がありません", affected_row_count=3),     # SYSTEM_EVIDENCE
            TaxMappingSetupItem("設定違い", action_owner="SYSTEM_IMPLEMENTATION", blocker_code="MF-JDL-TAX-ROUTE-MISMATCH",
                                reason="会社設定の入力元・変換先形式が一致していません。", affected_row_count=4),
        ), context_compatible=True)
        view = self.view(Review(), tax_review=tax_review, observed_tax=(
            ("課対仕入10%｜区分記載｜控除不可", 2), ("課対仕入8%（軽）｜区分記載｜控除不可", 1), ("別の税区分", 3), ("設定違い", 4)))
        rows = {r.source: r for r in view.group(mv.G_TAX).rows}
        self.assertEqual(rows["課対仕入10%｜区分記載｜控除不可"].state, mv.NEEDS_ACCOUNTANT)
        self.assertEqual(rows["課対仕入8%（軽）｜区分記載｜控除不可"].state, mv.NEEDS_ACCOUNTANT)
        self.assertEqual(rows["別の税区分"].state, mv.NEEDS_EVIDENCE)             # only this one lacks JDL Evidence
        self.assertEqual(rows["設定違い"].state, mv.UNCONFIRMED)                   # neither Evidence nor sign-off
        self.assertEqual([r.source for r in view.accountant_waiting],
                         ["課対仕入10%｜区分記載｜控除不可", "課対仕入8%（軽）｜区分記載｜控除不可"])
        self.assertEqual([r.source for r in view.evidence_waiting], ["別の税区分"])
        waiting = rows["課対仕入10%｜区分記載｜控除不可"]
        self.assertIn("SIGNOFF", waiting.next_action)
        self.assertIn("CLI", waiting.next_action)
        self.assertIn("BLOCK", waiting.next_action)
        self.assertNotIn("Evidence が記録される", waiting.next_action)
        self.assertNotIn("実機で取込を確認", waiting.next_action)
        self.assertEqual(len({mv.STATE_WORDS[s] for s in (mv.UNCONFIRMED, mv.NEEDS_JDL, mv.NEEDS_EVIDENCE,
                                                         mv.NEEDS_ACCOUNTANT)}), 4)
        self.assertEqual(waiting.usage, "2明細行")

    def test_nothing_pending_is_a_success_and_confirmed_stay_reviewable(self):
        view = self.view(Review([item(already_confirmed=True)]))
        self.assertEqual(view.message[0], "success")
        self.assertEqual(view.pending_total, 0)
        self.assertEqual(len(view.group(mv.G_ACCOUNT).confirmed), 1)
        self.assertEqual(view.next_steps, ())

    def test_retention_descriptions_notes_and_shape_evidence_are_distinguished(self):
        review = Review(source_is_yayoi=True, information_fields=(Field("部門", 5), Field("付箋1", 2, "色分け")),
                        unsupported_shape_count=3)
        view = self.view(review, tax_context_ready=False)
        retention = {r.source: r for r in view.group(mv.G_RETENTION).rows}
        self.assertEqual((retention["部門"].state, retention["付箋1"].state), (mv.UNCONFIRMED, mv.CONFIRMED))
        self.assertEqual(view.shape_blocked, 3)
        self.assertTrue(any("税設定が未確認" in n for n in view.notes))
        self.assertTrue(any("3仕訳" in n and "確認がない" in n for n in view.notes))

    def test_a_candidate_is_shown_with_its_basis_never_as_a_decision(self):
        class Candidate:
            code, name, kind, basis, warning = "1111", "普通預金", "EXACT", "名前が同じ", ""
        row = self.view(Review([item(source="普通預金", exact_candidate=None, candidates=(Candidate(),))])
                        ).group(mv.G_ACCOUNT).rows[0]
        self.assertEqual((row.state, row.candidate), (mv.UNCONFIRMED, "1111 普通預金"))
        self.assertIn("名前が同じ", row.basis)


class ControllerReadOnlyTest(unittest.TestCase):
    """The controller reads behind the pages write nothing (byte listing of the whole store before / after)."""

    def test_settings_facts_are_read_only_and_describe_the_saved_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            before = listing(env.root)
            found = env.controller.company_settings_facts(COMPANY)
            self.assertEqual(listing(env.root), before)
            self.assertEqual(found.company_id, COMPANY)
            self.assertEqual(found.source_kind, sv.YAYOI)
            self.assertTrue(found.context_loaded)
            self.assertFalse(found.context_draft)
            self.assertEqual(found.errors, ())
            self.assertIn(16, found.verified_row_limits)
            self.assertTrue(found.profile_id and found.profile_fingerprint and found.context_fingerprint)
            overview = sv.build_settings_overview(found)
            self.assertEqual(overview.company_name, found.display_name)
            self.assertEqual(env.controller.company_settings_facts(None), None)
            self.assertEqual(listing(env.root), before)

    def test_settings_facts_for_an_unknown_company_report_an_error_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            found = env.controller.company_settings_facts("company-does-not-exist")
            self.assertTrue(found.errors)
            self.assertEqual((found.created_at, found.updated_at), ("", ""))       # a placeholder, not real dates
            overview = sv.build_settings_overview(found)
            self.assertEqual(overview.message[0], "error")
            self.assertEqual(rows(overview, "company")["usable"].state, sv.UNREADABLE)

    def test_mapping_snapshot_is_read_only_and_matches_the_confirmation_screen_review(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, write=False)
            before = listing(env.root)
            snapshot = env.controller.company_mapping_review_snapshot(COMPANY, env.run.source)
            self.assertEqual(listing(env.root), before)                   # nothing registered, nothing saved
            screen = env.controller.review_company_mapping_updates(COMPANY, env.run.source)
            confirmed = {i.key for i in snapshot.review.items if i.already_confirmed}
            self.assertEqual({i.key for i in snapshot.review.items} - confirmed, {i.key for i in screen.items})
            view = mv.build_mapping_review(snapshot)
            self.assertEqual(view.journals, snapshot.review.logical_journal_count)
            pending_accounts = {r.source for r in view.group(mv.G_ACCOUNT).pending}
            self.assertEqual(pending_accounts, {i.source_value for i in screen.items if i.mapping_type == "ACCOUNT"})
            self.assertEqual(listing(env.root), before)


if __name__ == "__main__":
    unittest.main()

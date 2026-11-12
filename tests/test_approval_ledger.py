"""D0: pending approvals, preview, ledger and guarded apply (application/approval_ledger). Synthetic data only."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from accounting_converter.application import approval_ledger as al
from accounting_converter.application import noncredit_approval as nc
from accounting_converter.application import voucher_split as vs
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_sources import detect_format
from tests.test_noncredit_approval import NC10, evidence_covers_test_company, noncredit
from tests.test_voucher_split import card_voucher
from tests.test_yayoi_jdl_workflow import OUTSIDE, SALES, YAYOI
from tests.test_yayoi_journal_report_parser import build, detail, write
from tests.test_yayoi_scoped_workflow import DATE, make

COMPANY = "company-yayoi"


def multi_reason(voucher=3, debits=26):
    """Over the 16-row limit (split rule shape) AND one 控除不可 line: needs BOTH approvals (like journal 425)."""
    rows = card_voucher(debits, voucher=voucher)
    rows[5] = detail(DATE, voucher, debit=(YAYOI["fee"], "", "課対仕入10%", 1100, 0), invoice="区分記載",
                     credit_ratio="控除不可", description="控除不可明細", number=voucher)
    return rows


def zero_tax(voucher=4):
    """A 1-yen 売上10% line with a written tax 0 (like voucher 1240): no Evidence; no approval can release it."""
    return [detail(DATE, voucher, debit=(YAYOI["cash"], "", OUTSIDE, 1, None),
                   credit=(YAYOI["sales"], "", SALES, 1, 0), description="端数", number=voucher)]


def rows():
    return card_voucher(26, voucher=1) + [noncredit(1399, voucher=2)] + multi_reason() + zero_tax()


def write_in(directory: Path, source_rows) -> Path:
    directory.mkdir(parents=True)
    return write(directory, build(source_rows))


def judge_report(directory, result="EQUIVALENCE_CONFIRMED") -> Path:
    path = Path(directory) / "judge.json"
    path.write_text(json.dumps({"cases": {case: {"result": result} for case in nc.TECHNICAL_EVIDENCE.probe_cases.values()}}),
                    encoding="utf-8")
    return path


def store_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for name in ("profiles", "companies") for p in (root / name).rglob("*") if p.is_file()):
        digest.update(path.as_posix().encode() + path.read_bytes())
    return digest.hexdigest()


class Env:
    def __init__(self, directory, source_rows=None):
        self.root = Path(directory)
        self.fixture = make(directory, source_rows if source_rows is not None else rows())
        self.source = self.fixture.source
        self.ledger = al.ApprovalLedger(self.root / "ledger" / "approvals.jsonl", COMPANY)
        self.backups = self.root / "backups"

    def resolved(self):
        return self.fixture.resolved()

    def entries(self):
        return detect_format(self.source).diagnose(self.source).entries

    def items(self):
        r = self.resolved()
        return {i.item_id: i for i in al.pending_items(self.entries(), r.profile, r.context, COMPANY)}

    def label(self, voucher):
        return next(e for e in self.entries() if e.metadata.get("yayoi_voucher_number") == str(voucher)).id.rsplit(":", 1)[-1]

    def ready(self):
        r = self.resolved()
        blockers = YayoiJournalReportJdlWorkflow().assess(self.source, r.profile, r.context).journal_blockers
        return {j for j, v in blockers.items() if not v}, blockers

    def preview(self, *ids, scope=None):
        r, items = self.resolved(), self.items()
        return al.preview(self.source, r.profile, r.context, COMPANY, [(items[i], scope) for i in ids])

    def record(self, item_id, decision=al.APPROVED, scope=None, **overrides):
        item = self.items().get(item_id) or self._applied_item(item_id)
        kwargs = dict(tax_accountant="架空税理士", recorded_by="架空担当", decided_on=date(2026, 11, 20),
                      reference="確認書（架空）No.1", scope=scope or item.default_scope,
                      bindings=al.bindings_for(self.source, self.resolved().context, COMPANY, self.resolved().profile.profile_id), explicitly_confirmed=True)
        kwargs.update(overrides)
        return self.ledger.record_decision(item, decision, **kwargs)

    def _applied_item(self, item_id):
        return self.ledger.recorded_item(item_id)

    def apply(self, item_id, *, fingerprint=None, **overrides):
        decision = self.ledger.latest_decision(item_id)
        if fingerprint is None:
            fingerprint = self.preview(item_id, scope=decision["scope"]).fingerprint
        kwargs = dict(store_root=self.root, company_id=COMPANY, source=self.source,
                      expected_preview_fingerprint=fingerprint, backup_dir=self.backups, applied_by="架空担当")
        kwargs.update(overrides)
        result = al.apply_decision(self.ledger, item_id, **kwargs)
        self.fixture._rebind()
        return result


class PendingAndPreviewTest(unittest.TestCase):
    def test_items_are_listed_unapproved_and_nothing_changes_without_an_approval(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            before_store = store_digest(env.root)
            ready_before, _ = env.ready()
            items = env.items()
            split = items["SPLIT-V1"]
            self.assertEqual(sorted(t.voucher for t in split.targets), ["1", "3"])
            self.assertEqual(split.default_scope["kind"], vs.SCOPE_JOURNALS)
            self.assertEqual({i for i in items if i.startswith("NONCREDIT-")},
                             {f"NONCREDIT-{env.label(2)}", f"NONCREDIT-{env.label(3)}"})
            for item in items.values():
                for field in ("company_id", "period", "jdl_version", "voucher_row_limit", "evidence_ids", "change"):
                    self.assertTrue(getattr(item, field), (item.item_id, field))
            # previews and an ON_HOLD / REJECTED decision change neither READY nor the saved setting
            env.preview(*items)
            env.record("SPLIT-V1", al.ON_HOLD)
            env.record(f"NONCREDIT-{env.label(2)}", al.REJECTED)
            self.assertEqual(env.ready()[0], ready_before)
            self.assertEqual(store_digest(env.root), before_store)
            self.assertEqual(env.ledger.status("SPLIT-V1"), "保留")

    def test_split_preview_equals_the_result_of_the_real_approval(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            seen = env.preview("SPLIT-V1")
            self.assertEqual((seen.newly_blocked, seen.outside_scope_changed, seen.problems), ((), (), ()))
            self.assertEqual(len(seen.released), 1)               # voucher 1 only
            r = env.resolved()
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context,
                                    human_approver="a", tax_accountant="b", signoff_reference="c",
                                    signoff_date=date(2026, 11, 20), scope=al._split_scope_from(env.items()["SPLIT-V1"].default_scope))
            env.fixture._rebind()
            self.assertEqual(tuple(sorted(env.ready()[0])), seen.ready_after_ids)

    def test_a_journal_with_several_reasons_is_never_released_by_one_approval(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            multi = f"NONCREDIT-{env.label(3)}"
            multi_id = next(e.id for e in env.entries() if e.metadata.get("yayoi_voucher_number") == "3")
            for ids in (("SPLIT-V1",), (multi,)):
                seen = env.preview(*ids)
                self.assertNotIn(multi_id, seen.released, ids)
                self.assertIn(multi_id, seen.still_blocked, ids)
            both = env.preview("SPLIT-V1", multi)
            change = next(c for c in both.targets if c.journal_id == multi_id)
            self.assertNotIn("HUMAN:TAX_MAPPING", change.after)
            self.assertNotIn(vs.APPROVAL_BLOCKER, change.after)

    def test_no_item_and_no_combination_releases_the_zero_tax_journal(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            zero_id = next(e.id for e in env.entries() if e.metadata.get("yayoi_voucher_number") == "4")
            _, blockers = env.ready()
            self.assertTrue(blockers[zero_id])
            items = env.items()
            self.assertFalse(any(t.voucher == "4" for i in items.values() for t in i.targets))
            seen = env.preview(*items)
            self.assertNotIn(zero_id, seen.released)

    def test_noncredit_needs_the_evidence_scope_for_the_company(self):
        with tempfile.TemporaryDirectory() as directory:  # Evidence names only the real company
            env = Env(directory)
            seen = env.preview(f"NONCREDIT-{env.label(2)}")
            self.assertEqual(seen.released, ())

    def test_a_changed_row_limit_is_shown_as_invalidating_the_approvals(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            seen = env.preview("SPLIT-V1", f"NONCREDIT-{env.label(2)}")
            self.assertEqual(len(seen.setting_sensitivity), 2)
            self.assertIn("64", seen.setting_sensitivity[0])


class PolicyAndTrailingSpaceTest(unittest.TestCase):
    def test_an_operating_policy_is_recorded_only_and_never_widened(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            r = env.resolved()
            line = next(int(l.metadata["journal_row_number"]) for e in env.entries()
                        if e.metadata.get("yayoi_voucher_number") == "2" for l in e.lines)
            with self.assertRaises(al.ApprovalError):  # a policy must name its lines
                al.pending_items(env.entries(), r.profile, r.context, COMPANY,
                                 policies=({"item_id": "P", "journal": env.label(2), "lines": []},))
            items = al.pending_items(env.entries(), r.profile, r.context, COMPANY,
                                     policies=({"item_id": "POLICY-OVERSEAS", "journal": env.label(2), "lines": [line],
                                                "change": "海外購入は非課税仕入（架空）"},))
            policy = next(i for i in items if i.kind == al.KIND_POLICY)
            self.assertFalse(policy.applies_to_conversion)
            seen = al.preview(env.source, r.profile, r.context, COMPANY, [(policy, None)])
            self.assertEqual((seen.released, seen.ready_after), ((), seen.ready_before))
            bindings = al.bindings_for(env.source, r.context, COMPANY, r.profile.profile_id)
            common = dict(tax_accountant="t", recorded_by="r", decided_on=date(2026, 11, 20), reference="x",
                          bindings=bindings, explicitly_confirmed=True)
            with self.assertRaises(al.ApprovalError):  # wider than the named line
                env.ledger.record_decision(policy, al.APPROVED, scope={"kind": "LINES", "lines": [line, line + 1]}, **common)
            env.ledger.record_decision(policy, al.APPROVED, scope=policy.default_scope, **common)
            with patch.object(al, "pending_items", lambda *a, **k: items):
                with self.assertRaisesRegex(al.ApprovalError, "記録のみ"):
                    env.apply("POLICY-OVERSEAS", fingerprint="x")
            self.assertEqual(env.ready()[0], {j for j in seen.ready_after_ids})

    def test_the_trailing_space_item_is_pending_and_cannot_be_applied_from_the_ledger(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            record = env.root / "record.json"
            record.write_text(json.dumps({"rows": [{"x": 1}], "rows_count": 1, "journals_count": 1,
                                          "evidence_ids": ["EVID-X"], "rows_sha256": "0" * 64,
                                          "files": {"candidate": {"sha256": "a" * 64}}}), encoding="utf-8")
            r = env.resolved()
            items = al.pending_items(env.entries(), r.profile, r.context, COMPANY, trailing_space_record=record)
            item = next(i for i in items if i.kind == al.KIND_TRAILING_SPACE)
            self.assertEqual(env.ledger.status(item.item_id), "未判断")
            env.ledger.record_decision(item, al.APPROVED, tax_accountant="t", recorded_by="r",
                                       decided_on=date(2026, 11, 20), reference="x", scope=item.default_scope,
                                       bindings=al.bindings_for(env.source, r.context, COMPANY, r.profile.profile_id), explicitly_confirmed=True)
            with self.assertRaisesRegex(al.ApprovalError, "jdl_description_trailing_space_acceptance"):
                env.apply(item.item_id, fingerprint="x")
            self.assertEqual(list(env.root.rglob("*acceptance*")), [])


class LedgerTest(unittest.TestCase):
    def test_a_decision_needs_explicit_confirmation_names_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            for override in (dict(explicitly_confirmed=False), dict(tax_accountant=" "), dict(recorded_by=""),
                             dict(reference=""), dict(scope={"kind": ""}), dict(decided_on=None),
                             dict(scope={"kind": vs.SCOPE_PERIOD, "start": "2026-12-01", "end": "2026-01-01"})):
                with self.subTest(override), self.assertRaises(al.ApprovalError):
                    env.record("SPLIT-V1", **override)
            self.assertEqual(env.ledger.entries(), [])

    def test_duplicates_tampering_and_another_company_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            env.record("SPLIT-V1")
            with self.assertRaisesRegex(al.ApprovalError, "重複"):
                env.record("SPLIT-V1")
            with self.assertRaises(al.ApprovalError):  # bindings of another company
                env.record("SPLIT-V1", al.ON_HOLD, bindings={"company_id": "company-other"})
            with self.assertRaises(al.ApprovalError):
                al.ApprovalLedger(env.ledger.path, "company-other").entries()
            text = env.ledger.path.read_text(encoding="utf-8").replace("架空税理士", "別人")
            env.ledger.path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(al.ApprovalError, "改変"):
                env.ledger.entries()


class ApplyTest(unittest.TestCase):
    def test_apply_backup_audit_duplicate_and_revoke(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            ready_before, _ = env.ready()
            with self.assertRaises(al.ApprovalError):  # nothing approved yet
                env.apply("SPLIT-V1", fingerprint="x")
            env.record("SPLIT-V1")
            seen = env.preview("SPLIT-V1")
            entry = env.apply("SPLIT-V1")
            self.assertEqual(entry["type"], "APPLIED")
            self.assertEqual(entry["ready_after"], seen.ready_after)
            self.assertTrue(Path(entry["backup"], "profiles").is_dir())
            self.assertEqual(tuple(sorted(env.ready()[0])), seen.ready_after_ids)
            policy = env.resolved().profile.loss_policy_mappings[vs.POLICY_KEY]
            self.assertEqual(policy.metadata["approval_ledger_entry_sha256"],
                             env.ledger.latest_decision("SPLIT-V1")["entry_sha256"])
            with self.assertRaises(al.ApprovalError):  # applied once only
                env.apply("SPLIT-V1", fingerprint=seen.fingerprint)
            with self.assertRaisesRegex(al.ApprovalError, "REVOKED"):
                al.revoke_applied(env.ledger, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                                  backup_dir=env.backups, revoked_by="r", reference="x")
            env.record("SPLIT-V1", al.REVOKED)
            al.revoke_applied(env.ledger, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                              backup_dir=env.backups, revoked_by="架空担当", reference="取消の連絡（架空）")
            env.fixture._rebind()
            self.assertEqual(env.ready()[0], ready_before)
            self.assertEqual(vs.policy_problems(env.resolved().profile, env.resolved().context), ("SPLIT_NOT_APPROVED",))
            self.assertEqual([e["type"] for e in env.ledger.entries()], ["DECISION", "APPLIED", "DECISION", "UNAPPLIED"])

    def test_apply_is_refused_on_any_mismatch(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            digest = store_digest(env.root)
            with self.assertRaisesRegex(al.ApprovalError, "プレビュー"):
                env.apply("SPLIT-V1", fingerprint="0" * 64)
            with self.assertRaisesRegex(al.ApprovalError, "会社"):
                env.apply("SPLIT-V1", company_id="company-other")
            with self.assertRaisesRegex(al.ApprovalError, "AppData"):
                with patch.object(al, "_is_production_store", lambda root: True):
                    env.apply("SPLIT-V1")
            with self.assertRaises(al.ApprovalError):
                env.apply("SPLIT-V1", applied_by=" ")
            changed = write_in(env.root / "changed", rows() + card_voucher(20, voucher=9))
            with self.assertRaisesRegex(al.ApprovalError, "source_sha256"):
                env.apply("SPLIT-V1", source=changed)
            self.assertEqual(store_digest(env.root), digest)  # nothing written by a refused apply
            self.assertFalse(env.backups.exists())

    def test_a_result_that_differs_from_the_preview_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            seen = env.preview("SPLIT-V1")
            digest = store_digest(env.root)
            broken = al.Preview(**{**seen.__dict__, "ready_after_ids": ()})
            with patch.object(al, "preview", lambda *a, **k: broken):
                with self.assertRaisesRegex(al.ApprovalError, "元に戻します"):
                    env.apply("SPLIT-V1", fingerprint=seen.fingerprint)
            self.assertEqual(store_digest(env.root), digest)

    def test_noncredit_apply_needs_the_judged_signoff(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            item_id = f"NONCREDIT-{env.label(2)}"
            env.record(item_id)
            with self.assertRaisesRegex(al.ApprovalError, "消費税集計"):
                env.apply(item_id)
            with self.assertRaises(al.ApprovalError):
                env.apply(item_id, judge_report=judge_report(directory, "PENDING"))
            entry = env.apply(item_id, judge_report=judge_report(directory))
            self.assertEqual(entry["released"], 1)
            nc_id = next(e.id for e in env.entries() if e.metadata.get("yayoi_voucher_number") == "2")
            self.assertIn(nc_id, env.ready()[0])
            # the same identity in the multi-reason journal is NOT covered by this journal's approval
            multi_id = next(e.id for e in env.entries() if e.metadata.get("yayoi_voucher_number") == "3")
            self.assertIn("HUMAN:TAX_MAPPING", env.ready()[1][multi_id])
            env.record(item_id, al.REVOKED)
            al.revoke_applied(env.ledger, item_id, store_root=env.root, company_id=COMPANY, source=env.source,
                              backup_dir=env.backups, revoked_by="r", reference="x")
            env.fixture._rebind()
            self.assertNotIn(nc_id, env.ready()[0])
            self.assertNotIn(NC10, env.resolved().profile.tax_mappings)


class RouteTest(unittest.TestCase):
    """Every route that writes an approval leaves a ledger entry; the ledger and the setting cannot drift apart."""

    def _controller(self, env):
        from accounting_converter.infrastructure.application_preferences import ApplicationPreferencesStore
        from accounting_converter.ui.controllers import AccountingConverterController

        return AccountingConverterController(profile_store=env.fixture.profiles, company_store=env.fixture.companies,
                                             preferences_store=ApplicationPreferencesStore(env.root / "prefs.json"))

    def _gui_approve(self, env, controller=None):
        jid = env.entries()[0].id.rsplit(":", 1)[-1]
        return (controller or self._controller(env)).approve_voucher_split(
            COMPANY, human_approver="a", tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
            explicitly_confirmed=True, source_path=env.source, journal_ids=(jid,))

    def test_the_screen_route_leaves_a_ledger_entry_and_nothing_unexplained(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            state = self._gui_approve(env)
            self.assertIsNone(state.developer_error, state.user_message)
            ledger = al.ApprovalLedger(al.default_ledger_path(env.root, COMPANY), COMPANY)
            entries = ledger.entries()
            self.assertEqual([e["type"] for e in entries], ["DIRECT_APPLIED"])
            self.assertEqual((entries[0]["tax_accountant"], entries[0]["scope"]["split_scope"]), ("b", vs.SCOPE_JOURNALS))
            self.assertEqual(al.unrecorded_approvals(env.resolved().profile, ledger), [])
            self.assertEqual(vs.policy_problems(env.resolved().profile, env.resolved().context), ())

    def test_an_approval_that_bypassed_the_ledger_is_reported(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            ledger = al.ApprovalLedger(al.default_ledger_path(env.root, COMPANY), COMPANY)
            r = env.resolved()
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="a",
                                    tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
                                    scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            nc.approve_noncredit_identity(
                env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, NC10, human_approver="a",
                tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
                rate_distinction_loss_acknowledged=True, journals=[env.entries()[1]], source_entries=env.entries())
            env.fixture._rebind()
            found = al.unrecorded_approvals(env.resolved().profile, ledger)
            self.assertEqual(len(found), 2)
            self.assertTrue(any("伝票分割" in text for text in found) and any("控除不可" in text for text in found))

    def test_a_tampered_ledger_blocks_a_new_approval_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            controller = self._controller(env)
            self.assertIsNone(self._gui_approve(env, controller).developer_error)
            path = al.default_ledger_path(env.root, COMPANY)
            path.write_text(path.read_text(encoding="utf-8").replace('"b"', '"x"'), encoding="utf-8")
            digest = store_digest(env.root)
            state = self._gui_approve(env, controller)
            self.assertIsNotNone(state.developer_error)
            self.assertIn("改変", state.user_message)
            self.assertEqual(store_digest(env.root), digest)

    def test_a_ledger_that_cannot_be_written_puts_the_setting_back(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            digest = store_digest(env.root)
            with patch.object(al.ApprovalLedger, "_append", side_effect=OSError("disk full")):
                state = self._gui_approve(env)
            self.assertIsNotNone(state.developer_error)
            self.assertEqual(store_digest(env.root), digest)
            self.assertEqual(vs.policy_problems(env.resolved().profile, env.resolved().context), ("SPLIT_NOT_APPROVED",))

    def test_a_busy_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            env.ledger.path.parent.mkdir(parents=True)
            env.ledger.path.with_name(env.ledger.path.name + ".lock").write_text("x")
            with self.assertRaisesRegex(al.ApprovalError, "使用中"):
                env.record("SPLIT-V1")
            self.assertFalse(env.ledger.path.exists())


class ConcurrencyTest(unittest.TestCase):
    def _other_change(self, env, name="別の設定"):
        """Another screen saves an unrelated setting (a department mapping) into the same profile."""
        from dataclasses import replace

        from accounting_converter.domain.mapping import MappingStatus, MappingValue

        profile = env.fixture.profiles.get(env.resolved().profile.profile_id)
        loss = dict(profile.loss_policy_mappings)
        loss["other_policy:" + name] = MappingValue("other_policy:" + name, name, MappingStatus.USER_CONFIRMED,
                                                    metadata={"note": "unrelated"})
        env.fixture.profiles.update(replace(profile, loss_policy_mappings=loss))
        env.fixture._rebind()
        return "other_policy:" + name

    def test_revoke_keeps_a_change_made_after_the_apply(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            env.apply("SPLIT-V1")
            key = self._other_change(env)
            env.record("SPLIT-V1", al.REVOKED)
            al.revoke_applied(env.ledger, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                              backup_dir=env.backups, revoked_by="r", reference="x")
            env.fixture._rebind()
            policies = env.resolved().profile.loss_policy_mappings
            self.assertIn(key, policies)
            self.assertNotIn(vs.POLICY_KEY, policies)

    def test_revoke_stops_when_the_approval_was_replaced_afterwards(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            env.apply("SPLIT-V1")
            r = env.resolved()  # re-approved by another route with a different scope: no longer this ledger's approval
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="z",
                                    tax_accountant="y", signoff_reference="w", signoff_date=date(2026, 11, 25),
                                    scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            env.fixture._rebind()
            env.record("SPLIT-V1", al.REVOKED)
            digest = store_digest(env.root)
            with self.assertRaisesRegex(al.ApprovalError, "一致しません"):
                al.revoke_applied(env.ledger, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                                  backup_dir=env.backups, revoked_by="r", reference="x")
            self.assertEqual(store_digest(env.root), digest)
            self.assertIn(vs.POLICY_KEY, env.resolved().profile.loss_policy_mappings)

    def test_a_failed_check_does_not_overwrite_a_change_made_meanwhile(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            seen = env.preview("SPLIT-V1")
            real_assess = YayoiJournalReportJdlWorkflow.assess
            changed = {}

            def assess_then_other_save(self_, *a, **k):  # another screen saves during the post-check
                result = real_assess(self_, *a, **k)
                changed["key"] = TestSupport.other_change(env)
                return result

            broken = al.Preview(**{**seen.__dict__, "ready_after_ids": ()})
            with patch.object(al, "preview", lambda *a, **k: broken), \
                    patch("accounting_converter.application.yayoi_jdl_workflow.YayoiJdlWorkflow.assess",
                          assess_then_other_save):
                with self.assertRaisesRegex(al.ConflictError, "自動では元に戻しません"):
                    env.apply("SPLIT-V1", fingerprint=seen.fingerprint)
            self.assertIn(changed["key"], env.resolved().profile.loss_policy_mappings)  # their change survived
            self.assertEqual(env.ledger.applied("SPLIT-V1"), None)                     # and nothing was recorded

    def test_a_change_between_preview_and_write_stops_the_apply(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            fingerprint = env.preview("SPLIT-V1").fingerprint
            real_backup = al._backup

            def backup_then_other_save(*a, **k):
                result = real_backup(*a, **k)
                TestSupport.other_change(env)
                return result

            with patch.object(al, "_backup", backup_then_other_save):
                with self.assertRaisesRegex(al.ConflictError, "プレビュー後に会社設定が変更"):
                    env.apply("SPLIT-V1", fingerprint=fingerprint)
            self.assertNotIn(vs.POLICY_KEY, env.resolved().profile.loss_policy_mappings)
            self.assertEqual([e["type"] for e in env.ledger.entries()], ["DECISION"])


class TestSupport:
    other_change = staticmethod(lambda env: ConcurrencyTest()._other_change(env))


class CompanyIdentityTest(unittest.TestCase):
    """The company ID itself is checked, in addition to the profile ID, on every route (all fail closed)."""

    def _second_company(self, env, company="company-b"):
        """Another company setting that points at the SAME profile (the hazard: approvals live in the profile)."""
        env.fixture.companies.create(company_setting_id=company, display_name="別会社",
                                     conversion_profile_id=env.fixture.profile.profile_id,
                                     context_source=env.root / "context.json")
        return env.fixture.companies.resolve(company)

    def _direct(self, env, **overrides):
        r = env.resolved()
        kwargs = dict(store=env.fixture.profiles, companies=env.fixture.companies, company_id=COMPANY,
                      profile_id=r.profile.profile_id, context=r.context, human_approver="a", tax_accountant="b",
                      signoff_reference="c", signoff_date=date(2026, 11, 20),
                      scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
        kwargs.update(overrides)
        store, companies = kwargs.pop("store"), kwargs.pop("companies")
        company_id, profile_id, context = kwargs.pop("company_id"), kwargs.pop("profile_id"), kwargs.pop("context")
        return al.approve_split_direct(store, companies, company_id, profile_id, context, **kwargs)

    def _unchanged(self, env, digest, ledger_exists=False):
        self.assertEqual(store_digest(env.root), digest)
        self.assertEqual(al.default_ledger_path(env.root, COMPANY).exists(), ledger_exists)

    def test_the_right_company_and_profile_can_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            self._direct(env)
            env.fixture._rebind()
            r = env.resolved()
            self.assertEqual(r.context.company_setting_id, COMPANY)
            self.assertEqual(vs.policy_problems(r.profile, r.context), ())
            self.assertEqual(r.profile.loss_policy_mappings[vs.POLICY_KEY].metadata["company_setting_id"], COMPANY)

    def test_a_wrong_company_id_or_profile_id_is_refused_and_nothing_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            digest = store_digest(env.root)
            with self.assertRaises(al.ApprovalError):          # company ID differs from the resolved JDL setting
                self._direct(env, company_id="company-other")
            self._unchanged(env, digest)
            with self.assertRaises(al.ApprovalError):          # profile ID differs from the company setting's
                self._direct(env, profile_id="profile-other")
            self._unchanged(env, digest)
            r = env.resolved()
            with self.assertRaisesRegex(ValueError, "COMPANY_DIFFERS_FROM_SETTING"):   # the low-level function too
                vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, "company-other", r.context,
                                        human_approver="a", tax_accountant="b", signoff_reference="c",
                                        signoff_date=date(2026, 11, 20), scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            self._unchanged(env, digest)

    def test_the_screen_route_refuses_another_company(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            digest = store_digest(env.root)
            state = RouteTest()._controller(env).approve_voucher_split(
                "company-other", human_approver="a", tax_accountant="b", signoff_reference="c",
                signoff_date=date(2026, 11, 20), explicitly_confirmed=True, source_path=env.source,
                journal_ids=(env.entries()[0].id.rsplit(":", 1)[-1],))
            self.assertIsNotNone(state.developer_error)
            self._unchanged(env, digest)

    def test_a_profile_shared_with_another_company_is_never_approved_through_and_does_not_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            self._direct(env)                                  # company A approves first (not shared yet)
            env.fixture._rebind()
            b = self._second_company(env)
            self.assertEqual(vs.policy_problems(env.resolved().profile, env.resolved().context), ())  # A is unaffected
            # B converts with A's approval stored in the shared profile: it is not B's approval
            self.assertEqual(vs.policy_problems(b.profile, b.context), ("COMPANY_DIFFERS_FROM_APPROVAL",))
            blockers = YayoiJournalReportJdlWorkflow().assess(env.source, b.profile, b.context).journal_blockers
            self.assertTrue(all(v for v in blockers.values()))
            self.assertEqual(vs.apply_split(env.entries(), b.profile, b.context), list(env.entries()))
            # nobody can record a new approval while the profile is shared, and B cannot overwrite A's
            digest = store_digest(env.root)
            for company, resolved in ((COMPANY, env.resolved()), ("company-b", b)):
                with self.subTest(company), self.assertRaisesRegex(al.ApprovalError, "別の会社設定"):
                    self._direct(env, company_id=company, profile_id=resolved.profile.profile_id, context=resolved.context)
            with self.assertRaisesRegex(ValueError, "FOREIGN_COMPANY_APPROVAL_IN_PROFILE"):
                vs.approve_split_policy(env.fixture.profiles, b.profile.profile_id, "company-b", b.context,
                                        human_approver="a", tax_accountant="b", signoff_reference="c",
                                        signoff_date=date(2026, 11, 20), scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            self.assertEqual(store_digest(env.root), digest)

    def test_the_ledger_must_belong_to_the_company_being_changed(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record("SPLIT-V1")
            digest, ledger_bytes = store_digest(env.root), env.ledger.path.read_bytes()
            foreign = al.ApprovalLedger(env.ledger.path, "company-other")
            with self.assertRaises(al.ApprovalError):          # a ledger of another company, read as company A's
                foreign.entries()
            with self.assertRaisesRegex(al.ApprovalError, "別の会社"):
                al.apply_decision(foreign, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                                  expected_preview_fingerprint="x", backup_dir=env.backups, applied_by="x")
            self.assertEqual(store_digest(env.root), digest)
            self.assertEqual(env.ledger.path.read_bytes(), ledger_bytes)
            self.assertFalse(env.backups.exists())

    def test_a_decision_must_be_bound_to_the_resolved_company_and_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory)
            good = al.bindings_for(env.source, env.resolved().context, COMPANY, env.resolved().profile.profile_id)
            for change in ({"context_company_id": "company-other"}, {"context_company_id": None}, {"profile_id": None},
                           {"company_id": "company-other"}):
                with self.subTest(change), self.assertRaises(al.ApprovalError):
                    env.record("SPLIT-V1", bindings={**good, **change})
            self.assertEqual(env.ledger.entries(), [])
            # a decision made for another profile is not applied (bindings no longer match)
            env.record("SPLIT-V1", bindings={**good, "profile_id": "profile-before"})
            with patch.object(al, "preview"), self.assertRaisesRegex(al.ApprovalError, "profile_id"):
                al.apply_decision(env.ledger, "SPLIT-V1", store_root=env.root, company_id=COMPANY, source=env.source,
                                  expected_preview_fingerprint="x", backup_dir=env.backups, applied_by="x")

    def test_preview_reports_a_context_of_another_company(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            r, items = env.resolved(), env.items()
            from dataclasses import replace

            seen = al.preview(env.source, r.profile, replace(r.context, company_setting_id="company-other"), COMPANY,
                              [(items["SPLIT-V1"], None)])
            self.assertTrue(seen.problems)
            self.assertEqual(al.preview(env.source, r.profile, r.context, COMPANY, [(items["SPLIT-V1"], None)]).problems, ())

    def test_audit_reports_an_approval_recorded_for_another_company(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            self._direct(env)
            env.fixture._rebind()
            ledger_b = al.ApprovalLedger(env.root / "ledger_b.jsonl", "company-b")
            found = al.unrecorded_approvals(env.resolved().profile, ledger_b)
            self.assertTrue(any("別の会社" in text for text in found))
            self.assertEqual(al.unrecorded_approvals(env.resolved().profile,
                                                     al.ApprovalLedger(al.default_ledger_path(env.root, COMPANY), COMPANY)), [])

    def test_existing_valid_approvals_keep_working_and_unverifiable_ones_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            r = env.resolved()
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="a",
                                    tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
                                    scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            env.fixture._rebind()
            r = env.resolved()
            self.assertEqual(vs.policy_problems(r.profile, r.context), ())          # an existing approval: unchanged
            self.assertTrue(env.ready()[1])
            from dataclasses import replace

            self.assertEqual(vs.policy_problems(r.profile, replace(r.context, company_setting_id=None)), ("COMPANY_UNVERIFIED",))
            policy = r.profile.loss_policy_mappings[vs.POLICY_KEY]
            legacy = replace(r.profile, loss_policy_mappings={vs.POLICY_KEY: replace(policy, metadata={
                k: v for k, v in policy.metadata.items() if k != "company_setting_id"})})
            self.assertEqual(vs.policy_problems(legacy, r.context), ("APPROVAL_COMPANY_UNRECORDED",))

    def test_a_noncredit_approval_of_another_company_is_not_used_by_a_company_sharing_the_profile(self):
        with tempfile.TemporaryDirectory() as directory, evidence_covers_test_company():
            env = Env(directory)
            env.record(f"NONCREDIT-{env.label(2)}")
            env.apply(f"NONCREDIT-{env.label(2)}", judge_report=judge_report(directory))
            env.fixture._rebind()
            self.assertEqual(env.resolved().profile.tax_mappings[NC10].metadata["noncredit_company_setting_id"], COMPANY)
            b = self._second_company(env)
            self.assertIn(nc.COMPANY_CONTEXT_MISMATCH, nc.mapping_problems(NC10, b.profile.tax_mappings[NC10], b.profile, b.context))
            self.assertEqual(nc.mapping_problems(NC10, env.resolved().profile.tax_mappings[NC10], env.resolved().profile,
                                                 env.resolved().context), ())


class AmbiguityTest(unittest.TestCase):
    def test_an_approval_of_one_journal_never_covers_an_identical_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1) + card_voucher(26, voucher=2))
            entries = env.entries()
            self.assertEqual(vs.ambiguous_identities(entries), {stable_identity(entries[0])})
            r = env.resolved()
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="a",
                                    tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
                                    scope=vs.SplitScope.for_journals(entries[:1]))
            env.fixture._rebind()
            ready, blockers = env.ready()
            self.assertEqual(ready, set())                       # neither copy is covered
            self.assertTrue(all(v == {vs.APPROVAL_BLOCKER} for v in blockers.values()))
            self.assertEqual(len(vs.apply_split(entries, env.resolved().profile, env.resolved().context)), 2)


def stable_identity(entry):
    from accounting_converter.domain.journal_identity import stable_journal_identity

    return stable_journal_identity(entry)


class SplitScopeTest(unittest.TestCase):
    def test_journal_scope_does_not_reach_a_later_journal_and_period_scope_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            r = env.resolved()
            scope = vs.SplitScope.for_journals(env.entries())
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="a",
                                    tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20), scope=scope)
            env.fixture._rebind()
            later = write_in(env.root / "later", card_voucher(26, voucher=1) + card_voucher(20, voucher=2))
            r = env.resolved()
            blockers = YayoiJournalReportJdlWorkflow().assess(later, r.profile, r.context).journal_blockers
            by_voucher = {e.metadata.get("yayoi_voucher_number"): e.id for e in detect_format(later).diagnose(later).entries}
            self.assertEqual(blockers[by_voucher["1"]], frozenset())
            self.assertEqual(blockers[by_voucher["2"]], frozenset({vs.APPROVAL_BLOCKER}))
            # a period scope covers only journals dated inside it
            entry = env.entries()[0]
            inside = vs.SplitScope(vs.SCOPE_PERIOD, period=(entry.date, entry.date))
            outside = vs.SplitScope(vs.SCOPE_PERIOD, period=(date(2000, 1, 1), date(2000, 12, 31)))
            self.assertTrue(inside.covers(entry))
            self.assertFalse(outside.covers(entry))

    def test_an_approval_without_scope_is_refused_and_a_saved_one_without_scope_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Env(directory, card_voucher(26, voucher=1))
            r = env.resolved()
            with self.assertRaisesRegex(ValueError, "SPLIT_SCOPE_MISSING"):
                vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context,
                                        human_approver="a", tax_accountant="b", signoff_reference="c",
                                        signoff_date=date(2026, 11, 20), scope=None)
            vs.approve_split_policy(env.fixture.profiles, r.profile.profile_id, COMPANY, r.context, human_approver="a",
                                    tax_accountant="b", signoff_reference="c", signoff_date=date(2026, 11, 20),
                                    scope=vs.SplitScope(vs.SCOPE_COMPANY_WIDE))
            from dataclasses import replace

            profile = env.fixture.profiles.get(r.profile.profile_id)
            policy = profile.loss_policy_mappings[vs.POLICY_KEY]
            legacy = replace(policy, metadata={k: v for k, v in policy.metadata.items() if k != vs.SCOPE_KEY})
            env.fixture.profiles.update(replace(profile, loss_policy_mappings={vs.POLICY_KEY: legacy}))
            env.fixture._rebind()
            self.assertIn("SPLIT_SCOPE_MISSING", vs.policy_problems(env.resolved().profile, env.resolved().context))
            self.assertEqual(env.ready()[0], set())


if __name__ == "__main__":
    unittest.main()

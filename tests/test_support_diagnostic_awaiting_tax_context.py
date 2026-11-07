"""Support diagnostics while the JDL tax setting is not confirmed (Yayoi). Synthetic values only.

Windows report 2026-11-07: with the tax setting still a PDF draft the diagnostics showed
科目・補助・税区分 = 0, 未対応仕訳構成 = 602, final state "保存先を選択してください". The 602 came from the
Money Forward shape list used as a fallback; it is "not evaluated", not a finding."""
from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.application.company_mapping_update import _yayoi_unsupported_shape_count
from accounting_converter.application.company_review_state import CompanyReviewWorkQueue
from accounting_converter.profiles.known_formats import yayoi_journal_report_generic_identity
from accounting_converter.ui.view_models import (
    AWAITING_TAX_CONTEXT,
    AppState,
    present_main_screen,
    support_diagnostic_text,
)

SOURCE = Path("synthetic.txt")


def queue(**overrides) -> CompanyReviewWorkQueue:
    values = {}
    for field in dataclasses.fields(CompanyReviewWorkQueue):
        if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
            continue
        annotation = str(field.type)
        values[field.name] = (
            () if annotation.startswith("tuple") else SOURCE if "Path" in annotation
            else "company-1" if annotation == "str" else 0
        )
    values.update(overrides)
    return CompanyReviewWorkQueue(**values)


def state(work_queue) -> AppState:
    return AppState(selected_file=SOURCE, selected_company_setting_id="company-1", review_work_queue=work_queue,
                    selected_profile_id="profile-1", selected_context_file=Path("jdl-context.json"),
                    jdl_master_configured=True, jdl_master_state="JDL税設定の確認が必要")


def lines(text: str) -> dict[str, str]:
    return {line.split(": ", 1)[0]: line.split(": ", 1)[1] for line in text.splitlines() if ": " in line}


class ShapeCountFallbackTest(unittest.TestCase):
    yayoi = SimpleNamespace(source_format_identity=yayoi_journal_report_generic_identity())

    def test_yayoi_without_a_confirmed_tax_context_is_not_counted_with_the_money_forward_list(self):
        self.assertEqual(_yayoi_unsupported_shape_count((object(),) * 602, self.yayoi, None), 0)

    def test_a_non_yayoi_company_still_uses_its_own_shape_list(self):
        other = SimpleNamespace(source_format_identity=SimpleNamespace(stable_key="MF|other"))
        self.assertIsNone(_yayoi_unsupported_shape_count((), other, None))


class AwaitingTaxContextTest(unittest.TestCase):
    def test_diagnostics_say_not_evaluated_and_point_to_the_tax_setting(self):
        text = support_diagnostic_text(state(queue(awaiting_tax_context=True, unsupported_journals=0)), "x")
        rows = lines(text)
        self.assertEqual(rows["税区分確認"], AWAITING_TAX_CONTEXT)
        self.assertEqual(rows["未対応仕訳構成"], AWAITING_TAX_CONTEXT)
        self.assertEqual(rows["最終状態"], "JDL税設定の確認が必要です")
        self.assertEqual(rows["分類"], "確認が必要")
        self.assertIn("次の操作:\n- JDL税設定:", text)

    def test_a_confirmed_tax_setting_keeps_the_numbers(self):
        rows = lines(support_diagnostic_text(state(queue(unsupported_journals=32, tax_human_settings=2)), "x"))
        self.assertEqual(rows["未対応仕訳構成"], "0")  # taken from state when there is no summary
        self.assertEqual(rows["税区分確認"], "2")
        self.assertNotEqual(rows["最終状態"], "JDL税設定の確認が必要です")

    def test_main_screen_asks_for_the_tax_setting_not_a_save_location(self):
        shown = present_main_screen(state(queue(awaiting_tax_context=True)))
        self.assertEqual(shown.status_text, "JDL税設定の確認が必要です")

    def test_a_queue_for_another_file_does_not_change_the_main_screen(self):
        other = queue(awaiting_tax_context=True, source_path=Path("other.txt"))
        self.assertNotEqual(present_main_screen(state(other)).status_text, "JDL税設定の確認が必要です")


class InformationPolicyRowsTest(unittest.TestCase):
    def test_unconfirmed_fields_are_listed_with_what_to_do_and_nothing_is_dropped_silently(self):
        text = support_diagnostic_text(state(queue(information_pending=(("付箋1", 2),))), "x")
        rows = lines(text)
        self.assertEqual(rows["JDLに保持されない情報（扱い未確認）"], "付箋1 2仕訳")
        self.assertIn("監査記録に原本の値を残します", text)
        self.assertIn("未確認のまま変換はされません", text)

    def test_confirmed_fields_are_reported_as_audit_only(self):
        rows = lines(support_diagnostic_text(
            state(queue(information_confirmed=(("付箋1", 2), ("生成元", 5)))), "x"))
        self.assertEqual(rows["JDLに保持されない情報（扱い確認済み・監査記録のみ）"], "付箋1 2仕訳、生成元 5仕訳")
        self.assertEqual(rows["JDLに保持されない情報（扱い未確認）"], "なし")


if __name__ == "__main__":
    unittest.main()

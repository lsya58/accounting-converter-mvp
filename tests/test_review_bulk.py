"""Bulk confirmation logic and dialogs. Synthetic data only."""
from __future__ import annotations

from tests import _appdata_guard  # noqa: F401  (keeps tests away from the real application data)

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from accounting_converter.application.mapping_candidates import MappingCandidate
from accounting_converter.application.review_bulk import (
    BulkRow,
    account_bulk_row,
    description_preview,
    description_rules,
    mechanical_description_candidates,
    preview_signature,
    provisional_description_preview,
    rule_problems,
    selected_description_results,
    subaccount_bulk_row,
)
from accounting_converter.application.company_mapping_update import CompanyMappingUpdateItem

try:
    from PySide6.QtWidgets import QApplication, QDialog

    from accounting_converter.application.company_mapping_update import CompanyMappingUpdateReview
    from accounting_converter.application.moneyforward_description_replacement import (
        MoneyForwardDescriptionReviewItem,
        moneyforward_description_replacement_key,
    )
    from accounting_converter.ui_qt import main_window
    from accounting_converter.ui_qt.main_window import CompanyMappingUpdateDialog

    PYSIDE6_AVAILABLE = True
except ModuleNotFoundError:
    PYSIDE6_AVAILABLE = False


def account(name, *, exact=None, candidates=(), journals=3):
    return CompanyMappingUpdateItem(
        key=f"ACCOUNT|{name}", mapping_type="ACCOUNT", source_value=name, parent_account=None,
        available_targets=("現金", "売上高", "手数料"), exact_candidate=exact, recommended_reason="表示名が一致しています" if exact else None,
        affected_journal_count=journals, candidates=candidates,
    )


class BulkLogicTest(unittest.TestCase):
    def test_only_same_name_candidates_are_pre_ticked(self):
        exact = account_bulk_row(0, account("現金", exact="現金"))
        similar = account_bulk_row(1, account("売上金", candidates=(MappingCandidate("6121", "売上高", "ALIAS", "言い換え", 0.5),)))
        warned = BulkRow(2, "x", "", "y", "y", "EXACT", "名前が同じ", 1, warning="貸借が逆")
        self.assertTrue(exact.pre_ticked)
        self.assertFalse(similar.pre_ticked)
        self.assertFalse(warned.pre_ticked)
        self.assertIsNone(account_bulk_row(3, account("全く別")))

    def test_subaccount_row_prefers_the_same_name_under_the_confirmed_parent(self):
        item = CompanyMappingUpdateItem(key="S|口座A", mapping_type="SUBACCOUNT", source_value="口座A",
                                        parent_account="普通預金", available_targets=())
        same = subaccount_bulk_row(0, item, [("口座B", "口座B"), ("口座A", "口座A")])
        self.assertEqual((same.target, same.pre_ticked), ("口座A", True))
        other = subaccount_bulk_row(0, item, [("口座B（候補）", "口座B")])
        self.assertEqual((other.target, other.pre_ticked), ("口座B", False))
        self.assertIsNone(subaccount_bulk_row(0, item, []))  # parent not confirmed yet

    def test_description_rules_keep_digits_and_preview_identity_tracks_rules(self):
        descriptions = [
            ("a", "テスト商事株式会社 定期購入代金 定期購入代金 1234-5678-9012"),
            ("b", "テスト 1234 1234 とても長い説明文がここに続いて三十二文字を超えます"),
        ]
        rules = description_rules(text for _k, text in descriptions)
        self.assertTrue(all(not rule["【記入】承認"] for rule in rules))  # nothing approved
        nothing = description_preview(descriptions, rules)
        self.assertTrue(all(line.state == "INDIVIDUAL" for line in nothing))
        for rule in rules:
            rule["【記入】承認"] = "OK"
            if rule["種類"] == "語句の短縮":
                rule["【記入】短縮後の語句"] = rule["対象の語句"][:2]
        self.assertEqual(rule_problems(rules), [])
        lines = {line.key: line for line in description_preview(descriptions, rules)}
        self.assertEqual(lines["a"].state, "FIT")
        self.assertIn("(株)", lines["a"].result)
        self.assertNotEqual(lines["b"].state, "FIT")  # removing the repeated number would change digits
        before = preview_signature(list(lines.values()))
        next(rule for rule in rules if rule["種類"] == "法人格の略記")["【記入】承認"] = ""
        self.assertNotEqual(preview_signature(description_preview(descriptions, rules)), before)

    def test_approved_phrase_rule_without_text_is_a_problem(self):
        rule = {"ルールID": "R09", "種類": "語句の短縮", "対象の語句": "長い語句", "【記入】短縮後の語句": " ", "【記入】承認": "OK"}
        self.assertEqual(len(rule_problems([rule])), 1)

    def test_sixteen_approvals_with_twelve_missing_words_are_only_provisional(self):
        original = "テスト商事株式会社 定期購入代金 定期購入代金 1234-5678-9012"
        descriptions = [(f"synthetic-{index}", original) for index in range(248)]
        rules = description_rules([original])
        self.assertEqual(len(rules), 4)
        rules.extend({
            "ルールID": f"R{index:02d}", "種類": "語句の短縮", "対象の語句": f"架空語句{index}",
            "影響する摘要数": 1, "説明": "架空の短縮候補", "【記入】短縮後の語句": "", "【記入】承認": "OK",
        } for index in range(5, 17))
        for rule in rules:
            rule["【記入】承認"] = "OK"
        lines, problems = provisional_description_preview(descriptions, rules)
        self.assertEqual(len(problems), 12)
        self.assertEqual(sum(line.fits for line in lines), 248)
        self.assertTrue(all(line.original != line.result for line in lines))
        for rule in rules[4:]:
            rule["【記入】承認"] = ""
        lines, problems = provisional_description_preview(descriptions, rules)
        self.assertEqual(problems, [])
        self.assertEqual(sum(line.fits for line in lines), 248)

    def test_one_approved_description_rule_needs_no_other_approvals(self):
        original = "A" * 30 + "  B"
        rules = description_rules([original])
        rules[0]["【記入】承認"] = "OK"
        lines, problems = provisional_description_preview([("synthetic", original)], rules)
        self.assertEqual(problems, [])
        self.assertEqual((lines[0].state, lines[0].result), ("FIT", "A" * 30 + " B"))
        self.assertEqual(len(lines[0].result), 32)

    def test_description_preview_explains_length_encoding_and_digit_blocks(self):
        rules = [{"ルールID": "R01", "種類": "空白の整理", "対象の語句": "",
                  "【記入】短縮後の語句": "", "【記入】承認": "OK"}]
        lines = description_preview([
            ("long", "A" * 65), ("encoding", "A" * 31 + "😀"),
            ("fits", "あ" * 32),
        ], rules)
        self.assertEqual([line.state for line in lines], ["INDIVIDUAL", "INDIVIDUAL", "FIT"])
        self.assertIn("32文字", lines[0].reason)
        self.assertIn("CP932", lines[1].reason)
        self.assertEqual(len(lines[2].result.encode("cp932")), 64)  # 32 characters, not 32 bytes
        number = description_preview([("number", "取引 1234")], [{
            "ルールID": "R05", "種類": "語句の短縮", "対象の語句": "1234",
            "【記入】短縮後の語句": "省略", "【記入】承認": "OK",
        }])[0]
        self.assertEqual(number.state, "DIGITS_CHANGED")
        self.assertIn("数字", number.reason)
        moved_decimal = description_preview([("rate", "レート 1.25")], [{
            "ルールID": "R06", "種類": "語句の短縮", "対象の語句": "1.25",
            "【記入】短縮後の語句": "12.5", "【記入】承認": "OK",
        }])[0]
        self.assertEqual(moved_decimal.state, "DIGITS_CHANGED")
        kept_identifier = description_preview([("identifier", "番号 1234-5678-9012")], [{
            "ルールID": "R03", "種類": "番号のハイフン削除", "対象の語句": "",
            "【記入】短縮後の語句": "", "【記入】承認": "OK",
        }])[0]
        self.assertEqual(kept_identifier.state, "FIT")

    def test_mechanical_candidates_do_not_approve_phrase_or_repeated_word_deletion(self):
        originals = [("a", "A" * 30 + "  B"), ("b", "屋号 屋号 " + "C" * 30)]
        rules = description_rules(text for _key, text in originals)
        candidates = mechanical_description_candidates(originals, rules)
        self.assertEqual(candidates[0].state, "FIT")
        self.assertEqual(candidates[0].applied_rule_ids, ("R01",))
        self.assertNotIn("R02", candidates[1].applied_rule_ids)
        self.assertTrue(all(not rule["【記入】承認"] for rule in rules))
        self.assertNotEqual(preview_signature(candidates), preview_signature(description_preview(originals, rules)))

    def test_rule_pattern_records_only_changed_rules(self):
        originals = [("a", "A" * 30 + "  B"), ("b", "番号 1234-5678-9012")]
        rules = description_rules(text for _key, text in originals)
        for rule in rules:
            if rule["ルールID"] in {"R01", "R03"}:
                rule["【記入】承認"] = "OK"
        lines = description_preview(originals, rules)
        self.assertEqual(lines[0].applied_rule_ids, ("R01",))
        self.assertEqual(lines[1].applied_rule_ids, ("R03",))

    def test_only_selected_valid_changed_candidates_are_returned(self):
        originals = [("fit", "A" * 30 + "  B"), ("long", "X" * 34)]
        rules = description_rules(text for _key, text in originals)
        rules[0]["【記入】承認"] = "OK"
        lines = description_preview(originals, rules)
        self.assertEqual(selected_description_results(lines, set()), {})
        self.assertEqual(selected_description_results(lines, {"fit"}), {"fit": "A" * 30 + " B"})
        with self.assertRaises(ValueError):
            selected_description_results(lines, {"long"})
        with self.assertRaises(ValueError):
            selected_description_results(lines + [lines[0]], {"fit"})


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class BulkDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def review(self, items, descriptions=()):
        return CompanyMappingUpdateReview(company_setting_id="c", source_path=None, context_path=None,
                                          items=tuple(items), logical_journal_count=10, descriptions=tuple(descriptions))

    def test_bulk_ticks_only_the_rows_the_human_kept(self):
        items = [account("現金", exact="現金"), account("売上Y", candidates=(MappingCandidate("6121", "売上高", "SIMILAR", "似ている", 0.4),))]
        dialog = CompanyMappingUpdateDialog(object(), self.review(items))

        class Accept:
            def __init__(self, title, rows, parent):
                self.rows = rows

            def exec(self):
                return QDialog.DialogCode.Accepted

            def selected(self):
                return [row for row in self.rows if row.pre_ticked]  # the Human kept the defaults

        with mock.patch.object(main_window, "BulkCandidateDialog", Accept):
            dialog._open_bulk("accounts")
        cash_combo, cash_check = dialog.account_controls["現金"]
        sales_combo, sales_check = dialog.account_controls["売上Y"]
        self.assertEqual((cash_combo.currentData(), cash_check.isChecked()), ("現金", True))
        self.assertFalse(sales_check.isChecked())  # similar candidate not ticked
        self.assertIsNone(sales_combo.currentData())
        self.assertIn("一括確認できる候補", dialog.triage_label.text())

    def test_subaccount_waits_for_its_parent(self):
        parent = account("普通預金Y")
        sub = CompanyMappingUpdateItem(
            key="S|口座A", mapping_type="SUBACCOUNT", source_value="口座A", parent_account="普通預金Y",
            available_targets=(), subaccount_targets_by_parent=(("現金", ("口座A",)),),
        )
        dialog = CompanyMappingUpdateDialog(object(), self.review([parent, sub]))
        item, combo, check, _status = dialog._subaccount_rows[0]
        self.assertEqual(main_window._subaccount_category(item, combo, check), "親科目の確認待ち")
        self.assertIn("親科目の確認待ち: 補助 1件", dialog.triage_label.text())

    def test_description_rules_apply_only_after_the_matching_preview(self):
        text = "テスト商事株式会社 定期購入代金 定期購入代金 1234-5678-9012"
        key = moneyforward_description_replacement_key(text)
        description = MoneyForwardDescriptionReviewItem(key, "sha", text, len(text), (), 2)
        dialog = CompanyMappingUpdateDialog(object(), self.review([], [description]))
        from accounting_converter.ui_qt.bulk_review import DescriptionRulesDialog

        rules_dialog = DescriptionRulesDialog([(key, text)], description_rules([text]))
        for row in range(rules_dialog.rule_table.rowCount()):
            rules_dialog.rule_table.item(row, 0).setCheckState(main_window.Qt.CheckState.Checked)
        rules_dialog._apply()  # no preview yet: refused
        self.assertEqual(rules_dialog.result, {})
        rules_dialog._preview()
        rules_dialog.rule_table.item(0, 0).setCheckState(main_window.Qt.CheckState.Unchecked)  # changed after preview
        self.assertFalse(rules_dialog.apply_button.isEnabled())
        rules_dialog.rule_table.item(0, 0).setCheckState(main_window.Qt.CheckState.Checked)
        rules_dialog._preview()
        rules_dialog.preview_table.item(0, 0).setCheckState(main_window.Qt.CheckState.Checked)
        rules_dialog._apply()
        self.assertEqual(len(rules_dialog.result), 1)
        self.assertIn("(株)", rules_dialog.result[key])
        field, check = dialog.description_controls[key]
        self.assertFalse(check.isChecked())  # nothing is confirmed until filled in the review dialog

    def test_description_rules_16_approved_with_12_missing_words_preview_but_cannot_apply(self):
        from accounting_converter.ui_qt.bulk_review import DescriptionRulesDialog

        original = "テスト商事株式会社 定期購入代金 定期購入代金 1234-5678-9012"
        descriptions = [(f"synthetic-{index}", original) for index in range(248)]
        rules = description_rules([original])
        self.assertEqual(len(rules), 4)
        rules.extend({
            "ルールID": f"R{index:02d}", "種類": "語句の短縮", "対象の語句": f"架空語句{index}",
            "影響する摘要数": 1, "説明": "架空の短縮候補", "【記入】短縮後の語句": "", "【記入】承認": "",
        } for index in range(5, 17))
        dialog = DescriptionRulesDialog(descriptions, rules)
        for row in range(16):
            dialog.rule_table.item(row, 0).setCheckState(main_window.Qt.CheckState.Checked)
        self.assertEqual(len(rule_problems(dialog.current_rules())), 12)
        dialog.preview_button.click()
        self.assertEqual(dialog.preview_table.rowCount(), 248)
        self.assertIn("仮プレビューの候補 248件", dialog.preview_label.text())
        self.assertIn("12件に短縮後の語句が未入力", dialog.preview_label.text())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.result, {})
        dialog.preview_table.setCurrentCell(0, 0)
        self.assertIn("元の摘要:", dialog.preview_detail.text())
        self.assertIn("置き換え後:", dialog.preview_detail.text())

        dialog.rule_table.item(4, 0).setCheckState(main_window.Qt.CheckState.Unchecked)
        self.assertIn("もう一度プレビュー", dialog.preview_label.text())
        self.assertEqual(dialog.preview_table.rowCount(), 0)
        for row in range(5, 16):
            dialog.rule_table.item(row, 0).setCheckState(main_window.Qt.CheckState.Unchecked)
        dialog.preview_button.click()
        self.assertIn("反映できる 248件", dialog.preview_label.text())
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.pattern_filter.setCurrentIndex(1)
        dialog.select_pattern.click()
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.apply_button.click()
        self.assertEqual(len(dialog.result), 248)

    def test_one_approved_rule_can_apply_without_approving_others(self):
        from accounting_converter.ui_qt.bulk_review import DescriptionRulesDialog

        original = "A" * 30 + "  B"
        dialog = DescriptionRulesDialog([("synthetic", original)], description_rules([original]))
        dialog.rule_table.item(0, 0).setCheckState(main_window.Qt.CheckState.Checked)
        dialog.suggest_button.click()
        self.assertIn("まだ承認・反映していません", dialog.preview_label.text())
        self.assertFalse(dialog.apply_button.isEnabled())
        dialog.preview_button.click()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.result, {})
        self.assertEqual(dialog.preview_table.item(0, 5).text(), "32 / 32")
        dialog.preview_table.item(0, 0).setCheckState(main_window.Qt.CheckState.Checked)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.apply_button.click()
        self.assertEqual(dialog.result, {"synthetic": "A" * 30 + " B"})

    def test_selecting_one_pattern_does_not_select_other_fitting_rows(self):
        from accounting_converter.ui_qt.bulk_review import DescriptionRulesDialog

        originals = [("space", "A" * 30 + "  B"), ("number", "番号 1234-5678-9012")]
        dialog = DescriptionRulesDialog(originals, description_rules(text for _key, text in originals))
        for row in range(dialog.rule_table.rowCount()):
            if dialog.rule_table.item(row, 1).text() in {"R01", "R03"}:
                dialog.rule_table.item(row, 0).setCheckState(main_window.Qt.CheckState.Checked)
        dialog.preview_button.click()
        dialog.pattern_filter.setCurrentIndex(dialog.pattern_filter.findData("R01"))
        dialog.select_pattern.click()
        dialog.apply_button.click()
        self.assertEqual(dialog.result, {"space": "A" * 30 + " B"})


class YayoiInformationCountTest(unittest.TestCase):
    """Invoice classes are part of the Yayoi tax identity, not lost information."""

    def test_invoice_class_is_not_counted_as_information_outside_jdl(self):
        from accounting_converter.application.company_mapping_update import CompanyMappingUpdateService
        from accounting_converter.application.yayoi_sources import REPORT
        from tests.test_yayoi_import_format import Company, floor_context
        from tests.test_yayoi_journal_report_parser import build, detail, write
        from tests.test_yayoi_jdl_workflow import details

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = details() + [detail("令和08年05月12日", 3, debit=("現金Y", "", "対象外", 100, None),
                                       credit=("売上Y", "", "対象外", 100, None), sticky="1", number=3)]
            source = write(root, build(rows))
            company = Company(root, "company-i", source, REPORT, floor_context())
            review = CompanyMappingUpdateService(company.companies, company.profiles).review("company-i", source)
        fields = dict(review.optional_field_counts)
        self.assertNotIn("invoice_classification", fields)  # details() carries 適格 / 100%
        self.assertEqual(fields.get("optional_field"), 1)    # the sticky note


if __name__ == "__main__":
    unittest.main()

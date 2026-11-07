"""Same-name / same-abbreviation JDL accounts stay distinct; the subaccount registration worklist
never decides anything. Synthetic values only."""
from __future__ import annotations

import unittest

from accounting_converter.adapters.output.jdl import (
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlSubaccountIdentity,
    JdlTargetContextBuilder,
)
from accounting_converter.adapters.output.jdl.context import JdlTargetContextValidator
from accounting_converter.application import subaccount_registration as reg
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode
from accounting_converter.profiles.known_formats import jdl_ibex_cashbook_official_journal_import_schema_definition


def build(accounts, subaccounts=()):
    return JdlTargetContextBuilder().build(
        target_format_identity=jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
        product="JDL IBEX 出納帳", version="35.5", account_master=accounts, subaccounts=subaccounts,
        departments=(), tax_processing_mode=JdlTaxProcessingMode.EXEMPT, department_processing_enabled=False,
        standard_taxation_confirmed=False, individual_credit_method_confirmed=False,
        confirmation_state=JdlContextConfirmationState.CONFIRMED,
        provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        no_fuzzy_matching=True, no_automatic_replacement=True,
    )


def rules(context):
    return {item.rule_id: item.message for item in JdlTargetContextValidator().validate(context)}


BANK = JdlAccountIdentity("普通預金", "1311", "普通預金", "普通預金")
# A second bank account whose JDL 略名称 is the same as the parent account's name.
OTHER_BANK = JdlAccountIdentity("テスト信金", "1314", "普通預金", "テスト信金")
SALES = JdlAccountIdentity("売掛金", "1551", "売掛金", "売掛金")


class SameAbbreviationAccountsTest(unittest.TestCase):
    def test_accounts_sharing_an_abbreviation_are_distinct_identities(self):
        result = build((BANK, OTHER_BANK, SALES))
        self.assertTrue(result.success, [v.rule_id for v in result.validation_results])

    def test_keying_by_abbreviation_is_refused_and_names_the_codes(self):
        merged = (BANK, JdlAccountIdentity("普通預金", "1314", "普通預金", "テスト信金"), SALES)
        context = build((BANK, SALES)).context
        from dataclasses import replace

        broken = replace(context, account_master=merged, accounts=frozenset(a.mapping_value for a in merged))
        message = rules(broken)["JDL-CONTEXT-ACCOUNT-DUPLICATE"]
        self.assertIn("1311", message)
        self.assertIn("1314", message)
        self.assertNotIn("1551", message)
        self.assertNotIn("テスト信金", message)  # codes only, never names

    def test_duplicate_subaccount_message_names_parent_and_codes(self):
        from dataclasses import replace

        sub = JdlSubaccountIdentity("売掛金", "得意先A", "0001", "0001", "得意先A", True, "1551", "得意先A")
        context = build((BANK, SALES), (sub,)).context
        broken = replace(context, subaccounts=(sub, replace(sub, target_master_code="0002", output_code="0002")))
        message = rules(broken)["JDL-CONTEXT-SUBACCOUNT-DUPLICATE"]
        self.assertIn("1551-0001", message)
        self.assertIn("1551-0002", message)
        self.assertNotIn("得意先A", message)


SUBS = (
    reg.JdlSub("1551", "0016", "㈱テストヤ", True),
    reg.JdlSub("1551", "0028", "テストアロ -ス゛", False),  # JDL name too long for the import field
    reg.JdlSub("1551", "0030", "アルファ商事", True),
    reg.JdlSub("1551", "0031", "ガンマ", True),
    reg.JdlSub("1551", "0032", "ガンマ", True),  # duplicated in JDL: never chosen by name
    reg.JdlSub("3141", "0040", "テストヤ", True),  # other parent
)


class RegistrationWorklistTest(unittest.TestCase):
    def test_categories(self):
        def cat(name, parent="1551"):
            return reg.classify("売掛金", name, parent, 1, SUBS)

        self.assertEqual(cat("テストヤ").category, reg.NOTATION_DIFF)
        self.assertEqual([m.code for m in cat("テストヤ").matched], ["0016"])
        self.assertEqual(cat("テストアローズ").category, reg.JDL_NAME_UNUSABLE)
        self.assertEqual(cat("佐川代引").category, reg.SOURCE_UNCLEAR)
        self.assertEqual(cat("デルタ").category, reg.NEW_REGISTRATION)
        # A similar name is reference only, never a match.
        row = cat("アルファ物産")
        self.assertEqual(row.category, reg.NEW_REGISTRATION)
        self.assertEqual(row.matched, ())
        # Several JDL subaccounts read the same: all shown, none picked.
        self.assertEqual(len(cat("ガンマ").matched), 2)

    def test_name_length_and_order(self):
        long_name = reg.classify("売掛金", "とてもながいとくいさきめい", "1551", 1, SUBS)
        self.assertFalse(long_name.source_name_fits_jdl)
        self.assertEqual(long_name.suggested_new_name, "")
        rows = reg.sort_rows([long_name, reg.classify("売掛金", "テストアローズ", "1551", 1, SUBS)])
        self.assertEqual(rows[0].category, reg.JDL_NAME_UNUSABLE)

    def test_search_key_does_not_change_stored_identity(self):
        self.assertEqual(reg.search_key("ﾃﾞﾙﾀ ㈱"), reg.search_key("デルタ株式会社"))
        self.assertEqual(reg.search_key("テストアロ -ス゛"), reg.search_key("テストアローズ"))


def filled(row, decision, code, name, done=True, parent="1551", source="X"):
    return reg.FilledRow(row, "売掛金", source, parent, decision, code, name, done)


class FilledSheetCheckTest(unittest.TestCase):
    def test_only_exact_usable_unique_rows_marked_done_pass(self):
        ready, problems = reg.check_filled_rows([
            filled(2, "既存補助", "0016", "㈱テストヤ"),
            filled(3, "新規登録", "0099", "デルタ"),                 # not registered yet
            filled(4, "既存補助", "0030", "アルファ"),               # name differs from JDL
            filled(5, "既存補助", "0028", "テストアロ -ス゛"),        # unusable JDL name
            filled(6, "既存補助", "0031", "ガンマ"),                 # ambiguous by name
            filled(7, "既存補助", "0040", "テストヤ"),               # other parent's code
            filled(8, "既存補助", "0030", "アルファ商事", done=False),  # not confirmed: stays open
            filled(9, "保留", "", ""  , done=False),
            filled(10, "OK", "0016", "㈱テストヤ"),
        ], SUBS)
        self.assertEqual([r.sheet_row for r in ready], [2])
        self.assertEqual(sorted(r for r, _ in problems), [3, 4, 5, 6, 7, 10])

    def test_two_sources_on_one_jdl_subaccount_are_flagged(self):
        ready, problems = reg.check_filled_rows([
            filled(2, "既存補助", "0016", "㈱テストヤ", source="A"),
            filled(3, "既存補助", "0016", "㈱テストヤ", source="B"),
        ], SUBS)
        self.assertEqual([r for r, _ in problems], [3])

    def test_done_on_hold_row_is_a_problem(self):
        _ready, problems = reg.check_filled_rows([filled(2, "保留", "", "", done=True)], SUBS)
        self.assertEqual([r for r, _ in problems], [2])


if __name__ == "__main__":
    unittest.main()

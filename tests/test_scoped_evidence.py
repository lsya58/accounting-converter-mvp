"""Campaign Evidence (one exact company scope): registry, scope, composition, output. Synthetic data only.

What is proven here:
- inside the scope the registered conditions are accepted and produce the rows
  that round-tripped on the real JDL (structure of the probe rows);
- every boundary / counter-example stays blocked: another rounding, another or
  unconfirmed row limit, an unobserved layout, tax cell, row pair, account,
  explicit-tax relation, or amount;
- Evidence that existed before keeps precedence, evidence ids and output.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from accounting_converter.adapters.output.jdl import (
    JDL_OUTPUT_METADATA_KEY,
    JdlAccountIdentity,
    JdlContextConfirmationState,
    JdlContextProvenance,
    JdlEvidenceProfile,
    JdlInputTaxCreditMethod,
    JdlOutputPreflight,
    JdlTargetContext,
    JdlTaxationMethod,
    JdlTaxRounding,
    jdl_ibex_35_5_output_profile,
)
from accounting_converter.adapters.output.jdl import scoped_evidence as scoped
from accounting_converter.adapters.output.jdl.scoped_evidence_registry import SCOPED_CASES
from accounting_converter.adapters.output.jdl.tax_semantics import JDL_TAX_LITERALS, JdlTaxSemantic
from accounting_converter.application import moneyforward_tax_excluded_evidence as ev
from accounting_converter.application import scoped_evidence_composition as composition
from accounting_converter.domain.journal import JournalEntry, JournalLine, Side, SourceReference, TaxInfo
from accounting_converter.domain.journal_rows import (
    LINE_ROW_DESCRIPTION_KEY,
    LINE_ROW_KEY,
    ROW_ORDER_KEY,
)
from accounting_converter.domain.mapping import MappingStatus, MappingValue
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.jdl_official import JdlTaxProcessingMode

CODES = {
    "1111": "現金", "3141": "未払金", "3181": "未払費用", "6121": "売上高", "6131": "売上戻り", "6181": "雑売上",
    "7121": "仕入高", "7131": "仕入戻し", "8471": "消耗品費", "8681": "手数料", "8991": "雑費",
    "9111": "受取利息", "9251": "雑収入", "8491": "会議費",
}
# source tax name -> JDL cell (MF names are used only because the test helper
# mappings already exist; the composition is source independent)
SOURCE_TAX = {"NO": "対象外", "S10": "課税売上 10%", "P10": "課税仕入 10%", "NP": "非課税仕入", "NS": "非課税売上",
              "XS": "EXPORT", "R8": "R8", "T80": "T80"}
REF = SourceReference("synthetic", 1)


def context(*, limit=16, sales=JdlTaxRounding.CEILING, purchase=JdlTaxRounding.HALF_UP, **overrides) -> JdlTargetContext:
    base = JdlTargetContext(
        product="JDL IBEX 出納帳", version="35.5",
        accounts=frozenset(CODES.values()),
        account_master=tuple(JdlAccountIdentity(name, code, name, name) for code, name in CODES.items()),
        tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_EXCLUDED,
        taxation_method=JdlTaxationMethod.STANDARD,
        standard_taxation_confirmed=True,
        input_tax_credit_method=JdlInputTaxCreditMethod.PROPORTIONAL,
        confirmation_state=JdlContextConfirmationState.CONFIRMED,
        provenance=JdlContextProvenance.USER_CONFIRMED_RUNTIME_SNAPSHOT,
        sales_tax_rounding=sales, purchase_tax_rounding=purchase, voucher_row_limit=limit,
    )
    return replace(base, **overrides)


def profile(ctx: JdlTargetContext):
    """Human-confirmed tax mappings for every cell (what the review dialog would save)."""
    identity = ev.tax_context_identity_sha256(ctx)
    cells = {
        "NO": JdlTaxSemantic.NO_TAX, "S10": JdlTaxSemantic.SALES_10_EXTERNAL,
        "P10": JdlTaxSemantic.PURCHASE_10_INTERNAL, "NP": JdlTaxSemantic.NON_TAXABLE_PURCHASE,
        "NS": JdlTaxSemantic.NON_TAXABLE_SALES, "XS": JdlTaxSemantic.EXPORT_SALES,
        "R8": JdlTaxSemantic.PURCHASE_REDUCED_8_INTERNAL, "T80": JdlTaxSemantic.PURCHASE_10_TRANSITIONAL_80_INTERNAL,
    }
    mappings = {}
    for cell, semantic in cells.items():
        literal = JDL_TAX_LITERALS[semantic]
        mappings[SOURCE_TAX[cell]] = MappingValue(
            SOURCE_TAX[cell], literal.category, MappingStatus.USER_CONFIRMED,
            metadata={"jdl_tax_scope": literal.scope, "jdl_evidence_id": "TEST",
                      "jdl_tax_processing_mode": ctx.tax_processing_mode.value,
                      "jdl_tax_context_identity_sha256": identity},
        )
    return SimpleNamespace(account_mappings={}, subaccount_context_mappings={}, tax_mappings=mappings)


def side(code, cell, amount, explicit=None):
    return (code, cell, Decimal(amount), None if explicit is None else Decimal(explicit))


def journal(rows, *, description="TEST") -> JournalEntry:
    """rows: [(debit side or None, credit side or None)] -> one balanced-by-caller journal."""
    lines = []
    for number, (debit, credit) in enumerate(rows, start=1):
        for kind, spec in ((Side.DEBIT, debit), (Side.CREDIT, credit)):
            if spec is None:
                continue
            code, cell, amount, explicit = spec
            lines.append(JournalLine(
                kind, CODES[code], amount, REF, tax_info=TaxInfo(category=SOURCE_TAX[cell], tax_amount=explicit),
                metadata={LINE_ROW_KEY: number, LINE_ROW_DESCRIPTION_KEY: f"{description}-R{number}"}))
    return JournalEntry("j1", REF, date(2026, 6, 28), lines, metadata={ROW_ORDER_KEY: tuple(range(1, len(rows) + 1))})


def match(entry, ctx=None):
    ctx = ctx or context()
    return ev.match_evidence_for_occurrence(entry, entry, ctx, profile(ctx))


def sales_journal(count, account="6121", amount="1100", explicit="100"):
    return journal([(side("1111", "NO", amount), side(account, "S10", amount, explicit)) for _ in range(count)])


class RegistryTest(unittest.TestCase):
    def test_registry_is_the_campaign_and_gap_round_passes_plus_the_two_existing_ones(self):
        self.assertEqual(sum(case.row_limit_scope == 16 for case in SCOPED_CASES), 184)  # the 16-row Evidence is untouched
        self.assertEqual(sum(case.row_limit_scope == 64 for case in SCOPED_CASES), 30)  # round 5, 振替伝票入力行数 64
        self.assertEqual(len({case.evidence_id for case in SCOPED_CASES}), len(SCOPED_CASES))
        self.assertEqual(sum("BUDDIES-CAMP" in case.evidence_id for case in SCOPED_CASES), 64)
        self.assertEqual(sum("BUDDIES-GAP-GP" in case.evidence_id or "BUDDIES-GAP-FR" in case.evidence_id
                             for case in SCOPED_CASES), 75)  # 2026-11-06
        self.assertEqual(sum("BUDDIES-GAP-NA-" in case.evidence_id for case in SCOPED_CASES), 12)  # 2026-11-07 new accounts
        self.assertEqual(sum("BUDDIES-GAP-TX-" in case.evidence_id for case in SCOPED_CASES), 15)
        self.assertEqual(sum("BUDDIES-GAP-ST-" in case.evidence_id for case in SCOPED_CASES), 6)
        # 2026-11-07 round 4: voucher-split parts (7) and 非仕入 debit placement (3)
        self.assertEqual(sum("BUDDIES-GAP-SP-" in case.evidence_id for case in SCOPED_CASES), 7)
        self.assertEqual(sum("BUDDIES-GAP-NP-" in case.evidence_id for case in SCOPED_CASES), 3)

    def test_rejected_over_limit_cases_are_not_registered(self):
        sixteen = [case for case in SCOPED_CASES if case.row_limit_scope == 16]
        self.assertEqual(max(len(case.rows) for case in sixteen), 16)
        # A3 (2026-11-05), one gap-round case (2026-11-06) and SP-C1D15 (round 4) are the 16-row cases; none is longer.
        self.assertEqual(sum(len(case.rows) == 16 for case in sixteen), 3)
        self.assertFalse(any(len(case.rows) > scoped.SCOPE_VOUCHER_ROW_LIMIT for case in sixteen))
        # Under 64: nothing above 65 physical rows (the longest voucher imported: 64 lines on one side + 1)
        self.assertEqual(max(len(case.rows) for case in SCOPED_CASES if case.row_limit_scope == 64), 65)

    def test_every_case_is_internally_consistent(self):
        for case in SCOPED_CASES:
            with self.subTest(case=case.case_id):
                kinds = "".join(
                    "B" if debit != "-" and credit != "-" else "D" if debit != "-" else "C" for debit, credit in case.rows)
                runs = []
                for kind in kinds:
                    if runs and runs[-1][0] == kind:
                        runs[-1][1] += 1
                    else:
                        runs.append([kind, 1])
                self.assertEqual(case.layout, "".join(f"{k}{n}" for k, n in runs))
                taxed_in_rows = sum(c not in {"NO", "-"} for row in case.rows for c in row)
                self.assertEqual(len(case.taxed), taxed_in_rows)
                for side_name, cell, account, relation in case.taxed:
                    self.assertIn(side_name, {"DEBIT", "CREDIT"})
                    self.assertIn(cell, scoped.CELL_SEMANTIC)
                    self.assertIn(account, CODES | dict.fromkeys(
                        ("6121", "6131", "6181", "8471", "8991", "7131", "6122", "6123", "6124", "6132", "6142", "7122", "8672", "8451", "8621", "8641", "8751", "7141"), ""))
                    self.assertIn(relation, {"", "COMPANY", "FLOOR", "EXACT", "NONE", "HALF_LOW", "HALF_HIGH", "FLOOR_HIGH"})

    def test_observed_facts_the_implementation_relies_on(self):
        self.assertEqual(set(scoped.CELL_ACCOUNTS[("CREDIT", "S10")]),
                         {"6121", "6131", "6181", "6122", "6123", "6124", "6132", "6142", "9251"})
        self.assertEqual(set(scoped.CELL_ACCOUNTS[("CREDIT", "XS")]), {"6121", "6142"})
        self.assertEqual(set(scoped.CELL_ACCOUNTS[("DEBIT", "R8")]), {"8451", "8471", "8491"})
        self.assertEqual(set(scoped.CELL_ACCOUNTS[("DEBIT", "T80")]), {"7121", "8451", "8471", "8621", "8641", "8751"})
        self.assertEqual(set(scoped.relation_accounts("CREDIT", "S10", "COMPANY")),
                         {"6121", "6131", "6181", "6124", "6132", "6142"})
        self.assertEqual(set(scoped.relation_accounts("CREDIT", "S10", "FLOOR")), {"6121", "6122", "6124", "6132", "6142", "9251"})
        self.assertEqual(set(scoped.relation_accounts("DEBIT", "P10", "COMPANY")), {"8471", "7122", "7141", "8672"})
        self.assertEqual(set(scoped.relation_accounts("DEBIT", "S10", "FLOOR")), {"6131", "6142"})
        # Nothing about 控除不可 (no cell, no semantic) was ever registered.
        self.assertFalse(any("NODED" in case.case_id or "CLOSING" in case.case_id for case in SCOPED_CASES))


class ScopeTest(unittest.TestCase):
    def test_only_the_exact_company_settings_are_in_scope(self):
        self.assertIs(scoped.scope_state(context()), scoped.ScopeState.IN_SCOPE)
        self.assertIs(scoped.scope_state(context(limit=None)), scoped.ScopeState.VOUCHER_ROW_LIMIT_UNCONFIRMED)
        # Same settings but a row limit no real JDL round proved (only 16 and 64 are verified): blocked.
        for limit in (15, 17, 32, 65):
            with self.subTest(limit=limit):
                self.assertIs(scoped.scope_state(context(limit=limit)), scoped.ScopeState.VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED)
        for name, ctx in {
            "floor/floor rounding (ACT)": context(sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR),
            "sales half-up": context(sales=JdlTaxRounding.HALF_UP),
            "purchase ceiling": context(purchase=JdlTaxRounding.CEILING),
            "rounding unconfirmed": context(sales=JdlTaxRounding.UNCONFIRMED, purchase=JdlTaxRounding.UNCONFIRMED),
            "tax included": context(tax_processing_mode=JdlTaxProcessingMode.TAXABLE_TAX_INCLUDED),
            "individual credit method": context(input_tax_credit_method=JdlInputTaxCreditMethod.INDIVIDUAL),
            "unconfirmed context": context(confirmation_state=JdlContextConfirmationState.UNCONFIRMED),
            "other version": context(version="35.4"),
        }.items():
            with self.subTest(name):
                self.assertIs(scoped.scope_state(ctx), scoped.ScopeState.OUT_OF_SCOPE)

    def test_existing_company_contexts_are_never_in_scope(self):
        # MF / ACT contexts: rounding recorded as floor or not at all, no row limit.
        for ctx in (context(limit=None, sales=JdlTaxRounding.UNCONFIRMED, purchase=JdlTaxRounding.UNCONFIRMED),
                    context(limit=None, sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)):
            self.assertIs(scoped.scope_state(ctx), scoped.ScopeState.OUT_OF_SCOPE)
            self.assertEqual(composition.compose_scoped(sales_journal(3), (), has_partner=False, context=ctx), (None, None))


class PlacementTest(unittest.TestCase):
    def test_registered_layout_and_cell_are_accepted(self):
        self.assertEqual(scoped.placement_gaps("B3", [("NO", "S10")] * 3), ())
        self.assertEqual(scoped.placement_gaps("B3", [("NO", "NO")] * 3), ())  # untaxed rows ride on the layout

    def test_cell_never_observed_in_that_layout_is_blocked(self):
        # B3 round-tripped with 売上・仕入・非課税仕入 but never with 輸出売 on the credit side.
        self.assertEqual(scoped.placement_gaps("B3", [("NO", "XS")] * 3), ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",))

    def test_layout_never_observed_is_blocked(self):
        # B11 and B13 round-tripped; B12 and B14 did not (nothing is inferred between observed sizes).
        for layout in ("B12", "B14", "B17", "D2B1", "B1D40"):
            self.assertEqual(scoped.placement_gaps(layout, [("NO", "NO")]), ("VOUCHER_LAYOUT_UNVERIFIED",))

    def test_row_with_tax_on_both_sides_was_never_observed(self):
        self.assertEqual(scoped.placement_gaps("B1", [("P10", "S10")]), ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",))
        self.assertEqual(scoped.placement_gaps("B2", [("NO", "S10"), ("P10", "S10")]),
                         ("VOUCHER_TAX_PLACEMENT_UNVERIFIED",))

    def test_boundary_row_counts(self):
        self.assertEqual(scoped.placement_gaps("B16", [("NO", "NO")] * 16), ())
        self.assertEqual(scoped.placement_gaps("B9", [("NO", "NO")] * 9), ())
        self.assertEqual(scoped.placement_gaps("B8", [("NO", "NO")] * 8), ())  # 2026-11-06
        self.assertEqual(scoped.placement_gaps("B12", [("NO", "NO")] * 12), ("VOUCHER_LAYOUT_UNVERIFIED",))
        self.assertEqual(scoped.placement_gaps("B17", [("NO", "NO")] * 17), ("VOUCHER_LAYOUT_UNVERIFIED",))


class RelationTest(unittest.TestCase):
    def test_three_account_relation_rule_needs_identical_printed_tax_defaults(self):
        peers = scoped.JDL_TAX_SETTING_PEERS[("DEBIT", "P10", "COMPANY")]
        self.assertIn("8681", peers)
        self.assertNotIn("7141", peers)  # prints no 課区/入力: not like the probed accounts
        self.assertTrue(scoped.relation_covers_account("DEBIT", "P10", "COMPANY", "8681"))
        self.assertTrue(scoped.relation_covers_account("DEBIT", "P10", "COMPANY", "7141"))  # exact new probe, not peer expansion
        # Sales stay account-specific whatever the count; two-account relations stay specific.
        self.assertFalse(scoped.relation_covers_account("CREDIT", "S10", "COMPANY", "6122"))
        self.assertFalse(scoped.relation_covers_account("DEBIT", "S10", "FLOOR", "6121"))

    def test_pdf_peer_groups_do_not_authorize_new_tax_relations(self):
        for cell, relation, observed_account in (
            ("R8", "HALF_LOW", "8491"),
            ("T80", "EXACT", "7121"),
            ("T80", "FLOOR_HIGH", "8621"),
            ("T80", "HALF_HIGH", "8751"),
            ("T80", "HALF_LOW", "8641"),
        ):
            key = ("DEBIT", cell, relation)
            with self.subTest(key=key):
                self.assertIn("8681", scoped.JDL_TAX_SETTING_PEERS[key])
                self.assertNotIn(key, scoped.JDL_TAX_RELATION_AUTHORIZED_PEERS)
                self.assertTrue(scoped.relation_covers_account(*key, observed_account))
                self.assertFalse(scoped.relation_covers_account(*key, "8681"))

    def test_pdf_metadata_change_cannot_expand_the_frozen_allowlist(self):
        from unittest.mock import patch

        key = ("DEBIT", "P10", "COMPANY")
        with patch.dict(scoped.JDL_TAX_SETTING_PEERS, {key: frozenset({"9999"})}):
            self.assertTrue(scoped.relation_covers_account(*key, "8681"))
            self.assertFalse(scoped.relation_covers_account(*key, "9999"))

    def test_a_round_trip_on_an_account_with_other_defaults_does_not_withdraw_a_group(self):
        from accounting_converter.tools.build_scoped_evidence_registry import setting_peers

        keys = {"8471": "仕入内税", "7122": "仕入内税", "8672": "仕入内税", "8681": "仕入内税", "7141": ""}
        cases = [{"taxed": (("DEBIT", "P10", code, "COMPANY"),)} for code in ("8471", "7122", "8672")]
        before = setting_peers(cases, keys)
        after = setting_peers(cases + [{"taxed": (("DEBIT", "P10", "7141", "COMPANY"),)}], keys)
        self.assertEqual(before, after)  # 7141 is covered by its own round trip only
        self.assertIn("8681", after[("DEBIT", "P10", "COMPANY")])
        self.assertNotIn("7141", after[("DEBIT", "P10", "COMPANY")])
        two = setting_peers(cases[:2], keys)
        self.assertEqual(two, {})  # fewer than three accounts with the same defaults: no widening
        sales = setting_peers([{"taxed": (("CREDIT", "S10", c, "FLOOR"),)} for c in ("8471", "7122", "8672")], keys)
        self.assertEqual(sales, {})  # 課税売上10% credit stays account-specific

    def test_amount_relations_are_classified_for_this_scopes_rounding(self):
        d = Decimal
        self.assertEqual(scoped.relation_of("S10", d(1100), d(100)), "")
        self.assertEqual(scoped.relation_of("S10", d(1105), d(101)), "COMPANY")  # round up
        self.assertEqual(scoped.relation_of("S10", d(1105), d(100)), "FLOOR")
        self.assertIsNone(scoped.relation_of("S10", d(1105), d(102)))
        self.assertEqual(scoped.relation_of("P10", d(1106), d(101)), "COMPANY")  # round half up
        self.assertEqual(scoped.relation_of("P10", d(1106), d(100)), "FLOOR")
        self.assertEqual(scoped.relation_of("P10", d(1101), d(100)), "")  # floor == half-up
        self.assertIsNone(scoped.relation_of("P10", d(1100), d(99)))
        self.assertEqual(scoped.relation_of("R8", d(1080), d(80)), "EXACT")
        # A fractional exact value is classified; allowed only where it round-tripped (8471, 2026-11-06).
        self.assertEqual(scoped.relation_of("R8", d(1081), d(80)), "HALF_LOW")
        self.assertTrue(scoped.relation_covers_account("DEBIT", "R8", "HALF_LOW", "8471"))
        self.assertFalse(scoped.relation_covers_account("DEBIT", "R8", "HALF_LOW", "8681"))
        self.assertIsNone(scoped.relation_of("R8", d(1080), d(81)))
        self.assertIsNone(scoped.relation_of("R8", d(1080), None))
        self.assertEqual(scoped.relation_of("T80", d(1100), d(80)), "EXACT")
        self.assertIsNone(scoped.relation_of("T80", d(1100), d(100)))  # the full 10% tax is not the 80% tax
        self.assertEqual(scoped.relation_of("T80", d(1105), d(80)), "HALF_LOW")
        self.assertTrue(scoped.relation_covers_account("DEBIT", "T80", "HALF_LOW", "8471"))
        self.assertEqual(scoped.relation_of("XS", d(11000), None), "NONE")
        self.assertIsNone(scoped.relation_of("XS", d(11000), d(1000)))
        self.assertEqual(scoped.relation_of("NP", d(1100), None), "NONE")


class CompositionTest(unittest.TestCase):
    def assertScoped(self, entry, ctx=None):
        result = match(entry, ctx)
        self.assertIsNotNone(result.evidence, result.mismatch_fields)
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL)
        self.assertEqual(result.evidence.evidence_id, scoped.SCOPED_ROUTE_ID)
        self.assertIn(scoped.VOUCHER_ROW_LIMIT_EVIDENCE_ID, result.evidence.supporting_evidence_ids)
        return result

    def assertGap(self, entry, gap, ctx=None):
        result = match(entry, ctx)
        self.assertIsNone(result.evidence)
        self.assertIn(gap, result.mismatch_fields)

    def test_3d3c_and_4d4c_sales_are_released_with_their_evidence(self):
        for count, case_id in ((3, "BUD-SALES-3D3C"), (4, "BUD-SALES-4D4C")):
            result = self.assertScoped(sales_journal(count))
            self.assertTrue(any(case_id.split("-")[-1].lower() in i.lower() for i in result.evidence.supporting_evidence_ids))

    def test_existing_evidence_keeps_precedence_and_its_output(self):
        # 1D1C purchase: the MF composition covers it, so the scoped route is not used.
        result = match(journal([(side("8681", "P10", "1100", "100"), side("1111", "NO", "1100"))]))
        self.assertIs(result.evidence.profile, JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111)
        self.assertNotEqual(result.evidence.evidence_id, scoped.SCOPED_ROUTE_ID)

    def test_sales_accounts_decide_the_scope(self):
        for account in ("6121", "6131", "6181"):
            self.assertScoped(sales_journal(3, account))
        self.assertGap(sales_journal(3, "8471"), "TAX_ACCOUNT_UNVERIFIED")  # not a verified sales account
        self.assertGap(sales_journal(3, "9111"), "TAX_ACCOUNT_UNVERIFIED")

    def test_explicit_tax_relations_are_kept_only_where_observed(self):
        company = lambda account: sales_journal(1, account, "1105", "101")  # noqa: E731
        floor = lambda account: sales_journal(1, account, "1105", "100")  # noqa: E731
        for account in ("6121", "6131", "6181"):
            self.assertScoped(company(account))
        self.assertGap(company("9251"), "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED")  # round-tripped only without a fraction
        self.assertScoped(floor("6121"))
        self.assertGap(floor("6131"), "EXPLICIT_TAX_KEEP_UNVERIFIED")  # floor was observed on 6121 only
        self.assertGap(sales_journal(1, "6121", "1105", "102"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")

    def test_purchase_explicit_tax_company_value_reaches_only_same_jdl_default_accounts(self):
        entry = lambda account, tax: journal([(side(account, "P10", "1106", tax), side("1111", "NO", "1106"))])  # noqa: E731
        self.assertScoped(entry("8471", "101"))
        # Round-tripped on 8471, 7122, 8672 (all printed 仕入・内税); 8681 prints the same defaults.
        self.assertScoped(entry("8681", "101"))
        # 3141 prints no tax defaults in the JDL 科目一覧: never covered by the three-account rule.
        self.assertGap(entry("3141", "101"), "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED")
        self.assertGap(entry("8471", "99"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")

    def test_new_tax_cells_apply_to_the_observed_accounts_and_exact_amounts_only(self):
        export = lambda account, amount="11000": journal([(side("1111", "NO", amount), side(account, "XS", amount))])  # noqa: E731
        self.assertScoped(export("6121"))
        self.assertGap(export("6131"), "TAX_ACCOUNT_UNVERIFIED")
        reduced = lambda account, amount, tax: journal([(side(account, "R8", amount, tax), side("1111", "NO", amount))])  # noqa: E731
        self.assertScoped(reduced("8471", "1080", "80"))
        self.assertGap(reduced("8681", "1080", "80"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")
        self.assertScoped(reduced("8471", "1081", "80"))  # fraction kept by JDL (2026-11-06, HALF_LOW)
        self.assertGap(reduced("8471", "1081", "81"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")  # ceil of a low fraction
        self.assertGap(reduced("8471", "1200", "88"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")  # FLOOR_HIGH never probed for 8%
        self.assertGap(reduced("8471", "1080", None), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")
        transitional = lambda amount, tax: journal([(side("8471", "T80", amount, tax), side("1111", "NO", amount))])  # noqa: E731
        self.assertScoped(transitional("1100", "80"))
        self.assertScoped(transitional("2200", "160"))
        self.assertGap(transitional("1100", "100"), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")

    def test_new_cells_in_a_two_row_voucher(self):
        entry = journal([
            (side("1111", "NO", "1100"), side("6121", "XS", "1100")),
            (side("1111", "NO", "1100"), side("3181", "NO", "1100")),
        ])
        self.assertScoped(entry)

    def test_tax_cell_not_observed_in_the_layout_is_blocked(self):
        # B3 round-tripped, but never with 輸出売 on the credit side.
        entry = journal([(side("1111", "NO", "1100"), side("6121", "XS", "1100"))] * 3)
        self.assertGap(entry, "VOUCHER_TAX_PLACEMENT_UNVERIFIED")

    def test_unobserved_layout_is_blocked_even_when_every_cell_is_known(self):
        self.assertScoped(sales_journal(11))  # B11 round-tripped
        self.assertGap(sales_journal(12), "VOUCHER_LAYOUT_UNVERIFIED")  # B12 did not

    def test_row_limit_is_a_hard_stop_before_any_evidence(self):
        entry = sales_journal(17)
        self.assertGap(entry, "VOUCHER_ROW_LIMIT_EXCEEDED")
        self.assertNotIn("VOUCHER_LAYOUT_UNVERIFIED", match(entry).mismatch_fields)
        # A limit no real round proved: only that is reported (and the limit JDL enforces anyway).
        self.assertEqual(composition.compose_scoped(
            sales_journal(3), match(sales_journal(3)).actual_signature, has_partner=False, context=context(limit=2)),
            (None, ("VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED", "VOUCHER_ROW_LIMIT_EXCEEDED")))
        self.assertEqual(composition.compose_scoped(
            sales_journal(3), match(sales_journal(3)).actual_signature, has_partner=False, context=context(limit=32)),
            (None, ("VOUCHER_ROW_LIMIT_SETTING_UNVERIFIED",)))
        # the exact limit passes
        self.assertScoped(journal([(side("1111", "NO", "1100"), side("3181", "NO", "1100"))] * 16))

    def test_unconfirmed_row_limit_is_never_assumed(self):
        result = match(sales_journal(3), context(limit=None))
        self.assertIsNone(result.evidence)
        self.assertIn("VOUCHER_ROW_LIMIT_UNCONFIRMED", result.mismatch_fields)

    def test_other_company_settings_do_not_get_the_scoped_evidence(self):
        for ctx in (context(limit=17), context(sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)):
            result = match(sales_journal(3), ctx)
            self.assertIsNone(result.evidence)
            self.assertNotIn("VOUCHER_ROW_LIMIT_UNCONFIRMED", result.mismatch_fields)

    def test_blank_subaccount_required_by_master_stays_a_human_gap(self):
        """Regression (2026-11-06 audit): compose_capabilities refuses a blank
        subaccount on a parent the master requires one for; compose_scoped must
        refuse it too, not just leave it to the output stage."""
        from accounting_converter.adapters.output.jdl import JdlSubaccountIdentity

        ctx = replace(context(), subaccounts=(
            JdlSubaccountIdentity("未払費用", "未払A", "0001", "0001", "未払A", True,
                                  parent_account_code="3181", target_name="未払A"),
        ))
        entry = journal([(side("1111", "NO", "1100"), side("3181", "NO", "1100"))])  # blank subaccount on 3181
        result = ev.match_evidence_for_occurrence(entry, entry, ctx, profile(ctx))
        self.assertIsNone(result.evidence)
        self.assertIn("SUBACCOUNT_REQUIRED_BY_MASTER", result.mismatch_fields)
        # the same account with no registered subaccounts at all is unaffected
        self.assertScoped(sales_journal(3))

    def test_unmapped_tax_stays_a_human_gap(self):
        ctx = context()
        result = ev.match_evidence_for_occurrence(sales_journal(3), sales_journal(3), ctx, SimpleNamespace(
            account_mappings={}, subaccount_context_mappings={}, tax_mappings={}))
        self.assertIsNone(result.evidence)
        self.assertIn("TAX_MAPPING_UNCONFIRMED", result.mismatch_fields)

    def test_united_capabilities_follow_the_three_account_rule(self):
        caps = composition.UNITED_CAPABILITIES
        self.assertTrue(caps[("DEBIT", JdlTaxSemantic.SALES_10_EXTERNAL.value)].account_independent)  # 3 accounts
        self.assertFalse(caps[("CREDIT", JdlTaxSemantic.SALES_10_EXTERNAL.value)].account_independent)  # never
        self.assertTrue(caps[("CREDIT", JdlTaxSemantic.PURCHASE_10_INTERNAL.value)].account_independent)
        self.assertTrue(caps[("DEBIT", JdlTaxSemantic.NON_TAXABLE_PURCHASE.value)].account_independent)
        self.assertFalse(caps[("CREDIT", JdlTaxSemantic.EXPORT_SALES.value)].account_independent)
        self.assertEqual(caps[("CREDIT", JdlTaxSemantic.SALES_10_EXTERNAL.value)].verified_accounts,
                         {"6121", "6131", "6181", "9251", "6122", "6123", "6124", "6132", "6142"})
        self.assertFalse(caps[("CREDIT", JdlTaxSemantic.SALES_10_EXTERNAL.value)].covers("6141"))  # added, never probed


class OutputTest(unittest.TestCase):
    def rows_of(self, entry, ctx=None):
        ctx = ctx or context()
        found = ev.evidence_for_occurrence(entry, entry, ctx, profile(ctx))
        self.assertIsNotNone(found)
        literal = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = found.profile.value
        return JdlOutputPreflight(ctx).evaluate((literal,), jdl_ibex_35_5_output_profile())

    def test_3d3c_rows_are_the_rows_that_round_tripped_on_the_real_jdl(self):
        result = self.rows_of(sales_journal(3))
        self.assertEqual(result.validation_results, ())
        rows = result.plan.rows
        self.assertEqual([row.identifier_flag for row in rows], ["1110", "1100", "1101"])
        for row in rows:
            self.assertEqual((row.debit_account_code, row.credit_account_code), ("1111", "6121"))
            self.assertEqual((row.credit_tax_scope, row.credit_tax_category, row.credit_tax_input_method), ("売　上", "10%", "外税"))
            self.assertEqual((row.debit_amount, row.credit_amount, row.credit_tax_amount, row.debit_tax_amount), ("1100", "1100", "100", ""))
        self.assertEqual([row.description for row in rows], ["TEST-R1", "TEST-R2", "TEST-R3"])

    def test_single_row_new_cells_use_the_observed_literals(self):
        export = self.rows_of(journal([(side("1111", "NO", "11000"), side("6121", "XS", "11000"))])).plan.rows[0]
        self.assertEqual(export.identifier_flag, "1111")
        self.assertEqual((export.credit_tax_scope, export.credit_tax_category, export.credit_tax_input_method,
                          export.credit_tax_amount), ("輸出売", "", "", ""))
        reduced = self.rows_of(journal([(side("8471", "R8", "1080", "80"), side("1111", "NO", "1080"))])).plan.rows[0]
        self.assertEqual((reduced.debit_tax_scope, reduced.debit_tax_category, reduced.debit_tax_input_method,
                          reduced.debit_tax_amount), ("仕　入", "軽減8%", "内税", "80"))
        transitional = self.rows_of(journal([(side("8471", "T80", "1100", "80"), side("1111", "NO", "1100"))])).plan.rows[0]
        self.assertEqual((transitional.debit_tax_scope, transitional.debit_tax_category, transitional.debit_tax_input_method,
                          transitional.debit_tax_amount), ("仕　入", "10%免80", "内税", "80"))

    def test_company_rounded_explicit_tax_is_written_as_the_source_gave_it(self):
        row = self.rows_of(sales_journal(1, "6131", "1105", "101")).plan.rows[0]
        self.assertEqual((row.credit_amount, row.credit_tax_amount), ("1105", "101"))

    def test_output_stage_independently_refuses_an_unobserved_account_even_if_a_caller_forged_the_profile(self):
        """Regression (2026-11-06 audit): the output stage must not trust the profile tag alone.

        relation_of only classifies the AMOUNT relation (company-rounded /
        floor / exact), not the account; composition additionally gates by
        account. If something upstream ever tags a journal with the scoped
        profile without going through composition (a bug, a future caller),
        the output stage must still catch an account that never round-tripped
        for that relation -- not just the ones composition would never produce.
        """
        ctx = context()
        entry = journal([(side("1111", "NO", "1105"), side("9251", "S10", "1105", None))])
        entry = replace(entry, lines=[
            replace(entry.lines[0], tax_info=None),
            replace(entry.lines[1], tax_info=TaxInfo(
                category="10%", rate=Decimal("10"), tax_inclusion="EXCLUDED", tax_amount=Decimal("101"),
                metadata={"jdl_tax_scope": "売　上", "jdl_tax_input_method": "外税"})),
        ])
        entry.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL.value
        result = JdlOutputPreflight(ctx).evaluate((entry,), jdl_ibex_35_5_output_profile())
        self.assertFalse(result.supported)
        self.assertIn("JDL-OUT-TAX-AMOUNT-PATTERN", {item.rule_id for item in result.validation_results})
        # the same relation on an account that DID round-trip still passes
        ok = self.rows_of(sales_journal(1, "6121", "1105", "101"))
        self.assertEqual(ok.validation_results, ())

    def test_preflight_refuses_what_composition_would_not_release(self):
        ctx = context()
        entry = sales_journal(3)
        literal = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.SCOPED_COMPOSED_TAX_EXCLUDED_PROPORTIONAL.value

        def errors(entry_, ctx_=ctx):
            return {item.rule_id for item in JdlOutputPreflight(ctx_).evaluate((entry_,), jdl_ibex_35_5_output_profile()).validation_results}

        self.assertEqual(errors(literal), set())
        # another company setting
        self.assertIn("JDL-OUT-SCOPED-CONTEXT", errors(literal, context(sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)))
        self.assertIn("JDL-OUT-SCOPED-CONTEXT", errors(literal, context(limit=None)))
        # a row-limit setting no real round proved (e.g. 64): nothing is written
        self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT-SETTING", errors(literal, context(limit=32)))
        self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT-SETTING", errors(literal, context(limit=2)))
        # a tax amount that JDL was never shown to keep
        tampered = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
        tampered.metadata[JDL_OUTPUT_METADATA_KEY] = literal.metadata[JDL_OUTPUT_METADATA_KEY]
        tampered.lines[1].tax_info = replace(tampered.lines[1].tax_info, tax_amount=Decimal("99"))
        self.assertIn("JDL-OUT-TAX-AMOUNT-PATTERN", errors(tampered))
        # a literal that is not exactly an observed one
        wrong = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
        wrong.metadata[JDL_OUTPUT_METADATA_KEY] = literal.metadata[JDL_OUTPUT_METADATA_KEY]
        wrong.lines[1].tax_info.metadata["jdl_tax_input_method"] = "内税"
        self.assertIn("JDL-OUT-TAX-LITERAL", errors(wrong))
        # a layout that never round-tripped
        unobserved = sales_journal(12)
        # literals applied directly: the point is that the OUTPUT stage refuses it on its own
        literal8 = ev.apply_tax_literals(unobserved, unobserved, "TEST", profile=profile(ctx), context=ctx)
        literal8.metadata[JDL_OUTPUT_METADATA_KEY] = literal.metadata[JDL_OUTPUT_METADATA_KEY]
        self.assertIn("JDL-OUT-SCOPED-LAYOUT", errors(literal8))

    def test_row_limit_applies_to_every_profile_only_when_the_human_confirmed_it(self):
        # A company outside the campaign scope (another rounding): its confirmed limit still applies to every profile.
        ctx = context(limit=2, sales=JdlTaxRounding.FLOOR, purchase=JdlTaxRounding.FLOOR)
        entry = journal([(side("8681", "P10", "1100", "100"), side("1111", "NO", "1100"))])
        literal = ev.apply_verified_tax_semantics(entry, entry, ctx, profile(ctx))
        literal.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.MF_TAX_EXCLUDED_PROPORTIONAL_1111.value
        self.assertEqual(JdlOutputPreflight(ctx).evaluate((literal,), jdl_ibex_35_5_output_profile()).validation_results, ())
        three = sales_journal(3)
        literal3 = ev.apply_verified_tax_semantics(three, three, ctx, profile(ctx))
        literal3.metadata[JDL_OUTPUT_METADATA_KEY] = JdlEvidenceProfile.MF_COMPOUND_TAX_EXCLUDED_PROPORTIONAL.value
        errors = {i.rule_id for i in JdlOutputPreflight(ctx).evaluate((literal3,), jdl_ibex_35_5_output_profile()).validation_results}
        self.assertIn("JDL-OUT-VOUCHER-ROW-LIMIT", errors)


class ContextStorageTest(unittest.TestCase):
    def roundtrip(self, ctx):
        loader = JdlTargetContextLoader()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text(loader.to_json_text(ctx), encoding="utf-8")
            return loader.load(path), path.read_text(encoding="utf-8")

    def test_row_limit_is_written_only_when_confirmed_so_existing_files_keep_their_bytes(self):
        loaded, text = self.roundtrip(context(limit=None))
        self.assertNotIn("voucher_row_limit", text)
        self.assertIsNone(loaded.voucher_row_limit)
        loaded, text = self.roundtrip(context(limit=16))
        self.assertIn('"voucher_row_limit": 16', text)
        self.assertEqual(loaded.voucher_row_limit, 16)
        # nothing else in the file changes when the limit is added
        without = JdlTargetContextLoader().to_json_text(context(limit=None))
        with_limit = JdlTargetContextLoader().to_json_text(context(limit=16))
        self.assertEqual(with_limit.replace(',\n  "voucher_row_limit": 16\n}', '\n}'), without)

    def test_invalid_limits_are_rejected(self):
        loader = JdlTargetContextLoader()
        base = loader.to_json_text(context(limit=None)).rstrip().rstrip("}") + ',\n  "voucher_row_limit": %s\n}\n'
        for value in ("0", "-3", "true", '"16"', "16.5"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "context.json"
                path.write_text(base % value, encoding="utf-8")
                with self.assertRaises(Exception, msg=value):
                    loader.load(path)


if __name__ == "__main__":
    unittest.main()

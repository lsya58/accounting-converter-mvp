"""Yayoi 仕訳日記帳 → JDL workflow end to end, synthetic data only."""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.adapters.input.yayoi.journal_report_parser import YayoiJournalReportParser
from accounting_converter.adapters.output.jdl.tax_semantics import JdlTaxSemantic
from accounting_converter.application.moneyforward_conversion_workflow import MoneyForwardConversionWorkflow
from accounting_converter.application.yayoi_jdl_workflow import YayoiJournalReportJdlWorkflow
from accounting_converter.application.yayoi_review import (
    confirm_tax_identity,
    create_yayoi_profile,
    review_source,
    save_description_replacement,
)
from accounting_converter.application.first_release_workflow import FirstReleaseReadiness
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_target_context_loader import JdlTargetContextLoader
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)
from tests.test_mf_tax_capability_composition import ACCOUNTS, context
from tests.test_yayoi_journal_report_parser import build, detail, write

# Yayoi-side names are deliberately different from the JDL names.
YAYOI = {"bank": "当座預金Y", "fee": "支払手数料Y", "cash": "現金Y", "sales": "売上Y"}
TARGET = {"bank": "1311", "fee": "8681", "cash": "1111", "sales": "6121"}
PURCHASE, SALES, OUTSIDE = "課対仕入内10%", "課税売上内10%", "対象外"


def details(*, half_up=False, closing="", long_description=False):
    amount, tax = (1106, 101) if half_up else (1100, 100)
    return [
        detail("令和08年05月10日", 1, debit=(YAYOI["fee"], "", PURCHASE, amount, tax),
               credit=(YAYOI["bank"], "口座A", OUTSIDE, amount, None), invoice="適格", credit_ratio="100%",
               description="手数料" * (12 if long_description else 1), number=1, closing=closing),
        detail("令和08年05月11日", 2, debit=(YAYOI["cash"], "", OUTSIDE, 2200, None),
               credit=(YAYOI["sales"], "", SALES, 2200, 200), description="売上", number=2),
    ]


class Fixture:
    def __init__(self, directory: Path, rows) -> None:
        self.directory = directory
        self.source = write(directory, build(rows))
        self.entries = YayoiJournalReportParser().parse_path(self.source)
        self.profiles = ConversionProfileStore(directory / "profiles")
        self.companies = CompanySettingStore(directory / "companies", self.profiles)
        self.context = context()
        context_path = directory / "context.json"
        context_path.write_text(JdlTargetContextLoader().to_json_text(self.context), encoding="utf-8")
        self.profile = create_yayoi_profile(self.profiles, "テスト顧問先", self.entries)
        self.companies.create(
            company_setting_id="company-yayoi", display_name="テスト顧問先",
            conversion_profile_id=self.profile.profile_id, context_source=context_path,
        )

    def confirm_accounts(self) -> None:
        profile = self.profiles.get(self.profile.profile_id)
        accounts = {
            YAYOI[key]: MappingValue(
                YAYOI[key], ACCOUNTS[TARGET[key]], MappingStatus.USER_CONFIRMED,
                metadata={"target_code": TARGET[key], "target_printed_name": ACCOUNTS[TARGET[key]],
                          "target_formal_name": ACCOUNTS[TARGET[key]]},
            )
            for key in YAYOI
        }
        subs = {
            MappingKey(MappingType.SUBACCOUNT, "口座A", YAYOI["bank"]): MappingValue(
                "口座A", "銀行A", MappingStatus.USER_CONFIRMED, parent_account=YAYOI["bank"],
                metadata={"output_code": "0002", "target_code": "0002", "output_name": "銀行A"},
            )
        }
        self.profiles.update(replace(profile, account_mappings=accounts, subaccount_context_mappings=subs))
        self._rebind()

    def confirm_taxes(self, identities=None) -> None:
        semantics = {
            f"{PURCHASE}｜適格｜100%": JdlTaxSemantic.PURCHASE_10_INTERNAL,
            SALES: JdlTaxSemantic.SALES_10_EXTERNAL,
            OUTSIDE: JdlTaxSemantic.NO_TAX,
        }
        for identity, semantic in semantics.items():
            if identities is None or identity in identities:
                confirm_tax_identity(self.profiles, self.profile.profile_id, self.context, identity, semantic)
        self._rebind()

    def _rebind(self) -> None:
        self.companies.replace_profile("company-yayoi", self.profile.profile_id)

    def resolved(self):
        return self.companies.resolve("company-yayoi")


class YayoiJdlWorkflowTest(unittest.TestCase):
    def test_without_target_company_every_journal_needs_human_setup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = write(directory, build(details()))
            assessment = YayoiJournalReportJdlWorkflow().assess(source, None, None)
            review = review_source(YayoiJournalReportParser().parse_path(source))
        self.assertEqual(assessment.owner_counts(), {"HUMAN": 2})
        self.assertEqual({t.mapping_state for t in review.taxes}, {"TARGET_REQUIRED"})
        self.assertEqual(review.setting_item_counts["tax_identities"], 3)

    def test_partial_save_then_ready_and_formal_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fx = Fixture(Path(directory), details())
            workflow = YayoiJournalReportJdlWorkflow()
            first = workflow.assess(fx.source, fx.resolved().profile, fx.resolved().context)
            self.assertIn("HUMAN:TAX_MAPPING", first.blocker_counts())
            self.assertIn("HUMAN:ACCOUNT_MAPPING", first.blocker_counts())

            fx.confirm_accounts()
            fx.confirm_taxes({OUTSIDE})  # partial: only one identity confirmed
            states = {t.identity: t.mapping_state for t in review_source(fx.entries, fx.resolved().profile, fx.context).taxes}
            self.assertEqual(states[OUTSIDE], "CONFIRMED")
            self.assertEqual(states[SALES], "UNCONFIRMED")
            self.assertIn("HUMAN:TAX_MAPPING", workflow.assess(fx.source, fx.resolved().profile, fx.context).blocker_counts())

            fx.confirm_taxes()
            resolved = fx.resolved()
            self.assertEqual(workflow.assess(fx.source, resolved.profile, resolved.context).ready_journals, 2)
            output = Path(directory) / "out" / "jdl.csv"
            prepared = workflow.prepare(input_path=fx.source, output_path=output, profile=resolved.profile,
                                        context=resolved.context, company_setting_validated=resolved.available)
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.READY, prepared.summary.blocking_reasons)
            result = workflow.execute(prepared)
            self.assertEqual(result.status.value, "SUCCESS", [v.rule_id for v in result.validation_results])
            rows = [r for r in csv.reader(io.StringIO(output.read_bytes().decode("cp932"))) if r and r[0].isdigit()]
            self.assertEqual([r[0] for r in rows], ["1111", "1111"])
            self.assertEqual((rows[0][8], rows[0][9], rows[0][10], rows[0][12]), ("仕　入", "10%", "内税", "100"))
            self.assertEqual((rows[1][18], rows[1][19], rows[1][20], rows[1][22]), ("売　上", "10%", "外税", "200"))
            self.assertEqual(rows[0][16:18], ["0002", "銀行A"])

    def test_unverified_or_unrepresentable_information_blocks(self) -> None:
        cases = {
            "HUMAN:JDL_TAX_ROUNDING_SETTING": details(half_up=True),
            "SYSTEM_EVIDENCE:CLOSING_ENTRY_REPRESENTATION": details(closing="本決"),
            "HUMAN:DESCRIPTION_REPLACEMENT": details(long_description=True),
        }
        for blocker, rows in cases.items():
            with self.subTest(blocker=blocker), tempfile.TemporaryDirectory() as directory:
                fx = Fixture(Path(directory), rows)
                fx.confirm_accounts()
                fx.confirm_taxes()
                resolved = fx.resolved()
                workflow = YayoiJournalReportJdlWorkflow()
                self.assertIn(blocker, workflow.assess(fx.source, resolved.profile, resolved.context).blocker_counts())
                output = Path(directory) / "blocked.csv"
                prepared = workflow.prepare(input_path=fx.source, output_path=output, profile=resolved.profile,
                                            context=resolved.context, company_setting_validated=True)
                self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
                self.assertIsNone(workflow.execute(prepared))
                self.assertFalse(output.exists())

    def test_explicit_tax_is_safe_only_when_keep_and_recompute_agree(self) -> None:
        from decimal import Decimal as D

        from accounting_converter.adapters.output.jdl import JdlTaxRounding as R
        from accounting_converter.application.moneyforward_tax_excluded_evidence import explicit_tax_gap

        purchase = JdlTaxSemantic.PURCHASE_10_INTERNAL.value
        sales = JdlTaxSemantic.SALES_10_EXTERNAL.value
        base = context()

        def gap(explicit, amount, tax, sales_rounding=R.UNCONFIRMED, purchase_rounding=R.UNCONFIRMED):
            target = replace(base, sales_tax_rounding=sales_rounding, purchase_tax_rounding=purchase_rounding)
            return explicit_tax_gap(D(explicit), D(amount), tax, target)

        # No fraction: every setting agrees, nothing to confirm.
        self.assertIsNone(gap(100, 1100, purchase))
        # 1106 -> floor 100 / half-up 101 / ceiling 101.
        self.assertEqual(gap(100, 1106, purchase), "JDL_TAX_ROUNDING_UNCONFIRMED")
        self.assertIsNone(gap(100, 1106, purchase, purchase_rounding=R.FLOOR))
        self.assertEqual(gap(100, 1106, purchase, purchase_rounding=R.HALF_UP), "EXPLICIT_TAX_KEEP_UNVERIFIED")
        self.assertEqual(gap(101, 1106, purchase, purchase_rounding=R.HALF_UP),
                         "EXPLICIT_TAX_COMPANY_ROUNDING_UNVERIFIED")
        self.assertEqual(gap(101, 1106, purchase, purchase_rounding=R.FLOOR), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")
        # Sales and purchase settings are independent.
        self.assertIsNone(gap(100, 1106, sales, sales_rounding=R.FLOOR, purchase_rounding=R.HALF_UP))
        self.assertEqual(gap(100, 1106, sales, sales_rounding=R.CEILING, purchase_rounding=R.FLOOR),
                         "EXPLICIT_TAX_KEEP_UNVERIFIED")
        # Purchase-credit ratio applied (80%): matches no rounding rule.
        self.assertEqual(gap(80, 1100, purchase, purchase_rounding=R.FLOOR), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")
        # Untaxed lines must carry 0.
        self.assertIsNone(gap(0, 1106, JdlTaxSemantic.NO_TAX.value))
        self.assertEqual(gap(5, 1106, JdlTaxSemantic.NO_TAX.value), "EXPLICIT_TAX_AMOUNT_UNVERIFIED")

    def test_rounding_setting_survives_save_and_load_and_is_omitted_when_unset(self) -> None:
        from accounting_converter.adapters.output.jdl import JdlTaxRounding as R

        loader = JdlTargetContextLoader()
        unset = loader.to_json_text(context())
        self.assertNotIn("tax_rounding", unset)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text(loader.to_json_text(
                replace(context(), sales_tax_rounding=R.CEILING, purchase_tax_rounding=R.HALF_UP)
            ), encoding="utf-8")
            loaded = loader.load(path)
        self.assertEqual((loaded.sales_tax_rounding, loaded.purchase_tax_rounding), (R.CEILING, R.HALF_UP))

    def test_description_replacement_is_saved_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fx = Fixture(Path(directory), details(long_description=True))
            fx.confirm_accounts()
            fx.confirm_taxes()
            original = "手数料" * 12
            save_description_replacement(fx.profiles, fx.profile.profile_id, original, "振込手数料")
            fx._rebind()
            resolved = fx.resolved()
            assessment = YayoiJournalReportJdlWorkflow().assess(fx.source, resolved.profile, resolved.context)
            self.assertEqual(assessment.ready_journals, 2)
            self.assertEqual(review_source(fx.entries, resolved.profile, fx.context).descriptions, ())

    def test_company_settings_do_not_mix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fx = Fixture(Path(directory), details())
            fx.confirm_accounts()
            fx.confirm_taxes()
            now = datetime.now(timezone.utc)
            mf_profile = fx.profiles.create(ConversionProfile(
                "mf-other-company", "他社 MF → JDL",
                moneyforward_cloud_journal_export_observed_schema().identity,
                jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
                created_at=now, updated_at=now,
            ))
            # The Yayoi workflow refuses a MF company's profile.
            blocked = YayoiJournalReportJdlWorkflow().assess(fx.source, mf_profile, fx.context)
            self.assertIn("HUMAN:COMPANY_SETTING_SOURCE_MISMATCH", blocked.blocker_counts())
            self.assertEqual(blocked.ready_journals, 0)
            # The MF workflow refuses the Yayoi profile.
            prepared = MoneyForwardConversionWorkflow().prepare(
                input_path=fx.source, output_path=Path(directory) / "x.csv",
                profile=fx.resolved().profile, context=fx.context, company_setting_validated=True,
            )
            self.assertIs(prepared.summary.readiness, FirstReleaseReadiness.BLOCKED)
            # Confirming in one company does not touch the other.
            self.assertEqual(fx.profiles.get("mf-other-company").tax_mappings, {})
            self.assertEqual(fx.profiles.get("mf-other-company").account_mappings, {})


if __name__ == "__main__":
    unittest.main()

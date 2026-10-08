from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupError,
    MoneyForwardProfileSetupService,
)
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore


class MoneyForwardProfileSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile_store = ConversionProfileStore(self.root / "profiles")
        self.service = MoneyForwardProfileSetupService(self.profile_store)
        self.source = self.root / "mf.csv"
        self.context = self.root / "jdl.json"
        self._write_source(self.source)
        self._write_context(self.context)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_csv_extracts_accounts_and_exact_match_is_candidate_only(self) -> None:
        before = self.source.read_bytes()
        analysis = self.service.analyze(self.source, self.context)
        self.assertTrue(analysis.can_configure_accounts)
        self.assertEqual(len(analysis.account_items), 2)
        self.assertTrue(all(item.exact_candidate for item in analysis.account_items))
        self.assertEqual(self.profile_store.list(), ())
        self.assertEqual(self.source.read_bytes(), before)

    def test_invalid_non_moneyforward_csv_is_blocked(self) -> None:
        self.source.write_bytes(b"not,moneyforward\n")
        with self.assertRaisesRegex(MoneyForwardProfileSetupError, "確認できません"):
            self.service.analyze(self.source, self.context)

    def test_invalid_jdl_context_is_blocked(self) -> None:
        self.context.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.service.analyze(self.source, self.context)

    def test_optional_unsupported_field_blocks_without_silent_loss(self) -> None:
        self._write_source(self.source, debit_tax="課税仕入 10%")
        analysis = self.service.analyze(self.source, self.context)
        self.assertFalse(analysis.can_configure_accounts)
        self.assertEqual(analysis.unsupported_field_types, ("税区分",))
        with self.assertRaisesRegex(MoneyForwardProfileSetupError, "現在設定できない"):
            self.service.save_confirmed_profile(
                company_display_name="架空会社", analysis=analysis,
                selections={}, explicitly_confirmed=set(),
            )

    def test_unresolved_or_unconfirmed_account_cannot_save(self) -> None:
        analysis = self.service.analyze(self.source, self.context)
        selections = {
            item.source_value: item.exact_candidate
            for item in analysis.account_items
            if item.exact_candidate
        }
        with self.assertRaisesRegex(MoneyForwardProfileSetupError, "明示確認"):
            self.service.save_confirmed_profile(
                company_display_name="架空会社", analysis=analysis,
                selections=selections, explicitly_confirmed=set(),
            )
        self.assertEqual(self.profile_store.list(), ())

    def test_explicit_confirmation_saves_schema_v3_and_company_setting(self) -> None:
        analysis = self.service.analyze(self.source, self.context)
        selections = {
            item.source_value: item.exact_candidate
            for item in analysis.account_items
            if item.exact_candidate
        }
        profile = self.service.save_confirmed_profile(
            company_display_name="架空会社", analysis=analysis,
            selections=selections, explicitly_confirmed=set(selections),
        )
        self.assertEqual(profile.schema_version, "3")
        self.assertTrue(profile.account_mappings)
        self.assertTrue(
            all(item.status is MappingStatus.USER_CONFIRMED for item in profile.account_mappings.values())
        )
        company_store = CompanySettingStore(self.root / "companies", self.profile_store)
        setting = company_store.create(
            company_setting_id="company-mf", display_name="架空会社",
            conversion_profile_id=profile.profile_id, context_source=self.context,
        )
        self.assertTrue(company_store.resolve(setting.company_setting_id).available)

    @staticmethod
    def _write_source(path: Path, *, debit_tax: str = "") -> None:
        text = io.StringIO(newline="")
        writer = csv.writer(text, lineterminator="\n", quoting=csv.QUOTE_ALL)
        writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
        writer.writerow((
            "1", "2026/10/20", "現金", "", "", "", debit_tax, "", "700",
            "普通預金", "", "", "", "", "", "700", "架空摘要", "", "",
        ))
        path.write_bytes(text.getvalue().encode("cp932"))

    @staticmethod
    def _write_context(path: Path) -> None:
        accounts = (("現金", "1001"), ("普通預金", "1002"), ("雑収入", "1003"))
        payload = {
            "schema_version": "1", "product": "JDL IBEX 出納帳", "version": "35.5",
            "account_master": [
                {"mapping_value": name, "target_master_code": code, "target_name": name, "target_formal_name": name}
                for name, code in accounts
            ],
            "subaccounts": [], "departments": [], "tax_processing_mode": "EXEMPT",
            "department_processing_enabled": False, "standard_taxation_confirmed": False,
            "individual_credit_method_confirmed": False, "confirmation_state": "CONFIRMED",
            "provenance": "USER_CONFIRMED_RUNTIME_SNAPSHOT", "no_fuzzy_matching": True,
            "no_automatic_replacement": True,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

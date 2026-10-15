from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.application.company_mapping_update import CompanyMappingUpdateService
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.mapping import MappingKey, MappingStatus, MappingType, MappingValue
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import JdlAccountPdfDraftStore
from accounting_converter.profiles.known_formats import jdl_ibex_cashbook_official_journal_import_schema_definition, moneyforward_cloud_journal_export_observed_schema


class _Extractor:
    def extract_pages(self, _path):
        return (
            "科 目 一 覧\n1\n勘定科目 略名称 使用 課区 税区 入力 固変 比率 説明\n"
            "  1001- 架空科目A  借A ○\n"
            "  -0001 架空補助A  借\n"
            "  2001- 架空科目B  借B ○\n"
            "  -0002 架空補助B  借\n",
        )


class CompanyMappingUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        pdf = self.root / "master.pdf"; pdf.write_bytes(b"synthetic")
        self.draft = self.root / "master.json"
        JdlAccountPdfDraftStore(_Extractor()).import_pdf(pdf, self.draft)
        context_hash = hashlib.sha256(self.draft.read_bytes()).hexdigest()
        self.profiles = ConversionProfileStore(self.root / "profiles")
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.profiles.create(ConversionProfile(
            "profile-1", "架空設定", moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings={"入力科目A": MappingValue("入力科目A", "架空科目A", MappingStatus.USER_CONFIRMED, metadata={"target_code":"1001","target_printed_name":"架空科目A","setup_context_sha256":context_hash})},
            subaccount_context_mappings={MappingKey(MappingType.SUBACCOUNT,"入力補助A","入力科目A"): MappingValue("入力補助A","架空補助A",MappingStatus.USER_CONFIRMED,parent_account="入力科目A",metadata={"target_code":"0001","output_name":"架空補助A"})},
            created_at=now, updated_at=now,
        ))
        self.companies = CompanySettingStore(self.root / "companies", self.profiles)
        self.companies.create(company_setting_id="company-a",display_name="架空A",conversion_profile_id="profile-1",context_source=self.draft)
        self.service = CompanyMappingUpdateService(self.companies,self.profiles)

    def tearDown(self): self.temp.cleanup()

    def test_only_new_account_is_reviewed_and_confirmation_is_reused(self):
        source=self.root/"new.csv"; self._write(source, debit_account="入力科目A",debit_sub="入力補助A",credit_account="新規科目")
        review=self.service.review("company-a",source)
        self.assertEqual([(i.mapping_type,i.source_value) for i in review.items],[("ACCOUNT","新規科目")])
        with self.assertRaises(ValueError): self.service.apply(review,{},set())
        item=review.items[0]
        self.service.apply(review,{item.key:"架空科目B"},{item.key})
        self.assertFalse(self.service.review("company-a",source).items)

        editable = self.service.review(
            "company-a", source, include_confirmed=True
        )
        self.assertEqual(len(editable.items), 3)
        self.assertTrue(
            all(item.exact_candidate for item in editable.items)
        )

    def test_empty_company_profile_reviews_first_csv_then_reuses_confirmations(self):
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.profiles.create(ConversionProfile(
            "profile-empty", "架空初期設定",
            moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            created_at=now, updated_at=now,
        ))
        self.companies.create(
            company_setting_id="company-empty", display_name="架空初期会社",
            conversion_profile_id="profile-empty", context_source=self.draft,
        )
        source = self.root / "first.csv"
        self._write(
            source, debit_account="入力科目A", debit_sub="",
            credit_account="入力科目A",
        )

        review = self.service.review("company-empty", source)
        self.assertEqual(len(review.items), 1)
        item = review.items[0]
        self.service.apply(review, {item.key: "架空科目A"}, {item.key})

        self.assertFalse(self.service.review("company-empty", source).items)
        setting = self.companies.get("company-empty")
        updated = self.profiles.get(setting.conversion_profile_id)
        self.assertEqual(
            updated.tax_mappings["対象外"].status,
            MappingStatus.UNRESOLVED,
        )

    def test_subaccount_candidates_are_limited_to_confirmed_parent(self):
        source=self.root/"sub.csv"; self._write(source,debit_account="入力科目A",debit_sub="新規補助",credit_account="入力科目A")
        review=self.service.review("company-a",source)
        item=next(i for i in review.items if i.mapping_type=="SUBACCOUNT")
        self.assertEqual(item.available_targets,("架空補助A",))
        self.assertNotIn("架空補助B",item.available_targets)
        with self.assertRaises(ValueError):
            self.service.apply(review, {item.key: "架空補助B"}, {item.key})
        self.service.apply(review, {item.key: "架空補助A"}, {item.key})
        self.assertFalse(self.service.review("company-a", source).items)

    def test_tax_only_requirement_is_persisted_unresolved_then_reused(self):
        source = self.root / "tax-only.csv"
        self._write(
            source,
            debit_account="入力科目A",
            debit_sub="入力補助A",
            credit_account="入力科目A",
        )

        review = self.service.review("company-a", source)

        self.assertFalse(review.items)
        self.assertEqual(review.tax_categories, ("対象外",))
        self.service.ensure_tax_requirements(review)
        setting = self.companies.get("company-a")
        profile = self.profiles.get(setting.conversion_profile_id)
        self.assertEqual(
            profile.tax_mappings["対象外"].status,
            MappingStatus.UNRESOLVED,
        )
        self.assertEqual(
            self.service.review("company-a", source).tax_categories,
            ("対象外",),
        )
        self.profiles.update(
            replace(
                profile,
                tax_mappings={
                    "対象外": MappingValue(
                        "対象外", "", MappingStatus.USER_CONFIRMED
                    )
                },
            )
        )
        self.assertFalse(
            self.service.review("company-a", source).tax_categories
        )

    def test_saved_mappings_can_be_reviewed_without_source_csv(self):
        review = self.service.review_saved("company-a")

        self.assertIsNone(review.source_path)
        self.assertEqual(
            [(item.mapping_type, item.exact_candidate) for item in review.items],
            [("ACCOUNT", "架空科目A"), ("SUBACCOUNT", "架空補助A")],
        )
        selections = {item.key: item.exact_candidate for item in review.items}
        self.service.apply(review, selections, set(selections))
        self.assertEqual(len(self.service.review_saved("company-a").items), 2)

    def test_confirmed_runtime_context_uses_in_flow_review_and_save(self):
        context = self.root / "confirmed-context.json"
        payload = {
            "schema_version": "1",
            "product": "JDL IBEX 出納帳",
            "version": "35.5",
            "account_master": [
                {
                    "mapping_value": "科目甲",
                    "target_master_code": "1001",
                    "target_name": "科目甲",
                    "target_formal_name": "科目甲",
                },
                {
                    "mapping_value": "科目乙",
                    "target_master_code": "2001",
                    "target_name": "科目乙",
                    "target_formal_name": "科目乙",
                },
            ],
            "subaccounts": [],
            "departments": [],
            "tax_processing_mode": "EXEMPT",
            "department_processing_enabled": False,
            "standard_taxation_confirmed": False,
            "individual_credit_method_confirmed": False,
            "confirmation_state": "CONFIRMED",
            "provenance": "USER_CONFIRMED_RUNTIME_SNAPSHOT",
            "no_fuzzy_matching": True,
            "no_automatic_replacement": True,
        }
        context.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        context_hash = hashlib.sha256(context.read_bytes()).hexdigest()
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.profiles.create(ConversionProfile(
            "profile-runtime", "架空実行設定",
            moneyforward_cloud_journal_export_observed_schema().identity,
            jdl_ibex_cashbook_official_journal_import_schema_definition().identity,
            account_mappings={
                "入力科目A": MappingValue(
                    "入力科目A", "科目甲", MappingStatus.USER_CONFIRMED,
                    metadata={
                        "target_code": "1001",
                        "target_formal_name": "科目甲",
                        "setup_context_sha256": context_hash,
                    },
                )
            },
            created_at=now, updated_at=now,
        ))
        self.companies.create(
            company_setting_id="company-runtime",
            display_name="架空実行会社",
            conversion_profile_id="profile-runtime",
            context_source=context,
        )
        source = self.root / "runtime.csv"
        self._write(
            source,
            debit_account="入力科目A",
            debit_sub="",
            credit_account="新規科目",
        )

        review = self.service.review("company-runtime", source)
        item = next(item for item in review.items if item.mapping_type == "ACCOUNT")
        self.assertEqual(item.available_targets, ("科目甲", "科目乙"))
        self.service.apply(review, {item.key: "科目乙"}, {item.key})

        self.assertFalse(self.service.review("company-runtime", source).items)
        setting = self.companies.get("company-runtime")
        saved = self.profiles.get(setting.conversion_profile_id)
        self.assertEqual(
            saved.account_mappings["新規科目"].metadata["target_code"],
            "2001",
        )

    def test_conflicting_subaccount_identity_is_not_selectable(self):
        import json

        context = self.companies.context_path(self.companies.get("company-a"))
        payload = json.loads(context.read_text(encoding="utf-8"))
        payload["subaccounts"].append(
            {
                "parent_account_code": "1001",
                "parent_account_name": "架空科目A",
                "code": "0002",
                "name": "架空補助A",
                "evidence_scope": "PRINTED_EXPLICIT_PARENT",
            }
        )
        payload["conflict_categories"] = ["SUBACCOUNT_NAME_CONFLICT"]
        context.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        source=self.root/"conflict.csv"; self._write(source,debit_account="入力科目A",debit_sub="新規補助",credit_account="入力科目A")
        review=self.service.review("company-a",source)
        item=next(i for i in review.items if i.mapping_type=="SUBACCOUNT")
        self.assertNotIn("架空補助A", item.available_targets)

    def _write(self,path,*,debit_account,debit_sub,credit_account):
        row=["1","2026/10/14",debit_account,debit_sub,"","","対象外","","100",credit_account,"","","","","対象外","100","架空摘要","",""]
        with path.open("w",encoding="cp932",newline="") as f:
            w=csv.writer(f,lineterminator="\n",quoting=csv.QUOTE_ALL); w.writerow(MONEYFORWARD_OBSERVED_HEADER); w.writerow(row)

if __name__=="__main__": unittest.main()

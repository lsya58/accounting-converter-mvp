from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
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

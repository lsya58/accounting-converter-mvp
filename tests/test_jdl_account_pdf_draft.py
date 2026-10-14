from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from accounting_converter.adapters.input.moneyforward import MONEYFORWARD_OBSERVED_HEADER
from accounting_converter.application.company_settings import CompanySettingStatus
from accounting_converter.application.moneyforward_profile_setup import (
    MoneyForwardProfileSetupError,
    MoneyForwardProfileSetupService,
)
from accounting_converter.domain.mapping import MappingStatus
from accounting_converter.infrastructure.company_setting_store import CompanySettingStore
from accounting_converter.infrastructure.conversion_profile_store import ConversionProfileStore
from accounting_converter.infrastructure.jdl_account_pdf_draft import (
    JdlAccountPdfDraftError,
    JdlAccountPdfDraftStore,
    PypdfTextExtractor,
)
from accounting_converter.application.jdl_account_list_pdf import (
    JdlAccountListPdfTextParser,
    JdlAccountListTextPage,
)


class _SyntheticPdfExtractor:
    def __init__(self, pages: tuple[str, ...]) -> None:
        self.pages = pages

    def extract_pages(self, path: Path) -> tuple[str, ...]:
        return self.pages


class JdlAccountPdfDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pdf = self.root / "synthetic.pdf"
        self.pdf.write_bytes(b"synthetic-pdf-placeholder")
        self.pages = self._pages(125)
        self.store = JdlAccountPdfDraftStore(_SyntheticPdfExtractor(self.pages))
        self.draft_path = self.root / "draft.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_imports_125_accounts_as_observed_draft_without_formal_promotion(self) -> None:
        draft = self.store.import_pdf(self.pdf, self.draft_path)
        payload = json.loads(self.draft_path.read_text(encoding="utf-8"))

        self.assertEqual(draft.classification.value, "OBSERVED_PRINTED_MASTER")
        self.assertEqual(len(draft.observation.printed_accounts), 125)
        self.assertEqual(draft.source_sha256, hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertFalse(payload["formal_conversion_allowed"])
        self.assertEqual(payload["document_type"], "JDL_ACCOUNT_PDF_CONTEXT_DRAFT")
        self.assertEqual(self.store.load(self.draft_path), draft)

    def test_pypdf_compact_layout_is_normalized_without_guessing_blank_subaccount(self) -> None:
        pages = []
        for page_number in range(1, 6):
            compact = (
                f"科 目 一 覧 {page_number}\n"
                "令和 8年12月31日決算\n"
                "勘 定 科 目 略 名 称 使用 課 区 税 区 入力 固変 比 率 説 明\n"
                f"{1100 + page_number} 架空科目{page_number} 借 架空 略称 ○ 説明\n"
                "架空予備 借 架空 予備 ×\n"
            )
            if page_number == 2:
                compact += "-0001 貸\n"
            pages.append(
                JdlAccountListTextPage(
                    page_number,
                    PypdfTextExtractor._normalize_observed_page(
                        compact, page_number
                    ),
                )
            )

        result = JdlAccountListPdfTextParser().parse_pages(
            pages,
            source_sha256="a" * 64,
            acquisition_method="synthetic pypdf layout",
            human_observed=True,
        )

        self.assertEqual(len(result.printed_accounts), 5)
        self.assertFalse(result.subaccounts)
        self.assertEqual(result.completeness.value, "OBSERVED_PRINTED_MASTER")

    def test_import_never_overwrites_and_conflicts_are_blocked(self) -> None:
        self.store.import_pdf(self.pdf, self.draft_path)
        before = self.draft_path.read_bytes()
        with self.assertRaises(JdlAccountPdfDraftError):
            self.store.import_pdf(self.pdf, self.draft_path)
        self.assertEqual(self.draft_path.read_bytes(), before)

        conflict_pages = list(self.pages)
        conflict_pages[1] += "         1001  別の架空科目                    別略称  ○ 仕 入\n"
        conflict_store = JdlAccountPdfDraftStore(
            _SyntheticPdfExtractor(tuple(conflict_pages))
        )
        with self.assertRaises(JdlAccountPdfDraftError):
            conflict_store.import_pdf(self.pdf, self.root / "conflict.json")

        duplicate_name_pages = list(self.pages)
        duplicate_name_pages[1] += (
            "         1999  架空科目001                    借別略称  ○ 仕 入\n"
        )
        duplicate_name_store = JdlAccountPdfDraftStore(
            _SyntheticPdfExtractor(tuple(duplicate_name_pages))
        )
        with self.assertRaises(JdlAccountPdfDraftError):
            duplicate_name_store.import_pdf(
                self.pdf, self.root / "duplicate-name.json"
            )

    def test_subaccount_conflict_is_preserved_without_blocking_account_review(self) -> None:
        pages = list(self.pages)
        pages[0] = (
            "科        目        一         覧\n"
            "頁\n1\n令和 8年12月31日決算\n"
            "勘 定 科 目  略名称 使用 課区 税区 入力 固変 比率 説明\n"
            "         1311- 架空親科目                    借架空親科目 ○\n"
            "             -0001 架空補助科目              借\n"
            "             -0002 架空補助科目              借\n"
            "               架空予備科目                 借架空予備 ×\n"
        )
        store = JdlAccountPdfDraftStore(_SyntheticPdfExtractor(tuple(pages)))
        path = self.root / "subaccount-conflict.json"

        imported = store.import_pdf(self.pdf, path)
        loaded = store.load(path)

        self.assertEqual(
            tuple(item.category for item in imported.observation.conflicts),
            ("SUBACCOUNT_NAME_CONFLICT",),
        )
        self.assertEqual(loaded.observation.conflicts, imported.observation.conflicts)
        self.assertEqual(len(loaded.observation.printed_accounts), 101)

    def test_28_requirements_are_reviewable_and_saved_only_after_confirmation(self) -> None:
        self.store.import_pdf(self.pdf, self.draft_path)
        source = self.root / "mf.csv"
        source_accounts = tuple(
            [f"架空科目{number:03d}" for number in range(1, 21)]
            + [f"未登録科目{number:03d}" for number in range(21, 29)]
        )
        self._write_moneyforward(source, source_accounts)
        profiles = ConversionProfileStore(self.root / "profiles")
        service = MoneyForwardProfileSetupService(profiles)

        analysis = service.analyze(source, self.draft_path)

        self.assertTrue(analysis.context_is_draft)
        self.assertEqual(len(analysis.account_items), 28)
        self.assertEqual(sum(item.exact_candidate is not None for item in analysis.account_items), 20)
        self.assertEqual(sum(item.exact_candidate is None for item in analysis.account_items), 8)
        self.assertIn("JDL設定の確認", analysis.unsupported_field_types)
        selections = {
            item.source_value: item.exact_candidate or "架空科目001"
            for item in analysis.account_items
        }
        with self.assertRaises(MoneyForwardProfileSetupError):
            service.save_confirmed_profile(
                company_display_name="架空会社",
                analysis=analysis,
                selections=selections,
                explicitly_confirmed=set(selections) - {source_accounts[-1]},
            )

        profile = service.save_confirmed_profile(
            company_display_name="架空会社",
            analysis=analysis,
            selections=selections,
            explicitly_confirmed=set(selections),
        )
        self.assertEqual(len(profile.account_mappings), 28)
        self.assertTrue(
            all(item.status is MappingStatus.USER_CONFIRMED for item in profile.account_mappings.values())
        )
        self.assertTrue(
            all("target_printed_name" in item.metadata for item in profile.account_mappings.values())
        )
        self.assertTrue(
            all("target_formal_name" not in item.metadata for item in profile.account_mappings.values())
        )

        companies = CompanySettingStore(self.root / "companies", profiles)
        setting = companies.create(
            company_setting_id="draft-company",
            display_name="架空会社",
            conversion_profile_id=profile.profile_id,
            context_source=self.draft_path,
        )
        resolved = companies.resolve(setting.company_setting_id)
        self.assertEqual(resolved.status, CompanySettingStatus.REQUIRES_CONFIRMATION)
        self.assertFalse(resolved.available)
        self.assertIsNone(resolved.context)
        self.assertEqual(resolved.reason_codes, ("JDL_CONTEXT_DRAFT_UNCONFIRMED",))

    def test_changed_draft_is_stale_and_unknown_target_is_blocked(self) -> None:
        self.store.import_pdf(self.pdf, self.draft_path)
        source = self.root / "mf.csv"
        self._write_moneyforward(source, ("架空科目001", "架空科目002"))
        profiles = ConversionProfileStore(self.root / "profiles")
        service = MoneyForwardProfileSetupService(profiles)
        analysis = service.analyze(source, self.draft_path)
        with self.assertRaises(MoneyForwardProfileSetupError):
            service.save_confirmed_profile(
                company_display_name="架空会社",
                analysis=analysis,
                selections={"架空科目001": "存在しない科目", "架空科目002": "架空科目002"},
                explicitly_confirmed={"架空科目001", "架空科目002"},
            )
        self.draft_path.write_text(
            self.draft_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        with self.assertRaisesRegex(MoneyForwardProfileSetupError, "変更"):
            service.save_confirmed_profile(
                company_display_name="架空会社",
                analysis=analysis,
                selections={"架空科目001": "架空科目001", "架空科目002": "架空科目002"},
                explicitly_confirmed={"架空科目001", "架空科目002"},
            )

    def test_company_specific_drafts_do_not_share_account_candidates(self) -> None:
        first_path = self.root / "first-draft.json"
        second_path = self.root / "second-draft.json"
        self.store.import_pdf(self.pdf, first_path)

        second_pages = tuple(
            page.replace("架空科目001", "別会社専用科目") for page in self.pages
        )
        second_pdf = self.root / "second-synthetic.pdf"
        second_pdf.write_bytes(b"second-synthetic-pdf-placeholder")
        JdlAccountPdfDraftStore(_SyntheticPdfExtractor(second_pages)).import_pdf(
            second_pdf, second_path
        )

        source = self.root / "mf-isolation.csv"
        self._write_moneyforward(source, ("架空科目001", "架空科目002"))
        service = MoneyForwardProfileSetupService(
            ConversionProfileStore(self.root / "isolation-profiles")
        )

        first = service.analyze(source, first_path)
        second = service.analyze(source, second_path)

        self.assertEqual(
            sum(item.exact_candidate is not None for item in first.account_items), 2
        )
        self.assertEqual(
            sum(item.exact_candidate is not None for item in second.account_items), 1
        )
        self.assertNotEqual(first.context_sha256, second.context_sha256)

    @staticmethod
    def _pages(account_count: int) -> tuple[str, ...]:
        pages: list[str] = []
        per_page = account_count // 5
        for page_number in range(1, 6):
            start = (page_number - 1) * per_page + 1
            rows = "".join(
                f"         {1000 + number:04d}  架空科目{number:03d}                    "
                f"借架空略称{number:03d}  ○ 仕 入\n"
                for number in range(start, start + per_page)
            )
            rows += "               架空予備科目                 借架空予備 ×\n"
            pages.append(
                "科        目        一         覧\n"
                "頁\n"
                f"{page_number}\n"
                "令和 8年12月31日決算\n"
                "勘 定 科 目  略名称 使用 課区 税区 入力 固変 比率 説明\n"
                + rows
            )
        return tuple(pages)

    @staticmethod
    def _write_moneyforward(path: Path, accounts: tuple[str, ...]) -> None:
        rows = []
        for index in range(0, len(accounts), 2):
            rows.append(
                [
                    str(index // 2 + 1), "2026/12/01", accounts[index], "", "", "", "", "", "100",
                    accounts[index + 1], "", "", "", "", "", "100", "架空摘要", "", "",
                ]
            )
        with path.open("w", encoding="cp932", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_ALL)
            writer.writerow(MONEYFORWARD_OBSERVED_HEADER)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from accounting_converter.application.jdl_account_list_pdf import (
    JdlAccountListPdfParseError,
    JdlAccountListPdfTextParser,
    JdlAccountListTextPage,
)
from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservation,
    JdlMasterObservationService,
    JdlMasterSourceEvidence,
)
from accounting_converter.adapters.output.jdl import JdlAccountIdentity
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class JdlAccountListPdfTextParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = JdlAccountListPdfTextParser()

    def test_parses_five_page_structure_without_promoting_uncoded_rows(self) -> None:
        result = self._parse(
            (
                self._page(1, "1111", "架空現金", "借架空現金", "○"),
                self._page(2, "2111", "架空建物", "借架空建物", "○"),
                self._page(3, "3111", "架空未払", "貸架空未払", "○"),
                self._page(4, "4111", "架空収益", "貸架空収益", "○"),
                self._page(5, "8111", "架空費用", "借架空費用", "×"),
            )
        )

        self.assertEqual(
            result.completeness, JdlMasterCompleteness.OBSERVED_PRINTED_MASTER
        )
        self.assertEqual(len(result.printed_accounts), 5)
        self.assertEqual(sum(item.enabled for item in result.printed_accounts), 4)
        self.assertEqual(result.excluded_uncoded_printed_row_count, 5)
        self.assertFalse(result.accounts)
        self.assertFalse(result.subaccounts)
        self.assertEqual(result.sources[0].page_count, 5)
        self.assertTrue(result.sources[0].human_observed)
        self.assertNotIn("架空現金", str(result.privacy_safe_summary()))

    def test_extracts_code_name_abbreviation_and_balance_side(self) -> None:
        result = self._parse(self._pages())
        first = result.printed_accounts[0]

        self.assertEqual(first.code, "1111")
        self.assertEqual(first.name, "架空現金")
        self.assertEqual(first.abbreviation, "架空現金")
        self.assertEqual(first.normal_balance, "DEBIT")
        self.assertTrue(first.enabled)
        self.assertTrue(first.has_observed_setting_values)

    def test_group_header_and_uncoded_row_are_not_guessed_as_accounts(self) -> None:
        result = self._parse(self._pages())
        names = {item.name for item in result.printed_accounts}

        self.assertNotIn("架空流動資産", names)
        self.assertNotIn("架空予備科目", names)
        self.assertEqual(result.excluded_uncoded_printed_row_count, 5)

    def test_explicit_parent_marker_extracts_subaccount_and_preserves_code(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1311- 架空親科目                    借架空親科目 ○\n"
            + "             -0001 架空補助科目              借\n"
            + "               架空予備科目                 借架空予備 ×\n",
        )

        result = self._parse(tuple(pages))
        subaccount = result.subaccounts[0]
        draft = JdlMasterObservationService().build_unconfirmed_context_draft(result)

        self.assertEqual(len(result.subaccounts), 1)
        self.assertEqual(subaccount.parent_account_code, "1311")
        self.assertEqual(subaccount.parent_account_name, "架空親科目")
        self.assertEqual(subaccount.code, "0001")
        self.assertEqual(subaccount.name, "架空補助科目")
        self.assertEqual(draft.context.subaccounts[0].target_master_code, "0001")
        self.assertFalse(
            draft.context.subaccounts[0].output_representation_confirmed
        )
        self.assertFalse(draft.production_usable)

    def test_indented_code_less_row_is_not_subaccount(self) -> None:
        result = self._parse(self._pages())

        self.assertFalse(result.subaccounts)
        self.assertEqual(result.excluded_uncoded_printed_row_count, 5)

    def test_subaccount_without_explicit_parent_or_with_wrong_balance_is_blocked(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "             -0001 架空補助科目              借\n",
        )
        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse(tuple(pages))

        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1311- 架空親科目                    借架空親科目 ○\n"
            + "             -0001 架空補助科目              貸\n",
        )
        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse(tuple(pages))

    def test_credit_parent_uses_the_same_explicit_subaccount_structure(self) -> None:
        pages = list(self._pages())
        pages[2] = JdlAccountListTextPage(
            3,
            self._page_header(3)
            + "         3991- 架空貸方親科目                貸架空貸方親 ○\n"
            + "             -0001 架空貸方補助              貸\n",
        )

        result = self._parse(tuple(pages))
        child = result.subaccounts[0]
        parent = next(
            item for item in result.printed_accounts if item.code == "3991"
        )

        self.assertEqual(parent.normal_balance, "CREDIT")
        self.assertEqual(child.parent_account_code, parent.code)
        self.assertEqual(child.code, "0001")
        self.assertFalse(result.conflicts)

    def test_multiple_subaccounts_and_parent_transition_are_parent_scoped(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1211- 架空親科目A                   借架空親A ○\n"
            + "             -0001 架空補助A                借\n"
            + "         1311- 架空親科目B                   借架空親B ○\n"
            + "             -0001 架空補助B                借\n"
            + "             -0002 架空補助C                借\n",
        )

        result = self._parse(tuple(pages))
        by_parent: dict[str, list[str]] = {}
        for item in result.subaccounts:
            by_parent.setdefault(item.parent_account_code, []).append(item.code)

        self.assertEqual(len(result.subaccounts), 3)
        self.assertEqual(sorted(by_parent["1211"]), ["0001"])
        self.assertEqual(sorted(by_parent["1311"]), ["0001", "0002"])
        self.assertFalse(result.conflicts)

    def test_duplicate_under_same_parent_is_conflict_but_same_code_across_parents_is_not(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1211- 架空親科目A                   借架空親A ○\n"
            + "             -0001 架空補助A                借\n"
            + "         1311- 架空親科目B                   借架空親B ○\n"
            + "             -0001 架空補助B                借\n",
        )
        across_parents = self._parse(tuple(pages))
        self.assertFalse(across_parents.conflicts)

        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1211- 架空親科目A                   借架空親A ○\n"
            + "             -0001 架空補助A                借\n"
            + "             -0001 架空補助A                借\n",
        )
        duplicate = self._parse(tuple(pages))
        self.assertIn(
            "SUBACCOUNT_DUPLICATE",
            {item.category for item in duplicate.conflicts},
        )
        self.assertEqual(duplicate.completeness, JdlMasterCompleteness.PARTIAL_MASTER)

    def test_subaccount_cannot_continue_across_page_boundary(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1211- 架空親科目A                   借架空親A ○\n",
        )
        pages[1] = JdlAccountListTextPage(
            2,
            self._page_header(2)
            + "             -0001 架空補助A                借\n",
        )
        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse(tuple(pages))

    def test_malformed_subaccount_delimiter_is_blocked(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1,
            self._page_header(1)
            + "         1211- 架空親科目A                   借架空親A ○\n"
            + "             -001 架空補助A                 借\n",
        )
        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse(tuple(pages))

    def test_malformed_symbol_row_and_missing_page_are_blocked(self) -> None:
        pages = list(self._pages())
        pages[0] = JdlAccountListTextPage(
            1, pages[0].text + "\n  1111 malformed ○"
        )
        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse(tuple(pages))

        with self.assertRaises(JdlAccountListPdfParseError):
            self._parse((self._page(2, "1111", "架空現金", "借架空現金", "○"),))

    def test_short_code_less_marked_row_is_excluded_across_seven_pages(self) -> None:
        pages = tuple(
            self._page(
                number,
                str(1100 + number),
                f"架空科目{number}",
                f"借架空{number}",
                "○",
            )
            for number in range(1, 8)
        )
        last = pages[-1]
        pages = pages[:-1] + (
            JdlAccountListTextPage(
                last.page_number,
                last.text + "\n架空短縮行 × 借方",
            ),
        )

        result = self._parse(pages)

        self.assertEqual(len(result.printed_accounts), 7)
        self.assertEqual(result.completeness, JdlMasterCompleteness.OBSERVED_PRINTED_MASTER)
        self.assertEqual(result.excluded_uncoded_printed_row_count, 8)

    def test_duplicate_code_conflict_downgrades_completeness(self) -> None:
        pages = list(self._pages())
        pages[1] = self._page(2, "1111", "別の架空科目", "借別の略称", "○")
        result = self._parse(tuple(pages))

        self.assertEqual(result.completeness, JdlMasterCompleteness.PARTIAL_MASTER)
        self.assertIn(
            "PRINTED_ACCOUNT_CODE_CONFLICT",
            {item.category for item in result.conflicts},
        )

    def test_exact_coverage_and_unconfirmed_context_draft(self) -> None:
        result = self._parse(self._pages())
        service = JdlMasterObservationService()
        coverage = service.coverage(
            ("架空現金", "架空建物", "存在しない架空科目"), result
        )
        draft = service.build_unconfirmed_context_draft(result)

        self.assertEqual(coverage.exact_single_count, 2)
        self.assertEqual(coverage.missing_count, 1)
        self.assertFalse(draft.production_usable)
        self.assertFalse(draft.context.account_master)
        self.assertIn("架空現金", draft.context.accounts)

    def test_runtime_comparison_reports_conflicts_without_promoting_runtime_only(self) -> None:
        printed = self._parse(self._pages())
        runtime = JdlMasterObservation(
            accounts=(
                JdlAccountIdentity("架空現金", "1111", "架空現金", "架空現金"),
                JdlAccountIdentity("異なる名称", "2111", "異なる名称", "異なる名称"),
                JdlAccountIdentity("実行時のみ", "9999", "実行時のみ", "実行時のみ"),
            ),
            subaccounts=(),
            departments=(),
            sources=(JdlMasterSourceEvidence("b" * 64, "SYNTHETIC_RUNTIME", 2),),
        )

        comparison = JdlMasterObservationService.compare_printed_master_with_runtime(
            printed, runtime
        )

        self.assertEqual(comparison.corroborated_count, 1)
        self.assertEqual(comparison.conflict_count, 1)
        self.assertEqual(comparison.runtime_only_count, 1)
        self.assertNotIn("実行時のみ", str(comparison.privacy_safe_summary()))

    def test_production_registry_remains_unchanged(self) -> None:
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.assertEqual(
            registry.get_exact_input(source).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )
        self.assertFalse(registry.has_conversion_pair(source, target))

    def _parse(self, pages: tuple[JdlAccountListTextPage, ...]):
        return self.parser.parse_pages(
            pages,
            source_sha256="a" * 64,
            acquisition_method="JDL科目印刷からPDF出力（synthetic test）",
            human_observed=True,
        )

    def _pages(self) -> tuple[JdlAccountListTextPage, ...]:
        return (
            self._page(1, "1111", "架空現金", "借架空現金", "○"),
            self._page(2, "2111", "架空建物", "借架空建物", "○"),
            self._page(3, "3111", "架空未払", "貸架空未払", "○"),
            self._page(4, "4111", "架空収益", "貸架空収益", "○"),
            self._page(5, "8111", "架空費用", "借架空費用", "○"),
        )

    @staticmethod
    def _page(
        number: int, code: str, name: str, abbreviation: str, enabled: str
    ) -> JdlAccountListTextPage:
        return JdlAccountListTextPage(
            page_number=number,
            text=(
                JdlAccountListPdfTextParserTests._page_header(number)
                + f"         {code}  {name}                    {abbreviation}  "
                f"{enabled} 仕 入\n"
                "               架空予備科目                 借架空予備 ×\n"
                "         架空流動資産                       借\n"
            ),
        )

    @staticmethod
    def _page_header(number: int) -> str:
        return (
            "科        目        一         覧\n"
            "頁\n"
            f"{number}\n"
            "令和 8年12月31日決算\n"
            "勘 定 科 目  略名称 使用 課区 税区 入力 固変 比率 説明\n"
        )


if __name__ == "__main__":
    unittest.main()

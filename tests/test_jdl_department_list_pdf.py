from __future__ import annotations

import unittest

from accounting_converter.application.jdl_department_list_pdf import (
    JdlDepartmentListPdfParseError,
    JdlDepartmentListPdfTextParser,
    JdlDepartmentListTextPage,
)
from accounting_converter.application.jdl_master_observation import (
    JdlMasterCompleteness,
    JdlMasterObservationService,
)
from accounting_converter.infrastructure.adapter_registry import (
    AdapterAvailabilityStatus,
    production_adapter_registry,
)
from accounting_converter.profiles.known_formats import (
    jdl_ibex_cashbook_official_journal_import_schema_definition,
    moneyforward_cloud_journal_export_observed_schema,
)


class JdlDepartmentListPdfTextParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = JdlDepartmentListPdfTextParser()

    def test_extracts_department_and_optional_printed_fields(self) -> None:
        result = self._parse(
            self._page(
                "架空集計  1  架空部門  架空略称  架空配賦元  25.00  1.50"
            )
        )
        item = result.printed_departments[0]

        self.assertEqual(result.completeness, JdlMasterCompleteness.OBSERVED_PRINTED_MASTER)
        self.assertEqual(item.code, "1")
        self.assertEqual(item.name, "架空部門")
        self.assertEqual(item.abbreviation, "架空略称")
        self.assertEqual(item.aggregation_department, "架空集計")
        self.assertEqual(item.allocation_source, "架空配賦元")
        self.assertEqual(item.allocation_basis, "25.00")
        self.assertEqual(item.estimated_profit_rate, "1.50")
        self.assertNotIn("架空部門", str(result.privacy_safe_summary()))
        self.assertEqual(result.sources[0].page_count, 1)
        self.assertEqual(result.sources[0].sha256, "a" * 64)
        self.assertEqual(
            result.sources[0].source_kind,
            "JDL_IBEX_DEPARTMENT_LIST_PDF_TEXT_LAYER_OBSERVED",
        )
        self.assertTrue(result.sources[0].human_observed)

    def test_blank_optional_fields_are_preserved_without_guessing(self) -> None:
        result = self._parse(self._page("1  架空部門  架空略称  0.00  0.00"))
        item = result.printed_departments[0]

        self.assertEqual(item.code, "1")
        self.assertEqual(item.aggregation_department, "")
        self.assertEqual(item.allocation_source, "")
        self.assertEqual(item.allocation_basis, "0.00")
        self.assertEqual(item.estimated_profit_rate, "0.00")

    def test_two_departments_are_parsed_as_two_consecutive_rows(self) -> None:
        result = self._parse(
            self._page(
                "1  架空部門A  架空A  0.00  0.00\n"
                "2  架空部門B  架空B  0.00  0.00"
            )
        )
        draft = JdlMasterObservationService().build_unconfirmed_context_draft(result)

        self.assertEqual([item.code for item in result.printed_departments], ["1", "2"])
        self.assertEqual(len(draft.context.departments), 2)
        self.assertFalse(result.conflicts)
        self.assertFalse(draft.production_usable)

    def test_malformed_row_is_blocked(self) -> None:
        with self.assertRaises(JdlDepartmentListPdfParseError):
            self._parse(self._page("1  架空部門"))

    def test_duplicate_code_and_name_conflicts_are_parent_free(self) -> None:
        code_conflict = self._parse(
            self._page(
                "1  架空部門A  架空A  0.00  0.00\n"
                "                                   1  架空部門B  架空B  0.00  0.00"
            )
        )
        self.assertIn(
            "DEPARTMENT_CODE_CONFLICT",
            {item.category for item in code_conflict.conflicts},
        )
        self.assertEqual(code_conflict.completeness, JdlMasterCompleteness.PARTIAL_MASTER)

        name_conflict = self._parse(
            self._page(
                "1  架空部門  架空A  0.00  0.00\n"
                "                                   2  架空部門  架空B  0.00  0.00"
            )
        )
        self.assertIn(
            "DEPARTMENT_NAME_CONFLICT",
            {item.category for item in name_conflict.conflicts},
        )

    def test_context_draft_retains_values_but_is_not_production_usable(self) -> None:
        observed = self._parse(self._page("1  架空部門  架空略称  0.00  0.00"))
        draft = JdlMasterObservationService().build_unconfirmed_context_draft(observed)
        item = draft.context.departments[0]

        self.assertEqual(item.mapping_value, "架空部門")
        self.assertEqual(item.target_master_code, "1")
        self.assertEqual(item.output_code, "")
        self.assertEqual(item.output_name, "架空略称")
        self.assertFalse(draft.production_usable)
        self.assertTrue(draft.validation_results)

    def test_wrong_header_and_page_number_are_blocked(self) -> None:
        page = self._page("1  架空部門  架空略称  0.00  0.00")
        with self.assertRaises(JdlDepartmentListPdfParseError):
            self._parse(JdlDepartmentListTextPage(1, page.text.replace("配賦基準", "別項目")))
        with self.assertRaises(JdlDepartmentListPdfParseError):
            self._parse(JdlDepartmentListTextPage(1, page.text.replace("1頁", "2頁")))

    def test_production_registry_remains_unchanged(self) -> None:
        registry = production_adapter_registry()
        source = moneyforward_cloud_journal_export_observed_schema().identity
        target = jdl_ibex_cashbook_official_journal_import_schema_definition().identity
        self.assertEqual(
            registry.get_exact_input(source).status,
            AdapterAvailabilityStatus.UNAVAILABLE,
        )
        self.assertFalse(registry.has_conversion_pair(source, target))

    def _parse(self, page: JdlDepartmentListTextPage):
        return self.parser.parse_pages(
            (page,),
            source_sha256="a" * 64,
            acquisition_method="JDL部門登録から印刷（synthetic test）",
            human_observed=True,
        )

    @staticmethod
    def _page(rows: str) -> JdlDepartmentListTextPage:
        indented_rows = "\n".join("                                   " + row for row in rows.splitlines())
        return JdlDepartmentListTextPage(
            1,
            "\n".join(
                (
                    "部 門 情 報 一 覧",
                    "1頁",
                    "部 門 共通費",
                    "集計部門",
                    "名称 コード 名称 略名称 配賦元 配賦基準 利益率",
                    indented_rows,
                    "架空事務所",
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()

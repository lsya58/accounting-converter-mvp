from pathlib import Path
import unittest

from accounting_converter.application.company_mapping_update import (
    CompanyMappingUpdateReview,
)
from accounting_converter.application.company_review_state import (
    build_company_review_work_queue,
)
from accounting_converter.application.moneyforward_profile_setup import (
    TaxMappingSetupItem,
    TaxMappingSetupReview,
)


class CompanyReviewWorkQueueTests(unittest.TestCase):
    def test_distinguishes_settings_journals_and_evidence_rows(self) -> None:
        review = CompanyMappingUpdateReview(
            company_setting_id="company-test",
            source_path=Path("test.csv"),
            context_path=Path("context.json"),
            items=(),
            logical_journal_count=482,
            optional_field_blocker_count=73,
            optional_field_counts=(("trade_partner", 47), ("description", 11), ("description_character", 15)),
            optional_field_row_counts=(("trade_partner", 47), ("description", 127), ("description_character", 15)),
            other_optional_journal_count=26,
            other_optional_row_count=142,
            observed_tax_categories=("tax-a", "tax-b"),
        )
        tax = TaxMappingSetupReview(items=(
            TaxMappingSetupItem("tax-a", action_owner="HUMAN", affected_row_count=7),
            TaxMappingSetupItem("tax-b", affected_row_count=88),
        ))
        queue = build_company_review_work_queue(
            review, tax, trade_partner_confirmed=False
        )
        self.assertEqual(queue.trade_partner_policy_settings, 1)
        self.assertEqual(queue.trade_partner_affected_journals, 47)
        self.assertEqual(queue.trade_partner_affected_rows, 47)
        self.assertEqual(queue.other_optional_field_occurrences, 26)
        self.assertEqual(queue.other_optional_affected_journals, 26)
        self.assertEqual(queue.other_optional_affected_rows, 142)
        self.assertEqual(queue.optional_affected_journals, 73)
        self.assertEqual(queue.tax_human_settings, 1)
        self.assertEqual(queue.tax_evidence_settings, 1)
        self.assertEqual(queue.tax_evidence_rows, 88)

        confirmed = build_company_review_work_queue(
            review, tax, trade_partner_confirmed=True
        )
        self.assertEqual(confirmed.trade_partner_policy_settings, 0)
        self.assertEqual(confirmed.trade_partner_affected_journals, 47)


if __name__ == "__main__":
    unittest.main()

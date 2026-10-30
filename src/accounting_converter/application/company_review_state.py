from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from accounting_converter.application.company_mapping_update import CompanyMappingUpdateReview
from accounting_converter.application.moneyforward_profile_setup import TaxMappingSetupReview


@dataclass(frozen=True)
class CompanyReviewWorkQueue:
    company_setting_id: str
    source_path: Path | None
    account_settings: int
    subaccount_settings: int
    subaccount_affected_journals: int
    subaccount_review_ids: tuple[str, ...]
    description_settings: int
    tax_observed: int
    tax_human_settings: int
    tax_system_settings: int
    tax_evidence_settings: int
    tax_evidence_rows: int
    trade_partner_policy_settings: int
    trade_partner_affected_journals: int
    trade_partner_affected_rows: int
    other_optional_field_occurrences: int
    other_optional_affected_journals: int
    other_optional_affected_rows: int
    optional_affected_journals: int
    unsupported_journals: int


def build_company_review_work_queue(
    review: CompanyMappingUpdateReview,
    tax_review: TaxMappingSetupReview | None,
    *,
    trade_partner_confirmed: bool,
) -> CompanyReviewWorkQueue:
    optional = dict(review.optional_field_counts)
    optional_rows = dict(review.optional_field_row_counts)
    tax_items = tax_review.items if tax_review is not None else ()
    evidence_items = tuple(
        item for item in tax_items if item.action_owner == "SYSTEM_EVIDENCE"
    )
    partner_count = optional.get("trade_partner", 0)
    return CompanyReviewWorkQueue(
        company_setting_id=review.company_setting_id,
        source_path=review.source_path,
        account_settings=sum(item.mapping_type == "ACCOUNT" for item in review.items),
        subaccount_settings=sum(
            item.mapping_type in {"SUBACCOUNT", "DEFAULT_SUBACCOUNT"}
            for item in review.items
        ),
        subaccount_affected_journals=sum(
            item.affected_journal_count for item in review.items
            if item.mapping_type in {"SUBACCOUNT", "DEFAULT_SUBACCOUNT"}
        ),
        subaccount_review_ids=tuple(
            hashlib.sha256(item.key.encode("utf-8")).hexdigest()[:12]
            for item in review.items
            if item.mapping_type in {"SUBACCOUNT", "DEFAULT_SUBACCOUNT"}
        ),
        description_settings=len(review.descriptions),
        tax_observed=len(review.observed_tax_categories or review.tax_categories),
        tax_human_settings=sum(
            item.action_owner == "HUMAN" for item in tax_items
        ),
        tax_system_settings=sum(
            item.action_owner != "HUMAN" for item in tax_items
        ),
        tax_evidence_settings=len(evidence_items),
        tax_evidence_rows=sum(item.affected_row_count for item in evidence_items),
        trade_partner_policy_settings=int(partner_count > 0 and not trade_partner_confirmed),
        trade_partner_affected_journals=partner_count,
        trade_partner_affected_rows=optional_rows.get("trade_partner", 0),
        other_optional_field_occurrences=sum(
            count for field, count in optional.items() if field != "trade_partner"
        ),
        other_optional_affected_journals=review.other_optional_journal_count,
        other_optional_affected_rows=review.other_optional_row_count,
        optional_affected_journals=review.optional_field_blocker_count,
        unsupported_journals=review.unsupported_shape_count,
    )

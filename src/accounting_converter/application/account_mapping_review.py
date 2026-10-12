from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from accounting_converter.application.jdl_master_observation import (
    JdlMasterObservation,
    JdlPrintedAccount,
)
from accounting_converter.application.mapping_review import (
    MappingRequirement,
    MappingRequirementExtractor,
)
from accounting_converter.domain.conversion_profile import ConversionProfile
from accounting_converter.domain.journal import JournalEntry
from accounting_converter.domain.mapping import MappingStatus


class AccountCandidateClassification(str, Enum):
    EXACT_CANDIDATE = "EXACT_CANDIDATE"
    NO_CANDIDATE = "NO_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID_CONFLICT = "INVALID_CONFLICT"


@dataclass(frozen=True)
class AccountMappingReviewItem:
    requirement: MappingRequirement
    classification: AccountCandidateClassification
    exact_candidate: JdlPrintedAccount | None
    selectable_targets: tuple[JdlPrintedAccount, ...]
    debit_usage_count: int
    credit_usage_count: int
    related_subaccount_requirement_count: int
    confirmed: bool
    blocker_reason: str | None

    @property
    def usable(self) -> bool:
        return self.confirmed and self.blocker_reason is None


@dataclass(frozen=True)
class AccountMappingReviewResult:
    items: tuple[AccountMappingReviewItem, ...]
    journal_count: int
    journals_affected_by_unresolved_accounts: int

    def privacy_safe_summary(self) -> dict[str, int]:
        counts = Counter(item.classification.value for item in self.items)
        return {
            "total_requirements": len(self.items),
            "exact_candidate_count": counts["EXACT_CANDIDATE"],
            "no_candidate_count": counts["NO_CANDIDATE"],
            "ambiguous_count": counts["AMBIGUOUS"],
            "invalid_conflict_count": counts["INVALID_CONFLICT"],
            "confirmed_count": sum(item.confirmed for item in self.items),
            "unresolved_count": sum(not item.usable for item in self.items),
            "journals_affected_by_unresolved_accounts": (
                self.journals_affected_by_unresolved_accounts
            ),
            "subaccount_dependent_requirement_count": sum(
                item.related_subaccount_requirement_count > 0 for item in self.items
            ),
        }

    def private_report(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "summary": self.privacy_safe_summary(),
            "items": [
                {
                    "source_account": item.requirement.source_value,
                    "usage_count": item.requirement.occurrence_count,
                    "debit_usage_count": item.debit_usage_count,
                    "credit_usage_count": item.credit_usage_count,
                    "related_subaccount_requirement_count": (
                        item.related_subaccount_requirement_count
                    ),
                    "classification": item.classification.value,
                    "candidate": (
                        {
                            "code": item.exact_candidate.code,
                            "name": item.exact_candidate.name,
                        }
                        if item.exact_candidate is not None
                        else None
                    ),
                    "confirmation_status": (
                        "USER_CONFIRMED" if item.confirmed else "UNRESOLVED"
                    ),
                    "blocker_reason": item.blocker_reason,
                }
                for item in self.items
            ],
            "privacy_notice": (
                "PRIVATE LOCAL REPORT: contains customer-specific account identities; "
                "do not commit or share."
            ),
        }


class AccountMappingReviewService:
    """Builds an exact-only review over observed requirements and a JDL master."""

    def build(
        self,
        entries: Sequence[JournalEntry],
        master: JdlMasterObservation,
        profile: ConversionProfile | None = None,
    ) -> AccountMappingReviewResult:
        requirements = MappingRequirementExtractor().extract(entries, profile)
        usage: dict[str, Counter[str]] = defaultdict(Counter)
        affected: set[int] = set()
        for index, entry in enumerate(entries):
            for line in entry.lines:
                usage[line.account][line.side.value] += 1

        targets = tuple(
            sorted(
                (item for item in master.printed_accounts if item.enabled),
                key=lambda item: (item.code, item.name),
            )
        )
        by_name: dict[str, list[JdlPrintedAccount]] = defaultdict(list)
        for target in targets:
            by_name[target.name].append(target)
        subaccount_counts = Counter(
            item.parent_account for item in requirements.subaccounts
        )

        items: list[AccountMappingReviewItem] = []
        global_conflict = bool(master.conflicts)
        for requirement in requirements.accounts:
            candidates = tuple(by_name.get(requirement.source_value, ()))
            if global_conflict:
                classification = AccountCandidateClassification.INVALID_CONFLICT
                candidate = None
                blocker = "MASTER_CONFLICT"
            elif len(candidates) == 1:
                classification = AccountCandidateClassification.EXACT_CANDIDATE
                candidate = candidates[0]
                blocker = None
            elif not candidates:
                classification = AccountCandidateClassification.NO_CANDIDATE
                candidate = None
                blocker = "EXPLICIT_TARGET_SELECTION_REQUIRED"
            else:
                classification = AccountCandidateClassification.AMBIGUOUS
                candidate = None
                blocker = "AMBIGUOUS_EXACT_IDENTITY"

            confirmed = requirement.current_mapping_status is MappingStatus.USER_CONFIRMED
            selected_target_exists = any(
                target.name == requirement.current_target_value for target in targets
            )
            if confirmed and selected_target_exists and not global_conflict:
                blocker = None
            elif confirmed and not selected_target_exists:
                blocker = "CONFIRMED_TARGET_NOT_IN_CONTEXT"
            else:
                blocker = blocker or "USER_CONFIRMATION_REQUIRED"
            items.append(
                AccountMappingReviewItem(
                    requirement=requirement,
                    classification=classification,
                    exact_candidate=candidate,
                    selectable_targets=targets,
                    debit_usage_count=usage[requirement.source_value]["DEBIT"],
                    credit_usage_count=usage[requirement.source_value]["CREDIT"],
                    related_subaccount_requirement_count=subaccount_counts[
                        requirement.source_value
                    ],
                    confirmed=confirmed,
                    blocker_reason=blocker,
                )
            )

        unresolved = {item.requirement.source_value for item in items if not item.usable}
        for index, entry in enumerate(entries):
            if any(line.account in unresolved for line in entry.lines):
                affected.add(index)
        return AccountMappingReviewResult(tuple(items), len(entries), len(affected))
